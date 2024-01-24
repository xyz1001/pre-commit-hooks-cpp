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
        print('提交信息字符编码应使用UTF-8 without BOM，当前为 %s' % result.encoding)

    with open(filepath, 'r',  encoding='utf-8') as f:
        content = f.read()

    matches = re.match(regex, content, re.MULTILINE)
    if not matches:
        print('提交信息不符合提交规范')
        return -1

    return 0

if __name__ == '__main__':
    raise SystemExit(main())
