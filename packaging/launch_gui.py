"""The frozen build's entry point: one import and one call, so the
bundle's behaviour stays the library's behaviour."""

from pyargus.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
