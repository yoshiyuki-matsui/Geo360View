"""Compatibility wrapper for the TenkakuNinja standalone Exporter CLI."""

from TenkakuNinja.main import main


if __name__ == "__main__":
    raise SystemExit(main())
