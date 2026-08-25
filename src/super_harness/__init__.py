"""Public package surface for Super Harness."""

from super_harness.agent import Agent
from super_harness.config import HarnessConfig, ProfileName, SecretValue
from super_harness.exceptions import SuperHarnessError
from super_harness.models import DeepSeekProvider, OpenAICompatibleProvider
from super_harness.runtime.events import Event
from super_harness.runtime.thread import Thread
from super_harness.runtime.turn import Turn, TurnStatus

__all__ = [
    "Agent",
    "DeepSeekProvider",
    "Event",
    "HarnessConfig",
    "OpenAICompatibleProvider",
    "ProfileName",
    "SecretValue",
    "SuperHarnessError",
    "Thread",
    "Turn",
    "TurnStatus",
]

__version__ = "0.0.1.dev0"
