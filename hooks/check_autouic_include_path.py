from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Sequence


C_CPP_FILE_SUFFIXES = {
    '.c', '.cc', '.cp', '.cxx', '.cpp', '.c++',
    '.h', '.hh', '.hp', '.hxx', '.hpp', '.h++',
    '.inl', '.ipp', '.tcc',
}

INCLUDE_PATTERN = re.compile(
    r'^\s*#\s*include\s*"(?P<include>(?:(?P<relative_path>[^"]+)/)?'
    r'ui_(?P<name>[^/"]+)\.h)"')


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Check that ui_*.h includes have matching Qt .ui files.')
    parser.add_argument(
        '--source-root', required=True,
        help='Existing source directory relative to the current working directory.')
    args = parser.parse_args(argv)

    source_root = Path(args.source_root)
    if source_root.is_absolute() or not source_root.is_dir():
        print(
            'Error: --source-root must be an existing directory relative to '
            f'the current working directory: {args.source_root}')
        return 1

    ui_files_by_name: dict[str, list[Path]] = {}
    for ui_file in sorted(source_root.rglob('*.ui')):
        if ui_file.is_file():
            ui_files_by_name.setdefault(ui_file.stem, []).append(ui_file)

    has_error = False
    for source_file in sorted(source_root.rglob('*')):
        if not source_file.is_file() or source_file.suffix.lower() not in C_CPP_FILE_SUFFIXES:
            continue

        with source_file.open(encoding='utf-8', errors='replace') as file:
            for line_number, line in enumerate(file, start=1):
                match = INCLUDE_PATTERN.match(line)
                if match is None:
                    continue

                relative_path = match.group('relative_path')
                ui_file = source_root / f'{match.group("name")}.ui'
                if relative_path:
                    ui_file = source_root / relative_path / f'{match.group("name")}.ui'
                if ui_file.is_file():
                    continue

                include = match.group('include')
                candidates = ui_files_by_name.get(match.group('name'), [])
                if len(candidates) == 1:
                    actual_ui_file = candidates[0]
                    relative_ui_file = actual_ui_file.relative_to(source_root)
                    suggested_include = f'ui_{relative_ui_file.stem}.h'
                    if relative_ui_file.parent != Path('.'):
                        suggested_include = (
                            f'{relative_ui_file.parent.as_posix()}/'
                            f'{suggested_include}')
                    print(
                        f'{source_file}:{line_number}: AUTOUIC include path '
                        f'mismatch for include "{include}"\n'
                        f'  expected UI path: {ui_file}\n'
                        f'  actual UI path: {actual_ui_file}\n'
                        f'  fix: use #include "{suggested_include}".')
                elif not candidates:
                    print(
                        f'{source_file}:{line_number}: UI file does not exist '
                        f'for include "{include}"\n'
                        f'  expected UI path: {ui_file}\n'
                        '  fix: add the expected .ui file or update the include path.')
                else:
                    print(
                        f'{source_file}:{line_number}: AUTOUIC include path is '
                        f'ambiguous for include "{include}"\n'
                        f'  expected UI path: {ui_file}\n'
                        '  candidate UI paths:')
                    for candidate in candidates:
                        print(f'    {candidate}')
                has_error = True

    return 1 if has_error else 0


if __name__ == '__main__':
    raise SystemExit(main())
