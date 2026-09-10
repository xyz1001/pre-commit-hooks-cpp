"""Merge driver that reapplies a rebased version-segment bump."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence


SUCCESS = 0
CONFLICT = 1
ERROR = 2
VERSION = re.compile(r'^(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))+$')
DEFAULT_VERSION_REGEX = r'^\s*version\s*=\s*["\'](\d+(?:\.\d+)+)["\']\s*$'


class VersionError(ValueError):
    pass


class VersionCodec:
    def __init__(self, pattern: str):
        try:
            self.pattern = re.compile(pattern, re.MULTILINE)
        except re.error as error:
            raise VersionError(f'invalid version regex: {error}') from error
        if self.pattern.groups != 1:
            raise VersionError('--version-regex must contain exactly one capture group')

    def match(self, content: str, label: str) -> re.Match[str]:
        matches = list(self.pattern.finditer(content))
        if len(matches) != 1:
            raise VersionError(f'{label} must contain exactly one version match')
        if not VERSION.fullmatch(matches[0].group(1)):
            raise VersionError(f'{label} has an invalid version: {matches[0].group(1)!r}')
        return matches[0]

    def version_from(self, content: str, label: str) -> tuple[int, ...]:
        return tuple(int(part) for part in self.match(content, label).group(1).split('.'))

    def replace(self, content: str, version: str) -> str:
        match = self.match(content, 'merged file')
        return content[:match.start(1)] + version + content[match.end(1):]


def read_text(path: str | Path) -> str:
    with open(path, encoding='utf-8', newline='') as file:
        return file.read()


def write_text(path: str | Path, content: str) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as file:
        file.write(content)


def require_same_segment_count(*versions: tuple[int, ...]) -> None:
    if len({len(version) for version in versions}) != 1:
        raise VersionError('versions must have the same segment count')


def bump_kind(base: tuple[int, ...], theirs: tuple[int, ...]) -> int:
    require_same_segment_count(base, theirs)
    for index, (before, after) in enumerate(zip(base, theirs)):
        if before != after:
            if after == before + 1 and all(part == 0 for part in theirs[index + 1:]):
                return index
            break
    raise VersionError('base-to-theirs change is not one exact version-segment bump')


def apply_bump(version: tuple[int, ...], index: int) -> tuple[int, ...]:
    if not 0 <= index < len(version):
        raise VersionError(f'invalid version-segment index: {index}')
    return version[:index] + (version[index] + 1,) + (0,) * (len(version) - index - 1)


def merge_files(
        base_path: str, ours_path: str, theirs_path: str, codec: VersionCodec) -> int:
    try:
        base = read_text(base_path)
        ours = read_text(ours_path)
        theirs = read_text(theirs_path)
        base_version = codec.version_from(base, 'base')
        ours_version = codec.version_from(ours, 'ours')
        theirs_version = codec.version_from(theirs, 'theirs')
        require_same_segment_count(base_version, ours_version, theirs_version)
        if ours_version < base_version:
            raise VersionError('ours version is lower than base version')
        version = '.'.join(map(str, apply_bump(ours_version, bump_kind(base_version, theirs_version))))
        placeholder = '.'.join('0' for _ in base_version)
        base = codec.replace(base, placeholder)
        ours = codec.replace(ours, placeholder)
        theirs = codec.replace(theirs, placeholder)
    except (OSError, UnicodeError, VersionError) as error:
        print(f'conan-version merge driver: {error}', file=sys.stderr)
        return ERROR

    try:
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('base', 'ours', 'theirs')]
            for path, content in zip(paths, (base, ours, theirs)):
                write_text(path, content)
            process = subprocess.run(
                ['git', 'merge-file', '-p', str(paths[1]), str(paths[0]), str(paths[2])],
                capture_output=True,
            )
    except OSError as error:
        print(f'conan-version merge driver: cannot run git merge-file: {error}', file=sys.stderr)
        return ERROR
    if process.returncode not in (SUCCESS, CONFLICT):
        print(process.stderr.decode('utf-8', errors='replace'), file=sys.stderr, end='')
        return ERROR
    try:
        write_text(ours_path, codec.replace(process.stdout.decode('utf-8'), version))
    except (UnicodeError, VersionError, OSError) as error:
        print(f'conan-version merge driver: {error}', file=sys.stderr)
        return ERROR
    return process.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version-regex', default=DEFAULT_VERSION_REGEX)
    parser.add_argument('paths', nargs=3, metavar='PATH', help='Git merge-driver files: %%O %%A %%B')
    arguments = parser.parse_args(argv)
    try:
        rebase_path = subprocess.run(
            ['git', 'rev-parse', '--git-path', 'rebase-merge'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        ).stdout.strip()
        if not Path(rebase_path).exists():
            print('conan-version merge driver: only merge-backend rebase is supported', file=sys.stderr)
            return ERROR
        return merge_files(*arguments.paths, VersionCodec(arguments.version_regex))
    except (OSError, subprocess.CalledProcessError, VersionError) as error:
        print(f'conan-version merge driver: {error}', file=sys.stderr)
        return ERROR


if __name__ == '__main__':
    raise SystemExit(main())
