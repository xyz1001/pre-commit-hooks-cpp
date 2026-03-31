#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


COMMIT_VERSION_PATTERN = re.compile(r"\[(\d+(?:\.\d+)+)\]")


def extract_version_from_commit_msg(text: str) -> str | None:
    """从 commit message 中提取 [x.y.z] 形式的版本号"""
    match = COMMIT_VERSION_PATTERN.search(text)
    return match.group(1) if match else None


def extract_version_from_file(filepath: Path, pattern: str) -> str | None:
    """用正则从文件中提取版本号。

    单个捕获组 → 直接作为版本号；
    多个捕获组 → 各组用 '.' 连接组成版本号。
    """
    content = filepath.read_text(encoding="utf-8")
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        return None
    groups = [g for g in match.groups() if g is not None]
    if not groups:
        return None
    return ".".join(groups)


def get_previous_commit_version() -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%B", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return extract_version_from_commit_msg(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def parse_version(version_str: str) -> list[int]:
    return [int(x) for x in version_str.split(".")]


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check version consistency between commit message and version file"
    )
    parser.add_argument(
        "--version-file",
        required=True,
        help="path to the version file (e.g. conanfile.py, version.properties)",
    )
    parser.add_argument(
        "--version-regex",
        required=True,
        help=(
            "regex to extract version from the version file; "
            "single capture group = version string, "
            "multiple capture groups = joined by '.'"
        ),
    )
    parser.add_argument(
        "commit_msg_file",
        help="path to the commit message file (passed by pre-commit)",
    )
    args = parser.parse_args(argv)

    commit_msg_file = Path(args.commit_msg_file)
    if not commit_msg_file.exists():
        print(f"Error: commit message file not found: {commit_msg_file}")
        return 1

    commit_msg = commit_msg_file.read_text(encoding="utf-8")

    if commit_msg.lstrip().lower().startswith("fixup!"):
        return 0

    commit_version = extract_version_from_commit_msg(commit_msg)
    if not commit_version:
        print("Error: no version found in commit message (expected [x.y.z] format)")
        return 1

    version_file = Path(args.version_file)
    if not version_file.exists():
        print(f"Error: version file not found: {version_file}")
        return 1

    file_version = extract_version_from_file(version_file, args.version_regex)
    if not file_version:
        print(
            f"Error: no version matched in {version_file} "
            f"with regex: {args.version_regex}"
        )
        return 1

    if commit_version != file_version:
        print(
            f"Error: version mismatch between commit message and {version_file}\n"
            f"  commit message: {commit_version}\n"
            f"  {version_file}: {file_version}"
        )
        return 1

    prev_version = get_previous_commit_version()
    if prev_version is not None:
        error = validate_version_increment(prev_version, commit_version)
        if error:
            print(
                f"Error: invalid version increment\n"
                f"  previous: {prev_version}\n"
                f"  current:  {commit_version}\n"
                f"  reason:   {error}"
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
