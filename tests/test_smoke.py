"""Checks that the package imports, so CI has something to run before the first feature."""

import soc


def test_package_imports() -> None:
    assert soc.__doc__
