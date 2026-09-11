"""End-to-end tests for the centralized Conan version rewrite hooks."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from hooks import conan_version_merge_driver as driver
from hooks import conan_version_post_rewrite as rewriter


ROOT = Path(__file__).parents[1]
MERGE_DRIVER = ROOT / 'hooks' / 'conan_version_merge_driver.py'
POST_REWRITE = ROOT / 'hooks' / 'conan_version_post_rewrite.py'
VERSION_REGEX = r'^version=(\d+(?:\.\d+)+)$'
MESSAGE_REGEX = r'^\[feature\]\[\d+(?:\.\d+)+\] .+$'


def run(root: Path, *arguments: str, input_data: str | None = None, env: dict[str, str] | None = None) -> str:
    process = subprocess.run(
        ['git', *arguments],
        cwd=root,
        input=input_data,
        text=True,
        encoding='utf-8',
        capture_output=True,
        env=env,
        check=True,
    )
    return process.stdout.strip()


class TemporaryRepository:
    def __init__(self, base_version: str = '1.2.3') -> None:
        self.base_version = base_version

    def __enter__(self) -> 'TemporaryRepository':
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)
        run(self.path, 'init', '-q', '-b', 'master')
        run(self.path, 'config', 'user.name', 'Test User')
        run(self.path, 'config', 'user.email', 'test@example.invalid')
        (self.path / '.gitattributes').write_text('version.txt merge=conan-version\n', encoding='utf-8')
        self.write_version(self.base_version)
        self.commit(f'[feature][{self.base_version}] base')
        self.write_pre_commit_config()
        run(self.path, 'config', 'merge.conan-version.driver',
            'pre-commit run conan-version-merge-driver --hook-stage manual --files %O %A %B')
        run(self.path, 'config', 'rebase.backend', 'merge')
        run(self.path, 'config', 'rebase.updateRefs', 'false')
        subprocess.run(
            ['pre-commit', 'install', '--hook-type', 'post-rewrite'],
            cwd=self.path, check=True, capture_output=True, text=True, encoding='utf-8')
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.directory.cleanup()

    def write_pre_commit_config(self) -> None:
        self.path.joinpath('.pre-commit-config.yaml').write_text(
            'repos:\n'
            '  - repo: local\n'
            '    hooks:\n'
            '      - id: conan-version-merge-driver\n'
            '        name: centralized merge driver\n'
            f'        entry: {sys.executable} {MERGE_DRIVER}\n'
            '        language: system\n'
            '        stages: [manual]\n'
            '        pass_filenames: true\n'
            '        require_serial: true\n'
            '        always_run: true\n'
            '        args:\n'
            f"          - '--version-regex={VERSION_REGEX}'\n"
            '      - id: conan-version-post-rewrite\n'
            '        name: centralized post rewrite\n'
            f'        entry: {sys.executable} {POST_REWRITE}\n'
            '        language: system\n'
            '        stages: [post-rewrite]\n'
            '        pass_filenames: false\n'
            '        always_run: true\n'
            '        args:\n'
            '          - --version-file=version.txt\n'
            f"          - '--version-regex={VERSION_REGEX}'\n"
            f"          - '--commit-message-regex={MESSAGE_REGEX}'\n",
            encoding='utf-8')

    def write_version(self, version: str) -> None:
        self.path.joinpath('version.txt').write_text(f'version={version}\n', encoding='utf-8')

    def commit(self, message: str) -> None:
        run(self.path, 'add', '.')
        run(self.path, 'commit', '--no-verify', '-qm', message)

    def version_commit(self, version: str, message: str, file_name: str) -> str:
        self.write_version(version)
        self.path.joinpath(file_name).write_text(f'{file_name}\n', encoding='utf-8')
        self.commit(message)
        return self.head()

    def head(self) -> str:
        return run(self.path, 'rev-parse', 'HEAD')

    def subject(self) -> str:
        return run(self.path, 'log', '-1', '--format=%s')

    def message(self) -> str:
        return run(self.path, 'log', '-1', '--format=%B')

    def version(self) -> str:
        return self.path.joinpath('version.txt').read_text(encoding='utf-8').strip().split('=', 1)[1]

    def rebase(self, interactive: bool = False, action: str = 'squash', message: str | None = None,
               update_refs: bool | None = None) -> None:
        command = ['rebase']
        if update_refs is True:
            command.append('--update-refs')
        elif update_refs is False:
            command.append('--no-update-refs')
        environment = os.environ.copy()
        if interactive:
            editor = self.path / 'sequence_editor.py'
            editor.write_text(
                'from pathlib import Path\nimport sys\n'
                'path = Path(sys.argv[1])\n'
                "lines = path.read_text(encoding='utf-8').splitlines()\n"
                f"lines[1] = lines[1].replace('pick ', '{action} ', 1)\n"
                "path.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')\n",
                encoding='utf-8')
            environment['GIT_SEQUENCE_EDITOR'] = f'{sys.executable} {editor}'
            if message is None:
                environment['GIT_EDITOR'] = 'true'
            else:
                editor = self.path / 'message_editor.py'
                editor.write_text(
                    'from pathlib import Path\nimport sys\n'
                    f'Path(sys.argv[1]).write_text({message!r}, encoding="utf-8")\n',
                    encoding='utf-8')
                environment['GIT_EDITOR'] = f'{sys.executable} {editor}'
            command.append('-i')
        run(self.path, *command, 'master', env=environment)


class ConanVersionMergeDriverTests(unittest.TestCase):
    def test_rejects_invalid_versions_and_non_version_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('base', 'ours', 'theirs')]
            for path, version in zip(paths, ('1.2.3', '1.2.4', '01.2.4')):
                path.write_text(f'version={version}\n', encoding='utf-8')
            self.assertEqual(driver.ERROR, driver.merge_files(*map(str, paths), driver.VersionCodec(VERSION_REGEX)))

            paths[2].write_text('not-a-version\n', encoding='utf-8')
            self.assertEqual(driver.ERROR, driver.merge_files(*map(str, paths), driver.VersionCodec(VERSION_REGEX)))

    def test_preserves_non_version_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('base', 'ours', 'theirs')]
            contents = ('version=1.2.3\nvalue=base\n', 'version=1.2.4\nvalue=ours\n', 'version=1.3.0\nvalue=theirs\n')
            for path, content in zip(paths, contents):
                path.write_text(content, encoding='utf-8')
            self.assertEqual(driver.CONFLICT, driver.merge_files(*map(str, paths), driver.VersionCodec(VERSION_REGEX)))
            self.assertIn('version=1.3.0', paths[1].read_text(encoding='utf-8'))

    def test_supports_two_four_and_five_segment_versions(self) -> None:
        cases = (
            ('1.2', '1.2', '1.3', '1.3'),
            ('1.2.3.4', '1.2.3.5', '1.2.4.0', '1.2.4.0'),
            ('1.2.3.4.5', '1.2.3.4.6', '1.2.3.5.0', '1.2.3.5.0'),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('base', 'ours', 'theirs')]
            for base, ours, theirs, expected in cases:
                for path, version in zip(paths, (base, ours, theirs)):
                    path.write_text(f'version={version}\n', encoding='utf-8')
                self.assertEqual(driver.SUCCESS, driver.merge_files(*map(str, paths), driver.VersionCodec(VERSION_REGEX)))
                self.assertEqual(f'version={expected}\n', paths[1].read_text(encoding='utf-8'))

    def test_applies_a_low_segment_bump_to_a_higher_remote_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('base', 'ours', 'theirs')]
            for path, version in zip(paths, ('1.2.3.4', '1.3.0.0', '1.2.3.5')):
                path.write_text(f'version={version}\n', encoding='utf-8')
            self.assertEqual(driver.SUCCESS, driver.merge_files(*map(str, paths), driver.VersionCodec(VERSION_REGEX)))
            self.assertEqual('version=1.3.0.1\n', paths[1].read_text(encoding='utf-8'))

    def test_rejects_segment_count_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('base', 'ours', 'theirs')]
            for path, version in zip(paths, ('1.2.3', '1.2.3.4', '1.2.4')):
                path.write_text(f'version={version}\n', encoding='utf-8')
            self.assertEqual(driver.ERROR, driver.merge_files(*map(str, paths), driver.VersionCodec(VERSION_REGEX)))


class ConanVersionRewriteEndToEndTests(unittest.TestCase):
    def prepare_branches(self, remote: str, local: str, base: str = '1.2.3') -> TemporaryRepository:
        repository = TemporaryRepository(base).__enter__()
        self.addCleanup(repository.__exit__, None, None, None)
        run(repository.path, 'branch', 'local')
        repository.version_commit(remote, f'[feature][{remote}] remote', 'remote.txt')
        run(repository.path, 'checkout', '-q', 'local')
        repository.version_commit(local, f'[feature][{local}] local', 'local.txt')
        return repository

    def test_remote_patch_local_minor_uses_central_manual_driver(self) -> None:
        repository = self.prepare_branches('1.2.4', '1.3.0')
        repository.rebase()
        self.assertEqual('pre-commit run conan-version-merge-driver --hook-stage manual --files %O %A %B',
                         run(repository.path, 'config', '--get', 'merge.conan-version.driver'))
        self.assertEqual('1.3.0', repository.version())
        self.assertEqual('[feature][1.3.0] local', repository.subject())

    def test_two_remote_patches_and_local_patch_are_rebased_in_order(self) -> None:
        with TemporaryRepository() as repository:
            run(repository.path, 'branch', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] remote one', 'remote-one.txt')
            repository.version_commit('1.2.5', '[feature][1.2.5] remote two', 'remote-two.txt')
            run(repository.path, 'checkout', '-q', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] local', 'local.txt')
            repository.rebase()
            self.assertEqual('1.2.6', repository.version())
            self.assertEqual('[feature][1.2.6] local', repository.subject())

    def test_four_segment_remote_low_bump_and_local_high_bump(self) -> None:
        with TemporaryRepository('1.2.3.4') as repository:
            run(repository.path, 'branch', 'local')
            repository.version_commit('1.2.3.5', '[feature][1.2.3.5] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'local')
            repository.version_commit('1.2.4.0', '[feature][1.2.4.0] local', 'local.txt')
            repository.rebase()
            self.assertEqual('1.2.4.0', repository.version())
            self.assertEqual('[feature][1.2.4.0] local', repository.subject())

    def test_trivial_same_version_is_normalized(self) -> None:
        repository = self.prepare_branches('1.2.4', '1.2.4')
        repository.rebase()
        self.assertEqual('1.2.5', repository.version())
        self.assertEqual('[feature][1.2.5] local', repository.subject())

    def test_squash_patch_and_minor_uses_highest_bump_once(self) -> None:
        with TemporaryRepository() as repository:
            run(repository.path, 'branch', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] patch', 'patch.txt')
            repository.version_commit('1.3.0', '[feature][1.3.0] minor', 'minor.txt')
            repository.rebase(interactive=True, message='[feature][1.3.0] aggregate\n')
            self.assertEqual('1.3.0', repository.version())
            self.assertEqual(1, int(run(repository.path, 'rev-list', '--count', 'master..HEAD')))
            self.assertEqual('[feature][1.3.0] aggregate', repository.message())

    def test_four_segment_squash_uses_the_highest_bump_once(self) -> None:
        with TemporaryRepository('1.2.3.4') as repository:
            run(repository.path, 'branch', 'local')
            repository.version_commit('1.2.3.5', '[feature][1.2.3.5] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'local')
            repository.version_commit('1.2.3.5', '[feature][1.2.3.5] low', 'low.txt')
            repository.version_commit('1.2.4.0', '[feature][1.2.4.0] high', 'high.txt')
            repository.rebase(interactive=True, message='[feature][1.2.4.0] aggregate\n')
            self.assertEqual('1.2.4.0', repository.version())
            self.assertEqual(1, int(run(repository.path, 'rev-list', '--count', 'master..HEAD')))
            self.assertEqual('[feature][1.2.4.0] aggregate', repository.message())

    def test_default_squash_message_is_not_normalized_after_post_rewrite_failure(self) -> None:
        with TemporaryRepository() as repository:
            run(repository.path, 'branch', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] patch', 'patch.txt')
            repository.version_commit('1.3.0', '[feature][1.3.0] minor', 'minor.txt')
            repository.rebase(interactive=True)
            self.assertEqual('[feature][1.2.4] patch\n\n[feature][1.3.0] minor', repository.message())

    def test_rejects_no_op_singleton_and_group(self) -> None:
        for squash in (False, True):
            with self.subTest(squash=squash), TemporaryRepository() as repository:
                repository.path.joinpath('first.txt').write_text('first\n', encoding='utf-8')
                repository.commit('[feature][1.2.3] first')
                first = repository.head()
                records = [(first, first)]
                done = f'pick {first} first\n'
                orig_head = first
                if squash:
                    repository.path.joinpath('second.txt').write_text('second\n', encoding='utf-8')
                    repository.commit('[feature][1.2.3] second')
                    second = repository.head()
                    records = [(first, second), (second, second)]
                    done += f'squash {second} second\n'
                    orig_head = second
                state = repository.path / '.git' / 'rebase-merge'
                state.mkdir()
                state.joinpath('done').write_text(done, encoding='utf-8')
                state.joinpath('orig-head').write_text(f'{orig_head}\n', encoding='utf-8')
                with self.assertRaisesRegex(rewriter.NormalizationError, 'must contain a version bump'):
                    rewriter.normalize(records, 'version.txt', VERSION_REGEX, MESSAGE_REGEX, repository.path)

    def test_checkout_failure_cas_rolls_back_the_branch_ref(self) -> None:
        with TemporaryRepository() as repository:
            provisional = repository.version_commit('1.2.4', '[feature][1.2.3] patch', 'patch.txt')
            state = repository.path / '.git' / 'rebase-merge'
            state.mkdir()
            state.joinpath('done').write_text(f'pick {provisional} patch\n', encoding='utf-8')
            state.joinpath('orig-head').write_text(f'{provisional}\n', encoding='utf-8')
            calls: list[list[str]] = []
            original_run = rewriter.Git.run

            def fail_final_checkout(git: rewriter.Git, arguments: list[str], input_data: bytes | None = None,
                                    env: dict[str, str] | None = None) -> bytes:
                calls.append(arguments)
                if arguments[:3] == ['read-tree', '--reset', '-u'] and arguments[-1] != provisional:
                    raise rewriter.NormalizationError('injected final checkout failure')
                return original_run(git, arguments, input_data, env)

            with mock.patch.object(rewriter.Git, 'run', new=fail_final_checkout):
                with self.assertRaisesRegex(rewriter.NormalizationError, 'CAS rollback restored'):
                    rewriter.normalize([(provisional, provisional)], 'version.txt', VERSION_REGEX,
                                       MESSAGE_REGEX, repository.path)
            self.assertEqual(provisional, repository.head())
            self.assertIn(['read-tree', '--reset', '-u', provisional], calls)

    def test_fixup_no_op_is_retained(self) -> None:
        with TemporaryRepository() as repository:
            run(repository.path, 'branch', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'local')
            repository.version_commit('1.2.4', '[feature][1.2.4] patch', 'patch.txt')
            repository.path.joinpath('fixup.txt').write_text('fixup\n', encoding='utf-8')
            repository.commit('fixup! [feature][1.2.4] patch')
            repository.rebase(interactive=True, action='fixup')
            self.assertEqual('1.2.5', repository.version())
            self.assertTrue(repository.path.joinpath('fixup.txt').exists())

    def test_empty_stdin_uses_rewritten_list(self) -> None:
        with TemporaryRepository() as repository:
            old = repository.version_commit('1.2.4', '[feature][1.2.4] old', 'old.txt')
            state = repository.path / '.git' / 'rebase-merge'
            state.mkdir()
            state.joinpath('rewritten-list').write_text(f'{old} {old}\n', encoding='utf-8')
            records = rewriter.mapping_records(rewriter.Git(repository.path), io.StringIO(''))
            self.assertEqual([(old, old)], records)

    def test_update_refs_keeps_secondary_branch_at_git_provisional_commit(self) -> None:
        with TemporaryRepository() as repository:
            run(repository.path, 'branch', 'feature')
            repository.version_commit('1.2.4', '[feature][1.2.4] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'feature')
            repository.version_commit('1.2.4', '[feature][1.2.4] first', 'first.txt')
            run(repository.path, 'branch', 'secondary')
            repository.version_commit('1.2.5', '[feature][1.2.5] second', 'second.txt')
            run(repository.path, 'config', 'rebase.updateRefs', 'true')

            repository.rebase()

            secondary = run(repository.path, 'rev-parse', 'secondary')
            self.assertNotEqual(repository.head(), secondary)
            self.assertEqual('version=1.2.4', run(repository.path, 'show', f'{secondary}:version.txt'))
            self.assertEqual('[feature][1.2.4] first', run(repository.path, 'log', '-1', '--format=%s', secondary))
            self.assertEqual('1.2.6', repository.version())

    def test_no_update_refs_override_does_not_move_secondary_branch(self) -> None:
        with TemporaryRepository() as repository:
            run(repository.path, 'branch', 'feature')
            repository.version_commit('1.2.4', '[feature][1.2.4] remote', 'remote.txt')
            run(repository.path, 'checkout', '-q', 'feature')
            secondary = repository.version_commit('1.2.4', '[feature][1.2.4] local', 'local.txt')
            run(repository.path, 'branch', 'secondary', secondary)
            run(repository.path, 'config', 'rebase.updateRefs', 'true')

            repository.rebase(update_refs=False)

            self.assertEqual(secondary, run(repository.path, 'rev-parse', 'secondary'))


if __name__ == '__main__':
    unittest.main()
