"""Route requests by deterministic priority."""

from super_harness import Route, Router

router = Router(
    (
        Route("ordinary", "queue", lambda value, context: True, priority=20),
        Route("urgent", "pager", lambda value, context: value == "urgent", priority=10),
    )
)
print(router.route("urgent"))

