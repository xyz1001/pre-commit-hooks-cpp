"""Normalize version files and commit messages after a merge-backend rebase."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence

try:
    from hooks import conan_version_merge_driver as version_driver
except ModuleNotFoundError:
    import conan_version_merge_driver as version_driver


OID = re.compile(r'^[0-9a-f]{40}(?:[0-9a-f]{24})?$')
MESSAGE_VERSION = re.compile(r'\[(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+\]')


class NormalizationError(Exception):
    pass


class Git:
    def __init__(self, root: Path):
        self.root = root

    def run(self, arguments: list[str], input_data: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
        environment = os.environ.copy()
        if env:
            environment.update(env)
        process = subprocess.run(
            ['git', *arguments], cwd=self.root, input=input_data,
            capture_output=True, env=environment,
        )
        if process.returncode:
            message = process.stderr.decode('utf-8', errors='replace').strip()
            raise NormalizationError(f"git {' '.join(arguments)} failed: {message}")
        return process.stdout

    def text(self, arguments: list[str], input_data: bytes | None = None, env: dict[str, str] | None = None) -> str:
        try:
            return self.run(arguments, input_data, env).decode('utf-8').strip()
        except UnicodeDecodeError as error:
            raise NormalizationError('Git returned non-UTF-8 text') from error

    def config_bool(self, key: str) -> str | None:
        process = subprocess.run(['git', 'config', '--bool', '--get', key], cwd=self.root, capture_output=True)
        if process.returncode == 1:
            return None
        if process.returncode:
            raise NormalizationError(f'cannot read Git config {key}')
        return process.stdout.decode('utf-8').strip()


def git_path(git: Git, name: str) -> Path:
    path = Path(git.text(['rev-parse', '--git-path', name]))
    return path if path.is_absolute() else git.root / path


def commit_parent(git: Git, commit: str) -> str:
    try:
        headers = git.run(['cat-file', '-p', commit]).split(b'\n\n', 1)[0].decode('utf-8')
    except UnicodeDecodeError as error:
        raise NormalizationError('commit header is not UTF-8') from error
    parents = [line[7:] for line in headers.splitlines() if line.startswith('parent ')]
    if len(parents) != 1 or not OID.fullmatch(parents[0]):
        raise NormalizationError('only single-parent commits are supported')
    return parents[0]


def verify_commit(git: Git, oid: str) -> None:
    if not OID.fullmatch(oid) or git.text(['rev-parse', '--verify', f'{oid}^{{commit}}']) != oid:
        raise NormalizationError('post-rewrite mapping does not name a commit')


def version_from_commit(git: Git, commit: str, version_file: str, codec: version_driver.VersionCodec) -> tuple[int, ...]:
    try:
        return codec.version_from(git.run(['show', f'{commit}:{version_file}']).decode('utf-8'), commit)
    except (UnicodeDecodeError, version_driver.VersionError) as error:
        raise NormalizationError(str(error)) from error


def intent_for_old_commit(git: Git, old: str, version_file: str, codec: version_driver.VersionCodec) -> int | None:
    before = version_from_commit(git, commit_parent(git, old), version_file, codec)
    after = version_from_commit(git, old, version_file, codec)
    if before == after:
        return None
    try:
        return version_driver.bump_kind(before, after)
    except version_driver.VersionError as error:
        raise NormalizationError(f'{old} has an invalid version bump') from error


def parse_mappings(data: str) -> list[tuple[str, str]]:
    records = []
    for line in data.splitlines():
        fields = line.split()
        if len(fields) != 2 or not all(OID.fullmatch(field) for field in fields):
            raise NormalizationError('post-rewrite mapping line must contain two commit OIDs')
        records.append((fields[0], fields[1]))
    if not records:
        raise NormalizationError('post-rewrite mapping is empty')
    return records


def mapping_records(git: Git, stdin: object) -> list[tuple[str, str]]:
    data = stdin.read()
    if data.strip():
        return parse_mappings(data)
    path = git_path(git, 'rebase-merge/rewritten-list')
    if not path.exists():
        raise NormalizationError('post-rewrite mapping is empty and rewritten-list is unavailable')
    return parse_mappings(path.read_text(encoding='utf-8'))


def group_mappings(records: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    old_seen = set()
    new_completed = set()
    groups: list[tuple[str, list[str]]] = []
    for old, new in records:
        if old in old_seen:
            raise NormalizationError('post-rewrite mapping repeats an old commit OID')
        old_seen.add(old)
        if groups and new == groups[-1][0]:
            groups[-1][1].append(old)
        else:
            if new in new_completed:
                raise NormalizationError('post-rewrite mapping repeats a non-consecutive new commit OID')
            if groups:
                new_completed.add(groups[-1][0])
            groups.append((new, [old]))
    return groups


def validate_rebase_interval(git: Git, groups: list[tuple[str, list[str]]]) -> None:
    done = git_path(git, 'rebase-merge/done')
    orig_head = git_path(git, 'rebase-merge/orig-head')
    if not done.exists() or not orig_head.exists():
        raise NormalizationError('merge-backend rebase done or orig-head state is unavailable')
    expected = {old for _, olds in groups for old in olds}
    done_oids = set()
    for line in done.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        fields = line.split(maxsplit=2)
        if len(fields) < 2 or fields[0] not in {'pick', 'p', 'squash', 's', 'fixup', 'f'}:
            raise NormalizationError('rebase done contains an unsupported command')
        done_oids.add(git.text(['rev-parse', '--verify', f'{fields[1]}^{{commit}}']))
    if done_oids != expected:
        raise NormalizationError('mapped old commits do not exactly match rebase done')
    current = orig_head.read_text(encoding='utf-8').strip()
    walked = set()
    while current in expected:
        if current in walked:
            raise NormalizationError('original rebase interval contains a cycle')
        walked.add(current)
        current = commit_parent(git, current)
    if walked != expected:
        raise NormalizationError('mapped old commits are not the complete orig-head interval')


def update_refs_pending(git: Git) -> bool:
    for name in ('rebase-merge/update-refs', 'rebase-apply/update-refs'):
        path = git_path(git, name)
        if path.exists() and path.read_text(encoding='utf-8').strip():
            return True
    return False


def tree_with_version(
        git: Git, commit: str, version_file: str, codec: version_driver.VersionCodec,
        version: str, index_path: Path) -> str:
    entry = git.run(['ls-tree', '-z', commit, '--', version_file]).split(b'\0')
    if len(entry) != 2 or not entry[0]:
        raise NormalizationError(f'commit does not contain {version_file}')
    try:
        metadata, path = entry[0].split(b'\t', 1)
        mode, object_type, _ = metadata.decode('ascii').split()
    except (UnicodeDecodeError, ValueError) as error:
        raise NormalizationError('invalid version-file tree entry') from error
    if path != version_file.encode() or object_type != 'blob':
        raise NormalizationError('invalid version-file tree entry')
    content = git.run(['show', f'{commit}:{version_file}']).decode('utf-8')
    try:
        content = codec.replace(content, version).encode('utf-8')
    except (UnicodeDecodeError, version_driver.VersionError) as error:
        raise NormalizationError('cannot replace version-file version') from error
    env = {'GIT_INDEX_FILE': str(index_path)}
    git.run(['read-tree', f'{commit}^{{tree}}'], env=env)
    blob = git.text(['hash-object', '-w', '--stdin'], content)
    git.run(['update-index', '--add', '--cacheinfo', f'{mode},{blob},{version_file}'], env=env)
    return git.text(['write-tree'], env=env)


def rebuild_commit(
        git: Git, provisional: str, tree: str, parent: str, version: str,
        message_pattern: re.Pattern[str] | None) -> str:
    try:
        headers, message = git.run(['cat-file', 'commit', provisional]).split(b'\n\n', 1)
        lines = headers.decode('utf-8').splitlines()
        message = message.decode('utf-8')
    except (UnicodeDecodeError, ValueError) as error:
        raise NormalizationError('commit is not valid UTF-8') from error
    rebuilt = []
    trees = parents = 0
    for line in lines:
        if not re.fullmatch(r'[A-Za-z0-9-]+ .+', line) or line.startswith(('gpgsig ', 'mergetag ')):
            raise NormalizationError('commit has an unsupported header')
        if line.startswith('tree '):
            trees += 1
            rebuilt.append(f'tree {tree}')
        elif line.startswith('parent '):
            parents += 1
            rebuilt.append(f'parent {parent}')
        else:
            rebuilt.append(line)
    if trees != 1 or parents != 1:
        raise NormalizationError('commit must contain one tree and one parent header')
    first, separator, remainder = message.partition('\n')
    match = MESSAGE_VERSION.search(first)
    if not match:
        raise NormalizationError('commit message first line must contain [x.y[.z...]]')
    message = first[:match.start()] + f'[{version}]' + first[match.end():] + separator + remainder
    if message_pattern and not message_pattern.fullmatch(message.rstrip('\n')):
        raise NormalizationError('rebuilt commit message violates --commit-message-regex')
    return git.text(['hash-object', '-t', 'commit', '-w', '--stdin'], ('\n'.join(rebuilt) + '\n\n' + message).encode())


def normalize(
        records: list[tuple[str, str]], version_file: str, version_regex: str,
        commit_message_regex: str | None, root: Path | None = None) -> str:
    git = Git(root or Path.cwd())
    codec = version_driver.VersionCodec(version_regex)
    try:
        message_pattern = re.compile(commit_message_regex, re.MULTILINE) if commit_message_regex else None
    except re.error as error:
        raise NormalizationError(f'invalid commit-message regex: {error}') from error
    groups = group_mappings(records)
    if git.config_bool('rebase.updateRefs') == 'true' or update_refs_pending(git):
        raise NormalizationError('rebase.updateRefs must be false')
    validate_rebase_interval(git, groups)
    tip = records[-1][1]
    branch = git.text(['symbolic-ref', '-q', 'HEAD'])
    if not branch.startswith('refs/heads/') or git.text(['rev-parse', 'HEAD']) != tip:
        raise NormalizationError('HEAD must be the provisional rewritten branch tip')
    parent = commit_parent(git, groups[0][0])
    current = version_from_commit(git, parent, version_file, codec)
    previous = None
    intents = []
    for new, olds in groups:
        verify_commit(git, new)
        if previous and commit_parent(git, new) != previous:
            raise NormalizationError('provisional commits are not a first-parent chain')
        for old in olds:
            verify_commit(git, old)
        source_version = version_from_commit(git, commit_parent(git, olds[0]), version_file, codec)
        if len(current) != len(source_version):
            raise NormalizationError('rewritten versions must have the same segment count')
        group_intents = [intent_for_old_commit(git, old, version_file, codec) for old in olds]
        intents_for_group = [intent for intent in group_intents if intent is not None]
        if not intents_for_group:
            raise NormalizationError('each rewritten group must contain a version bump')
        intents.append(min(intents_for_group))
        previous = new
    with tempfile.TemporaryDirectory() as directory:
        index = Path(directory) / 'index'
        for (new, _), intent in zip(groups, intents):
            current = version_driver.apply_bump(current, intent)
            version = '.'.join(map(str, current))
            tree = tree_with_version(git, new, version_file, codec, version, index)
            parent = rebuild_commit(git, new, tree, parent, version, message_pattern)
    git.run(['update-ref', branch, parent, tip])
    try:
        git.run(['read-tree', '--reset', '-u', parent])
    except NormalizationError as error:
        try:
            git.run(['update-ref', branch, tip, parent])
        except NormalizationError as rollback_error:
            raise NormalizationError(
                f'working-tree reset failed after advancing {branch}; '
                f'CAS rollback from {parent} to {tip} failed: {rollback_error}') from error
        try:
            git.run(['read-tree', '--reset', '-u', tip])
        except NormalizationError as restore_error:
            raise NormalizationError(
                f'working-tree reset failed after advancing {branch}; '
                f'CAS rollback restored {branch} to {tip}, but restoring the working tree failed: {restore_error}') from error
        raise NormalizationError(
            f'working-tree reset failed after advancing {branch}; '
            f'CAS rollback restored {branch} to provisional {tip}') from error
    return parent


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version-file', required=True)
    parser.add_argument('--version-regex', required=True)
    parser.add_argument('--commit-message-regex')
    parser.add_argument('--command')
    parser.add_argument('--mapping', nargs=2, action='append', metavar=('OLD', 'NEW'))
    arguments = parser.parse_args(argv)
    command = arguments.command or os.environ.get('PRE_COMMIT_REWRITE_COMMAND')
    if command != 'rebase':
        return 0
    try:
        git = Git(Path.cwd())
        records = arguments.mapping or mapping_records(git, sys.stdin)
        normalize(records, arguments.version_file, arguments.version_regex, arguments.commit_message_regex)
        return 0
    except (OSError, NormalizationError, version_driver.VersionError) as error:
        print(f'conan-version post-rewrite: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
