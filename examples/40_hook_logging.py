import asyncio

from super_harness import HookContext, HookEvent, HookRegistry

hooks = HookRegistry()


def log_turn(context: HookContext) -> None:
    print(context.event, context.thread_id, context.turn_id)


hooks.register(HookEvent.TURN_END, log_turn)
asyncio.run(hooks.dispatch(HookContext(HookEvent.TURN_END, thread_id="thread-1")))
