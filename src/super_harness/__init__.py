"""Public package surface for Super Harness."""

from super_harness.agent import Agent
from super_harness.config import HarnessConfig, ProfileName, SecretValue
from super_harness.context import (
    AgentsMdLoader,
    ContextAssembler,
    ContextDebugSnapshot,
    ContextFragment,
    ContextKind,
    ContextSummary,
)
from super_harness.exceptions import SuperHarnessError
from super_harness.knowledge import (
    HTTPRAGProvider,
    KnowledgeRouter,
    KnowledgeTrace,
    RAGDocument,
    SearchResponse,
    SearchResult,
    VisionResult,
    ZhipuVisionProvider,
    ZhipuWebSearchProvider,
)
from super_harness.mcp import (
    MCPBundle,
    MCPClient,
    MCPRegistry,
    MCPServerConfig,
    MCPTransport,
    OfficialMCPRegistry,
    import_mcp_servers,
    inspect_mcpb,
    install_mcpb,
)
from super_harness.memory import (
    HeuristicMemoryExtractor,
    MemoryCandidate,
    MemoryKind,
    MemoryManager,
    MemoryMatch,
    MemoryRecord,
    MemoryTrace,
    SQLiteMemoryStore,
    WorkingMemory,
)
from super_harness.models import DeepSeekProvider, OpenAICompatibleProvider
from super_harness.persistence import SQLiteThreadStore
from super_harness.runtime.events import Event
from super_harness.runtime.handle import TurnHandle
from super_harness.runtime.thread import Thread
from super_harness.runtime.turn import Turn, TurnStatus
from super_harness.skills import (
    ActivatedSkill,
    SkillCatalog,
    SkillInstaller,
    SkillMetadata,
    SkillSource,
    activate_skill,
    parse_skill,
)
from super_harness.tools import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    LocalSandbox,
    SandboxMode,
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    basic_builtin_tools,
    tool,
)

__all__ = [
    "ActivatedSkill",
    "Agent",
    "AgentsMdLoader",
    "ApprovalDecision",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ContextAssembler",
    "ContextDebugSnapshot",
    "ContextFragment",
    "ContextKind",
    "ContextSummary",
    "DeepSeekProvider",
    "Event",
    "HTTPRAGProvider",
    "HarnessConfig",
    "HeuristicMemoryExtractor",
    "KnowledgeRouter",
    "KnowledgeTrace",
    "LocalSandbox",
    "MCPBundle",
    "MCPClient",
    "MCPRegistry",
    "MCPServerConfig",
    "MCPTransport",
    "MemoryCandidate",
    "MemoryKind",
    "MemoryManager",
    "MemoryMatch",
    "MemoryRecord",
    "MemoryTrace",
    "OfficialMCPRegistry",
    "OpenAICompatibleProvider",
    "ProfileName",
    "RAGDocument",
    "SQLiteMemoryStore",
    "SQLiteThreadStore",
    "SandboxMode",
    "SearchResponse",
    "SearchResult",
    "SecretValue",
    "SkillCatalog",
    "SkillInstaller",
    "SkillMetadata",
    "SkillSource",
    "SuperHarnessError",
    "Thread",
    "Tool",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "Turn",
    "TurnHandle",
    "TurnStatus",
    "VisionResult",
    "WorkingMemory",
    "ZhipuVisionProvider",
    "ZhipuWebSearchProvider",
    "activate_skill",
    "basic_builtin_tools",
    "import_mcp_servers",
    "inspect_mcpb",
    "install_mcpb",
    "parse_skill",
    "tool",
]

__version__ = "0.0.1.dev0"
