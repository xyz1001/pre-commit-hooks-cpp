#!/usr/bin/env python3

import sys
import re
from pathlib import Path
from charset_normalizer import from_path

def main(argv: list[str] = sys.argv) -> int:
    regex=argv[1]
    filepath = argv[2]

    result = from_path(Path(filepath)).best()
    if result.encoding not in ('utf_8', 'ascii') or result.bom:
        print(f'The text codec of commit message should be UTF-8 without BOM, current text codec is {result.encoding}')

    with open(filepath, 'r',  encoding='utf-8') as f:
        content = f.read()

    matches = re.match(regex, content, re.MULTILINE)
    if not matches:
        print(f'The commit message is not match the check rule\n{content}')
        return -1

    return 0

if __name__ == '__main__':
    raise SystemExit(main())
