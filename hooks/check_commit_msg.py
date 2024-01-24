#!/usr/bin/env python3

import sys
import re



def main(argv: list[str] = sys.argv) -> int:
    regex=argv[1]
    filepath = argv[2]

    with open(filepath, 'r') as f:
        content = f.read()

    matches = re.match(regex, content, re.MULTILINE)
    if not matches:
        print('提交信息不符合提交规范')
        return -1

    return 0

if __name__ == '__main__':
    raise SystemExit(main())
