"""Tests for the version-check hook."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from hooks.check_version import main


class CheckVersionTests(unittest.TestCase):
    version_regex = r'^version=(\d+(?:\.\d+)+)$'

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.git('init')
        self.git('config', 'user.name', 'Test User')
        self.git('config', 'user.email', 'test@example.com')
        self.write_version('1.0.0')
        self.git('add', 'version.txt')
        self.git('commit', '--no-verify', '-m', '[feature][1.0.0] initial')

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ['git', *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        return result.stdout

    def write_version(self, version: str) -> None:
        (self.root / 'version.txt').write_text(f'version={version}\n', encoding='utf-8')

    def stage_version(self, version: str) -> None:
        self.write_version(version)
        self.git('add', 'version.txt')

    def commit_version(self, version: str, message: str) -> None:
        self.stage_version(version)
        subprocess.run(
            ['git', 'commit', '--no-verify', '-F', '-'],
            cwd=self.root,
            input=message,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )

    def write_commit_message(self, message: str) -> Path:
        message_file = self.root / '.git' / 'COMMIT_EDITMSG'
        message_file.write_text(message, encoding='utf-8')
        return message_file

    def create_rebase_state(self, rebase_directory: str = 'rebase-merge') -> Path:
        path = Path(self.git('rev-parse', '--git-path', rebase_directory).strip())
        if not path.is_absolute():
            path = self.root / path
        path.mkdir()
        return path

    def run_hook(
            self, *extra_args: str, commit_msg_file: Path | None = None) -> tuple[int, str]:
        arguments = [
            '--version-file=version.txt',
            f'--version-regex={self.version_regex}',
            *extra_args,
        ]
        if commit_msg_file:
            arguments.append(str(commit_msg_file))

        previous_directory = Path.cwd()
        output = io.StringIO()
        os.chdir(self.root)
        try:
            with redirect_stderr(output):
                result = main(arguments)
        finally:
            os.chdir(previous_directory)
        return result, output.getvalue()

    def test_commit_msg_default_does_not_correct_message(self) -> None:
        self.stage_version('1.0.1')
        message_file = self.write_commit_message('[feature][1.0.0] title\n')

        result, output = self.run_hook(commit_msg_file=message_file)

        self.assertEqual(0, result)
        self.assertEqual('', output)
        self.assertEqual('[feature][1.0.0] title\n', message_file.read_text(encoding='utf-8'))

    def test_commit_msg_fix_replaces_first_version_and_preserves_body(self) -> None:
        self.stage_version('1.0.1')
        message = '[feature][1.0.0][PROJ-1] title\n\nwhy: retain [9.9.9]\n'
        message_file = self.write_commit_message(message)

        result, output = self.run_hook(
            '--fix-commit-message', commit_msg_file=message_file)

        self.assertEqual(0, result)
        self.assertEqual('', output)
        self.assertEqual(
            '[feature][1.0.1][PROJ-1] title\n\nwhy: retain [9.9.9]\n',
            message_file.read_text(encoding='utf-8'),
        )

    def test_commit_msg_fix_reads_version_from_index(self) -> None:
        self.stage_version('1.0.1')
        message_file = self.write_commit_message('[feature][1.0.0] title\n')

        result, _ = self.run_hook('--fix-commit-message', commit_msg_file=message_file)

        self.assertEqual(0, result)
        self.assertIn('[1.0.1]', message_file.read_text(encoding='utf-8'))

    def test_commit_msg_fix_rejects_missing_version(self) -> None:
        self.stage_version('1.0.1')
        message_file = self.write_commit_message('[feature] title\n')

        result, output = self.run_hook(
            '--fix-commit-message', commit_msg_file=message_file)

        self.assertEqual(1, result)
        self.assertIn('No version found', output)
        self.assertNotIn('git reset HEAD~1', output)
        self.assertNotIn('COMMIT MUST BE REVERTED', output)
        self.assertIn('The commit has not been created.', output)
        self.assertIn('retry the commit', output)
        self.assertEqual('[feature] title\n', message_file.read_text(encoding='utf-8'))

    def test_commit_msg_fixup_is_skipped(self) -> None:
        self.stage_version('1.0.1')
        message_file = self.write_commit_message('fixup! [feature][1.0.0] title\n')

        result, output = self.run_hook(
            '--fix-commit-message', commit_msg_file=message_file)

        self.assertEqual(0, result)
        self.assertEqual('', output)
        self.assertIn('[1.0.0]', message_file.read_text(encoding='utf-8'))

    def test_post_commit_fix_skips_validation_during_rebase(self) -> None:
        self.commit_version('1.0.1', '[feature][1.0.0] title')

        for rebase_directory in ('rebase-merge', 'rebase-apply'):
            with self.subTest(rebase_directory=rebase_directory):
                rebase_state = self.create_rebase_state(rebase_directory)
                result, output = self.run_hook('--fix-commit-message')
                rebase_state.rmdir()

                self.assertEqual(0, result)
                self.assertEqual('', output)

    def test_post_commit_without_fix_rejects_mismatch_during_rebase(self) -> None:
        self.commit_version('1.0.1', '[feature][1.0.0] title')
        self.create_rebase_state()

        result, output = self.run_hook()

        self.assertEqual(1, result)
        self.assertIn('Version mismatch', output)

    def test_post_commit_fix_rejects_invalid_version_increment_without_rebase(self) -> None:
        self.commit_version('1.0.2', '[feature][1.0.2] title')

        result, output = self.run_hook('--fix-commit-message')

        self.assertEqual(1, result)
        self.assertIn('Invalid version increment', output)

    def test_pre_commit_hooks_synchronize_regular_commit(self) -> None:
        hook_directory = Path(__file__).parents[1] / 'hooks'
        (self.root / '.pre-commit-config.yaml').write_text(
            'repos:\n'
            '  - repo: local\n'
            '    hooks:\n'
            '      - id: check-commit-msg\n'
            '        name: check commit message\n'
            f'        entry: {sys.executable} {hook_directory / "check_commit_msg.py"}\n'
            '        language: system\n'
            '        stages: [commit-msg]\n'
            "        args: ['^\\[feature\\]\\[\\d+\\.\\d+\\.\\d+\\] .+$']\n"
            '      - id: check-version\n'
            '        name: check version\n'
            f'        entry: {sys.executable} {hook_directory / "check_version.py"}\n'
            '        language: system\n'
            '        stages: [commit-msg, post-commit]\n'
            '        args:\n'
            '          - --version-file=version.txt\n'
            f"          - '--version-regex={self.version_regex}'\n"
            '          - --fix-commit-message\n',
            encoding='utf-8',
        )
        subprocess.run(
            ['pre-commit', 'install', '--hook-type', 'commit-msg'],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        subprocess.run(
            ['pre-commit', 'install', '--hook-type', 'post-commit'],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        self.stage_version('1.0.1')

        self.git('commit', '-m', '[feature][1.0.0] title')

        self.assertIn('[feature][1.0.1] title', self.git('log', '-1', '--format=%B'))


if __name__ == '__main__':
    unittest.main()
