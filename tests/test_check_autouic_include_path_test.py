"""Tests for the AutoUIC include-path hook."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from hooks.check_autouic_include_path import main


class CheckAutouicIncludePathTests(unittest.TestCase):
    def run_hook(self, source_root: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(['--source-root', source_root])
        return result, output.getvalue()

    def test_accepts_matching_nested_ui_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'src' / 'forms').mkdir(parents=True)
            (root / 'src' / 'forms' / 'settings.ui').touch()
            (root / 'src' / 'main.cpp').write_text(
                '#include "forms/ui_settings.h"\n', encoding='utf-8')

            previous_directory = Path.cwd()
            os.chdir(root)
            try:
                result, output = self.run_hook('src')
            finally:
                os.chdir(previous_directory)

            self.assertEqual(0, result)
            self.assertEqual('', output)

    def test_reports_ui_file_does_not_exist_for_bare_include(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'src').mkdir()
            (root / 'src' / 'widget.hpp').write_text(
                '#include "ui_missing.h"\n', encoding='utf-8')

            previous_directory = Path.cwd()
            os.chdir(root)
            try:
                result, output = self.run_hook('src')
            finally:
                os.chdir(previous_directory)

            self.assertEqual(1, result)
            self.assertIn('src/widget.hpp:1', output)
            self.assertIn('UI file does not exist', output)
            self.assertIn('include "ui_missing.h"', output)
            self.assertIn('expected UI path: src/missing.ui', output)
            self.assertIn('fix:', output)

    def test_reports_unique_ui_file_with_complete_include_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'src' / 'forms').mkdir(parents=True)
            (root / 'src' / 'forms' / 'settings.ui').touch()
            (root / 'src' / 'widget.cpp').write_text(
                '#include "wrong/ui_settings.h"\n', encoding='utf-8')

            previous_directory = Path.cwd()
            os.chdir(root)
            try:
                result, output = self.run_hook('src')
            finally:
                os.chdir(previous_directory)

            self.assertEqual(1, result)
            self.assertIn('AUTOUIC include path mismatch', output)
            self.assertIn('actual UI path: src/forms/settings.ui', output)
            self.assertIn('#include "forms/ui_settings.h"', output)
            self.assertNotIn('UI file does not exist', output)

    def test_reports_ambiguous_ui_file_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'src' / 'forms').mkdir(parents=True)
            (root / 'src' / 'dialogs').mkdir()
            (root / 'src' / 'forms' / 'settings.ui').touch()
            (root / 'src' / 'dialogs' / 'settings.ui').touch()
            (root / 'src' / 'widget.cpp').write_text(
                '#include "wrong/ui_settings.h"\n', encoding='utf-8')

            previous_directory = Path.cwd()
            os.chdir(root)
            try:
                result, output = self.run_hook('src')
            finally:
                os.chdir(previous_directory)

            self.assertEqual(1, result)
            self.assertIn('AUTOUIC include path is ambiguous', output)
            self.assertIn('src/dialogs/settings.ui', output)
            self.assertIn('src/forms/settings.ui', output)

    def test_ignores_angle_bracket_and_non_ui_includes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / 'src').mkdir()
            (root / 'src' / 'main.cc').write_text(
                '#include <forms/ui_missing.h>\n'
                '#include "forms/regular.h"\n', encoding='utf-8')

            previous_directory = Path.cwd()
            os.chdir(root)
            try:
                result, output = self.run_hook('src')
            finally:
                os.chdir(previous_directory)

            self.assertEqual(0, result)
            self.assertEqual('', output)

    def test_rejects_invalid_source_root(self) -> None:
        result, output = self.run_hook('does-not-exist')

        self.assertEqual(1, result)
        self.assertIn('--source-root must be an existing directory', output)


if __name__ == '__main__':
    unittest.main()
