import asyncio
from types import SimpleNamespace

from super_harness import HookContext, HookEvent, HookRegistry, HookResult

hooks = HookRegistry()


def protect_delete(context: HookContext) -> HookResult | None:
    tool = context.data["tool"]
    if tool.name == "delete_all":
        return HookResult.deny("destructive tool blocked by application policy")
    return None


hooks.register(HookEvent.PRE_TOOL_USE, protect_delete)
outcome = asyncio.run(
    hooks.dispatch(HookContext(HookEvent.PRE_TOOL_USE, {"tool": SimpleNamespace(name="read")}))
)
print(outcome.denied, outcome.deny_reason)
