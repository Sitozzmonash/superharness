# User Guide Structure

This is strictly the **usage manual**. Keep internal architecture in the Internals section.

## Part I — Start

1. What is Super Harness?
2. Installation
3. Five-minute Quick Start
4. Project layout
5. Configuration and `.env`
6. First Agent
7. Sync vs Async

## Part II — Models and Inputs

8. Main text model
9. DeepSeek V4 Flash setup
10. Custom/OpenAI-compatible provider
11. Vision setup
12. GLM-4V-Flash usage
13. Model capability/fallback configuration
14. Structured output

## Part III — Sessions

15. Thread basics
16. Multi-turn
17. Resume
18. Fork
19. Archive/inspect
20. Streaming
21. Interrupt
22. Steer
23. Cancel
24. Compaction

## Part IV — Knowledge

25. Working memory
26. Long-term memory
27. External RAG
28. Connecting an HTTP RAG service
29. Mock RAG server tutorial
30. RAG sources/metadata
31. Web Search
32. Zhipu Web Search
33. Vision + RAG/Search combinations

## Part V — Execution

34. Function tools
35. Async tools
36. Dynamic tools
37. Built-in tools
38. Shell/file/python tools
39. Sandbox
40. Approval/permissions
41. Tool errors/timeouts

## Part VI — Instructions and Extensions

42. Persona and role
43. AGENTS.md
44. Nested AGENTS.md
45. Skills overview
46. Install skill from GitHub
47. Project/global skills
48. Write a skill
49. MCP overview
50. stdio MCP
51. Streamable HTTP MCP
52. Import existing `mcpServers` config
53. MCP 2026 compatibility notes (stateless/MRTR/headers)
54. Install MCP Bundle (`.mcpb`)
55. MCP Registry discovery (when enabled)
56. Plugins
57. Install plugin
58. Write plugin
59. Hooks
60. Hook examples

## Part VII — Multi-Agent

61. Autonomous multi-agent
62. Spawn/send/wait/resume/close
63. Subagent context
64. Subagent limits/budgets
65. Sequential workflow
66. Parallel workflow
67. Conditional workflow
68. Router
69. Retry and loop
70. DAG
71. Hybrid orchestration
72. Workflow resume

## Part VIII — Operations

73. Persistence
74. Observability
75. Logs
76. Tracing
77. Token/cost metrics
78. CLI
79. `doctor`
80. Testing providers
81. Deployment
82. Docker deployment
83. China-ready deployment
84. Offline/custom-provider deployment
85. Security best practices
86. Performance/cost tuning
87. Troubleshooting

## Mandatory examples per feature

Each major feature page must point to at least:
- Basic
- Real-world
- Advanced/combined

Multi-agent/workflow/skills/MCP/plugins should exceed three where useful.
