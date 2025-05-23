#!/usr/bin/env python3

from __future__ import annotations

import argparse
from charset_normalizer import from_path
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', help='Filenames to check')
    args = parser.parse_args(argv)

    for filename in args.filenames:
        # 使用charset_normalizer读取文件内容，它能自动处理不同的编码
        raw = from_path(filename).best()
        if not raw:
            print(f"warning: unable to read file {filename}")
            return 0

        content = str(raw)
        # 查找Windows风格换行符(\r\n)
        if '\r\n' in content:
            print(
                f"Error: file {filename} contains Windows linebreak(CRLF)")
            return -1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
