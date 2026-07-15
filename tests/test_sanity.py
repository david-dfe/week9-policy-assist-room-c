"""Sanity checks that verify the CI pipeline is wired correctly."""

import monitoring


def test_package_imports() -> None:
    assert monitoring.__version__ == "0.1.0"
