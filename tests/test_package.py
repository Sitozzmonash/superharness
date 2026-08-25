from __future__ import annotations

import pytest

from super_harness import __version__
from super_harness.cli import main


def test_package_version_and_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    captured = capsys.readouterr()

    assert __version__ == "0.0.1.dev0"
    assert captured.out == "super-harness 0.0.1.dev0\n"
