from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from super_harness import (
    Agent,
    CompositeSecretProvider,
    ConfigResolver,
    DockerSandbox,
    EnvironmentSecretProvider,
    Event,
    FallbackPolicy,
    FallbackProvider,
    MappingSecretProvider,
    Persona,
    Route,
    Router,
    SandboxMode,
    SQLiteThreadStore,
    ToolRegistry,
    tool,
)
from super_harness.exceptions import ConfigError, ModelError, SandboxError, ToolError, WorkflowError
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class StubProvider:
    capabilities = ModelCapabilities()

    def __init__(
        self,
        name: str,
        *,
        response: str = "ok",
        error: Exception | None = None,
        deltas: tuple[str, ...] = (),
        delay: float = 0,
        model: str = "test-model",
    ) -> None:
        self.name = name
        self.response = response
        self.error = error
        self.deltas = deltas
        self.delay = delay
        self.model = model
        self.calls = 0
        self.closed = False

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return ModelResponse(self.response)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.calls += 1
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        for delta in self.deltas:
            yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta=delta)
        if self.error:
            raise self.error
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(self.response),
        )

    async def aclose(self) -> None:
        self.closed = True


class Collector:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def observe(self, event: object) -> None:
        assert isinstance(event, Event)
        self.events.append(event)


