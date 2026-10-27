import pytest

from app import telemetry


@pytest.fixture(autouse=True)
def _reset_telemetry():
    telemetry.telemetry.reset()
    yield
    telemetry.telemetry.reset()
