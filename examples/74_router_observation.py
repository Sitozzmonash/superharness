"""Observe a routing decision without exposing routed content."""

from super_harness import Event, Route, Router


class Observer:
    def observe(self, event: object) -> None:
        if isinstance(event, Event):
            print(event.type, dict(event.payload))


Router((Route("safe", "worker", lambda value, context: value >= 0),), observer=Observer()).route(1)