def test_config_precedence_sources_and_diagnostics(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    config_root = project / ".super-harness"
    config_root.mkdir()
    user = tmp_path / "user.toml"
    user.write_text(
        'profile = "global"\n[model]\nmodel = "user-model"\n[sandbox]\nmode = "read_only"',
        encoding="utf-8",
    )
    (config_root / "config.yaml").write_text(
        "model:\n  model: project-model\nsandbox:\n  backend: docker\n",
        encoding="utf-8",
    )
    resolved = ConfigResolver(user_config=user).resolve(
        cwd=project,
        environment={"SUPER_HARNESS_MODEL": "env-model"},
        runtime={"model": {"model": "runtime-model"}},
    )
    assert resolved.config.profile.value == "global"
    assert resolved.config.model.provider == "openai_compatible"
    assert resolved.config.model.model == "runtime-model"
    assert resolved.config.sandbox.backend == "docker"
    assert resolved.config.sandbox.mode == "read_only"
    assert resolved.sources == (user.resolve(), (config_root / "config.yaml").resolve())
    assert resolved.environment_keys == ("SUPER_HARNESS_MODEL",)
    assert "secret" not in json.dumps(resolved.diagnostics()).casefold()


@pytest.mark.parametrize(
    ("profile", "provider", "mode"),
    [
        ("china", "deepseek", "workspace_write"),
        ("global", "openai_compatible", "workspace_write"),
        ("offline", "offline", "read_only"),
        ("test", "test", "workspace_write"),
    ],
)
def test_config_profiles(profile: str, provider: str, mode: str, tmp_path: Path) -> None:
    resolved = ConfigResolver(user_config=tmp_path / "missing").resolve(
        cwd=tmp_path,
        runtime={"profile": profile},
        environment={},
    )
    assert resolved.config.model.provider == provider
    assert resolved.config.sandbox.mode == mode


def test_dotenv_is_opt_in_and_does_not_mutate_process(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text(
        "SUPER_HARNESS_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    resolver = ConfigResolver(user_config=tmp_path / "missing")
    plain = resolver.resolve(cwd=tmp_path, environment={})
    loaded = resolver.resolve(cwd=tmp_path, environment={}, load_dotenv=True)
    assert plain.config.model.model == "deepseek-v4-flash"
    assert loaded.config.model.model == "dotenv-model"
    assert loaded.dotenv == tmp_path / ".env"
    assert os.environ.get("SUPER_HARNESS_MODEL") != "dotenv-model"


def test_config_rejects_unknown_profile(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown"):
        ConfigResolver(user_config=tmp_path / "missing").resolve(
            cwd=tmp_path,
            runtime={"profile": "mystery"},
            environment={},
        )


def test_secret_provider_chain_masks_values() -> None:
    provider = CompositeSecretProvider(
        (EnvironmentSecretProvider({}), MappingSecretProvider({"API_KEY": "secret-value"}))
    )
    secret = provider.get("API_KEY")
    assert secret is not None and secret.reveal() == "secret-value"
    assert str(secret) == "********" and "secret-value" not in repr(secret)


@tool(namespace="safe")
def safe_tool(value: str) -> str:
    return value


@tool(namespace="admin")
def admin_tool(value: str) -> str:
    return value


def test_persona_composes_instructions_scopes_tools_and_metadata(tmp_path: Path) -> None:
    reviewer = Persona("reviewer", "Reviewer", "Find correctness issues")
    persona = Persona(
        "builder",
        "Engineer",
        "Ship a correct change",
        instructions="Use tests.",
        constraints=("Do not expose secrets",),
        model_override="test-model",
        tool_scopes=("safe.*",),
        skill_scopes=("code-*",),
        memory_scope="both",
        subagent_roles={"reviewer": reviewer},
    )
    database = tmp_path / "threads.db"
    with SQLiteThreadStore(database) as store:
        agent = Agent(
            StubProvider("primary"),
            persona=persona,
            instructions="Follow project rules.",
            tools=(safe_tool, admin_tool),
            store=store,
        )
        thread = agent.thread()
        assert [item.qualified_name for item in agent.tool_registry.list()] == ["safe.safe_tool"]
        assert "Role: Engineer" in (agent.instructions or "")
        assert "Application instructions" in (agent.instructions or "")
        assert thread.metadata["persona"] == "builder"
        assert store.load(thread.thread_id).metadata["memory_scope"] == "both"
        assert persona.subagent("reviewer") is reviewer


def test_persona_rejects_model_mismatch() -> None:
    persona = Persona("builder", "Engineer", "Build", model_override="other-model")
    with pytest.raises(ValueError, match="requires model"):
        Agent(StubProvider("primary"), persona=persona)


def test_persona_scope_applies_to_later_tool_registration() -> None:
    persona = Persona("Scoped", "worker", "Stay scoped", tool_scopes=("safe.*",))
    agent = Agent(StubProvider("primary"), persona=persona)
    with pytest.raises(ToolError, match="outside"):
        agent.tool_registry.register(admin_tool)
    with pytest.raises(ToolError, match="outside"):
        agent.tool_registry.register_lazy("later", "Deferred", lambda: safe_tool)


def test_lazy_tool_loads_only_on_explicit_search() -> None:
    calls = 0

    def loader() -> object:
        nonlocal calls
        calls += 1
        return safe_tool

    registry = ToolRegistry()
    metadata = registry.register_lazy(
        "safe_tool",
        "Safe deferred tool",
        loader,
        namespace="safe",
        source="plugin:demo",
    )
    assert metadata.qualified_name == "safe.safe_tool"
    assert registry.definitions() == ()
    assert registry.discover("deferred")[0][3] is True
    assert calls == 0 and registry.search("safe") == ()
    assert registry.search("safe", load_deferred=True) == (safe_tool,)
    assert calls == 1 and registry.load("safe.safe_tool") is safe_tool
    assert registry.definitions()[0].name == "safe.safe_tool"


def test_lazy_tool_failure_is_retryable_and_mismatch_rejected() -> None:
    registry = ToolRegistry()
    registry.register_lazy("wrong", "Wrong", lambda: safe_tool)
    with pytest.raises(ToolError, match="mismatched"):
        registry.load("wrong")
    assert registry.deferred()[0].name == "wrong"


@pytest.mark.asyncio
async def test_router_priority_async_default_and_observation() -> None:
    collector = Collector()

    async def urgent(value: dict[str, Any], context: Mapping[str, Any]) -> bool:
        await asyncio.sleep(0)
        return value.get("severity") == "urgent" and context.get("enabled") is True

    router: Router[dict[str, Any]] = Router(
        (
            Route[dict[str, Any]]("ordinary", "queue", lambda value, context: True, priority=20),
            Route[dict[str, Any]](
                "urgent", "pager", urgent, priority=10, metadata={"team": "oncall"}
            ),
        ),
        default="dead-letter",
        observer=collector,
    )
    decision = await router.aroute({"severity": "urgent"}, context={"enabled": True})
    assert decision.route == "urgent" and decision.target == "pager"
    assert collector.events[-1].type == "route.selected"
    default: Router[str] = Router(
        (Route[str]("never", "x", lambda value, context: False),), default="other"
    )
    assert (await default.aroute("value")).target == "other"


def test_router_sync_and_no_match_error() -> None:
    router: Router[int] = Router(
        (Route[int]("positive", "accept", lambda value, context: value > 0),)
    )
    assert router.route(1).target == "accept"
    with pytest.raises(WorkflowError, match="no matching"):
        router.route(-1)


@pytest.mark.asyncio
async def test_fallback_complete_is_observable_and_ordered() -> None:
    collector = Collector()
    primary = StubProvider("primary", error=ModelError("unavailable"))
    backup = StubProvider("backup", response="backup answer")
    provider = FallbackProvider((primary, backup), observer=collector)
    response = await provider.complete(ModelRequest(()))
    assert response.text == "backup answer"
    assert primary.calls == backup.calls == 1
    assert [item.type for item in collector.events] == [
        "provider.attempt.started",
        "provider.attempt.failed",
        "provider.fallback.selected",
        "provider.attempt.started",
        "provider.attempt.completed",
    ]
    await provider.aclose()
    assert primary.closed and backup.closed


@pytest.mark.asyncio
async def test_fallback_stream_before_output_and_never_after_visible_output() -> None:
    primary = StubProvider("primary", error=ModelError("early"))
    backup = StubProvider("backup", response="done", deltas=("safe",))
    provider = FallbackProvider((primary, backup))
    events = [item async for item in provider.stream(ModelRequest(()))]
    assert [item.type for item in events] == [
        ModelStreamEventType.STARTED,
        ModelStreamEventType.TEXT_DELTA,
        ModelStreamEventType.COMPLETED,
    ]
    partial = StubProvider("partial", error=ModelError("late"), deltas=("visible",))
    unused = StubProvider("unused")
    unsafe = FallbackProvider((partial, unused))
    with pytest.raises(ModelError, match="visible output"):
        async for _ in unsafe.stream(ModelRequest(())):
            pass
    assert unused.calls == 0


@pytest.mark.asyncio
async def test_fallback_timeout_and_cancellation_are_distinct() -> None:
    slow = StubProvider("slow", delay=1)
    backup = StubProvider("backup", response="fast")
    provider = FallbackProvider((slow, backup), policy=FallbackPolicy(timeout=0.01))
    assert (await provider.complete(ModelRequest(()))).text == "fast"

    task = asyncio.create_task(
        FallbackProvider((StubProvider("cancel", delay=10), backup)).complete(ModelRequest(()))
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_fallback_does_not_hide_unexpected_provider_bug() -> None:
    broken = StubProvider("broken", error=ValueError("programming bug"))
    backup = StubProvider("backup", response="must not be used")
    with pytest.raises(ModelError, match="attempt failed"):
        await FallbackProvider((broken, backup)).complete(ModelRequest(()))
    assert backup.calls == 0


def test_docker_command_has_secure_defaults_and_no_secret_argv(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerSandbox(
        workspace,
        "python:3.12-alpine",
        mode=SandboxMode.READ_ONLY,
        environment_allowlist=("TOKEN",),
    )
    command, environment = sandbox.build_command(
        ("python", "-c", "print('ok')"),
        env={"TOKEN": "sk-abcdefghijklmnop"},
        container_name="test-container",
    )
    joined = " ".join(command)
    assert "--network none" in joined
    assert "--read-only" in command and "--cap-drop" in command
    assert "readonly" not in joined or "dst=/workspace,ro" in joined
    assert "sk-abcdefghijklmnop" not in joined
    assert environment["TOKEN"] == "sk-abcdefghijklmnop"
    assert sandbox.describe()["read_only_root"] is True


def test_docker_rejects_path_escape_env_and_unsafe_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sandbox = DockerSandbox(workspace, "alpine:3.20")
    with pytest.raises(SandboxError, match="cwd escapes"):
        sandbox.build_command(("true",), cwd=tmp_path)
    with pytest.raises(SandboxError, match="allowlisted"):
        sandbox.build_command(("true",), env={"SECRET": "value"})
    with pytest.raises(SandboxError, match="mount target"):
        DockerSandbox(workspace, "alpine:3.20", read_only_mounts={workspace: "../escape"})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_docker_real_isolation_when_local_image_available(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is not installed")
    image = "alpine:3.20"
    inspected = subprocess.run(
        [docker, "image", "inspect", image],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if inspected.returncode != 0:
        pytest.skip("local alpine:3.20 image is not available; tests never pull implicitly")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = await DockerSandbox(workspace, image, timeout=15).run_exec(
        ("sh", "-c", "test ! -e /proc/1/root/host && printf isolated")
    )
    assert result.exit_code == 0 and result.stdout == "isolated"
