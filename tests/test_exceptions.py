from __future__ import annotations

import pytest

from super_harness.exceptions import SuperHarnessError


def test_error_preserves_read_only_diagnostics() -> None:
    details = {"provider": "example"}
    error = SuperHarnessError("failed", correlation_id="trace-1", details=details)

    details["provider"] = "mutated"

    assert str(error) == "failed"
    assert error.correlation_id == "trace-1"
    assert error.details == {"provider": "example"}
    with pytest.raises(TypeError):
        error.details["provider"] = "changed"  # type: ignore[index]
