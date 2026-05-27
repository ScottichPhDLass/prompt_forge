import sys

from .cli import main as _cli_main


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] in ("--ui", "ui"):
        from .ui_server import main as _ui_main
        return _ui_main(args[1:])
    return _cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
