import argparse
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('filenames', nargs='*', help='Filenames to check')
    args = parser.parse_args(argv)

    ret = 0
    for filename in args.filenames:
        try:
            with open(filename, 'rb') as f:
                f.read().decode('utf-8')
        except UnicodeDecodeError:
            print(f'{filename} is not UTF-8 encoded')
            ret = 1
    return ret


if __name__ == '__main__':
    raise SystemExit(main())
