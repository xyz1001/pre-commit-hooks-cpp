#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence


COMMIT_VERSION_PATTERN = re.compile(r'\[(\d+(?:\.\d+)+)\]')


def extract_version_from_commit_msg(text: str) -> str | None:
    """从 commit message 中提取 [x.y.z] 形式的版本号"""
    match = COMMIT_VERSION_PATTERN.search(text)
    return match.group(1) if match else None


def git_run(*cmd: str) -> str | None:
    try:
        result = subprocess.run(
            ['git', *cmd],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def extract_version_from_file(filepath: str, pattern: str) -> str | None:
    """用正则从文件中提取版本号。

    单个捕获组 → 直接作为版本号；
    多个捕获组 → 各组用 '.' 连接组成版本号。
    """
    content = git_run('show', f"HEAD:{filepath}")
    if content is None:
        return None
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        return None
    groups = [g for g in match.groups() if g is not None]
    if not groups:
        return None
    return '.'.join(groups)


def get_previous_commit_version() -> str | None:
    msg = git_run('log', '-1', '--format=%B', 'HEAD~1')
    if not msg:
        return None
    return extract_version_from_commit_msg(msg)


def parse_version(version_str: str) -> list[int]:
    return [int(x) for x in version_str.split('.')]


def validate_version_increment(prev: str, curr: str) -> str | None:
    """检查版本号递增是否合法。合法返回 None，不合法返回错误信息。

    规则：有且仅有一位增加了 1，该位之后的所有低位必须置为 0。
    """
    prev_parts = parse_version(prev)
    curr_parts = parse_version(curr)

    if len(prev_parts) != len(curr_parts):
        return (
            f"Version segment count changed: "
            f"{prev} ({len(prev_parts)} segments) -> {curr} ({len(curr_parts)} segments)"
        )

    incremented_index = -1
    for i in range(len(prev_parts)):
        diff = curr_parts[i] - prev_parts[i]

        if diff == 0:
            continue

        if diff == 1 and incremented_index == -1:
            incremented_index = i
            continue

        if incremented_index != -1 and curr_parts[i] == 0:
            continue

        if diff < 0 and incremented_index != -1:
            return (
                f"Version segment {i} should be 0 after incrementing segment {incremented_index}: "
                f"{prev} -> {curr}"
            )

        if diff > 1:
            return (
                f"Version segment {i} increased by {diff} (must be exactly 1): "
                f"{prev} -> {curr}"
            )

        if diff == 1 and incremented_index != -1:
            return (
                f"Multiple segments incremented (segment {incremented_index} and {i}): "
                f"{prev} -> {curr}"
            )

        if diff < 0:
            return (
                f"Version segment {i} decreased without a higher segment increment: "
                f"{prev} -> {curr}"
            )

    if incremented_index == -1:
        return f"Version not incremented: {prev} -> {curr}"

    for i in range(incremented_index + 1, len(curr_parts)):
        if curr_parts[i] != 0:
            return (
                f"Version segment {i} should be 0 after incrementing segment {incremented_index}: "
                f"{prev} -> {curr}"
            )

    return None


def _fatal(error_detail: str, remediation_hint: str = '') -> int:
    """Print a prominent, non-ignorable error banner and return exit-code 1.

    Because this hook runs at the *post-commit* stage, the commit has
    already been created by the time an error is detected.  The error
    output is deliberately verbose and strongly-worded so that both
    human developers and AI coding assistants understand that:

    1. The commit **MUST** be reverted with ``git reset HEAD~1``.
    2. The underlying issue **MUST** be fixed.
    3. A new, corrected commit **MUST** be created.

    Ignoring this error and continuing is **NOT** acceptable.
    """
    separator = '!' * 72
    extra = f"\n  Hint: {remediation_hint}" if remediation_hint else ''
    print(
        f"\n{separator}\n"
        f"!!  FATAL: VERSION CHECK FAILED — COMMIT MUST BE REVERTED\n"
        f"{separator}\n"
        f"\n"
        f"  {error_detail}\n"
        f"{extra}\n"
        f"  This hook runs at the post-commit stage, so the commit has already\n"
        f"  been created. However, this error MUST NOT be ignored.\n"
        f"\n"
        f"  >>> REQUIRED ACTION (mandatory — do NOT skip) <<<\n"
        f"\n"
        f"  1. Revert the commit:  git reset HEAD~1\n"
        f"  2. Fix the version number in both the commit message and the\n"
        f"     version file so that they are consistent and correctly\n"
        f"     incremented.\n"
        f"  3. Create a new commit with the corrected version.\n"
        f"\n"
        f"  AI agents / LLM tools: you MUST execute 'git reset HEAD~1' now\n"
        f"  and fix the version before re-committing. Do NOT proceed with\n"
        f"  any other work until this is resolved. Treating this as a\n"
        f"  non-blocking warning is INCORRECT — this is a hard error.\n"
        f"\n"
        f"{separator}\n",
        file=sys.stderr,
    )
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Check version consistency between commit message and version file'
    )
    parser.add_argument(
        '--version-file',
        required=True,
        help='path to the version file (e.g. conanfile.py, version.properties)',
    )
    parser.add_argument(
        '--version-regex',
        required=True,
        help=(
            'regex to extract version from the version file; '
            'single capture group = version string, '
            "multiple capture groups = joined by '.'"
        ),
    )
    args = parser.parse_args(argv)

    commit_msg = git_run('log', '-1', '--format=%B', 'HEAD')
    if not commit_msg:
        return 0

    if commit_msg.lstrip().lower().startswith('fixup!'):
        return 0

    commit_version = extract_version_from_commit_msg(commit_msg)
    if not commit_version:
        return _fatal(
            'No version found in commit message (expected [x.y.z] format).',
            'Include a version tag like [1.2.3] in your commit message.',
        )

    file_version = extract_version_from_file(args.version_file, args.version_regex)
    if not file_version:
        return _fatal(
            f"No version matched in {args.version_file} "
            f"with regex: {args.version_regex}",
            f"Ensure {args.version_file} contains a version that matches "
            f"the expected pattern.",
        )

    if commit_version != file_version:
        return _fatal(
            f"Version mismatch between commit message and {args.version_file}:\n"
            f"    commit message : {commit_version}\n"
            f"    {args.version_file} : {file_version}",
            'Make the version in the commit message and the version file identical.',
        )

    prev_version = get_previous_commit_version()
    if prev_version is not None:
        error = validate_version_increment(prev_version, commit_version)
        if error:
            return _fatal(
                f"Invalid version increment:\n"
                f"    previous : {prev_version}\n"
                f"    current  : {commit_version}\n"
                f"    reason   : {error}",
                'Increment exactly one version segment by 1 and reset all '
                'lower segments to 0.',
            )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
