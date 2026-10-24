"""Command line:  python -m io_sudoku <command>   (see `python -m io_sudoku --help`)."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from io_sudoku.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
