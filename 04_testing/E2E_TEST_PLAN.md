# End-to-End Test Plan

## Suite A — Basic Agent

A1 install package in clean venv  
A2 create DeepSeek-backed Agent  
A3 run prompt  
A4 verify Thread/Turn persisted  
A5 resume thread

## Suite B — Tool Loop

B1 register calculator function  
B2 prompt model requiring calculation  
B3 observe model tool call  
B4 execute tool  
B5 feed result  
B6 verify final answer and trace

Repeat for async tool.

## Suite C — Streaming and interruption

C1 start long streamed turn  
C2 collect model delta events  
C3 steer with new instruction  
C4 verify updated behavior  
C5 interrupt another run  
C6 confirm terminal state and no orphan task

## Suite D — Web Search

D1 agent asked for current public fact  
D2 model selects web search  
D3 actual Zhipu endpoint called  
D4 results normalized  
D5 source metadata visible  
D6 final answer grounded

## Suite E — Vision

E1 load deterministic fixture image with known visible objects/text  
E2 actual `glm-4v-flash` call  
E3 verify expected key concepts  
E4 combine vision result with main DeepSeek reasoning

## Suite F — RAG

F1 start local HTTP mock RAG service  
F2 seed known corpus  
F3 Agent asks question not answerable from default context  
F4 RAG provider calls HTTP  
F5 top-N returns known evidence  
F6 evidence injected  
F7 DeepSeek answers correctly  
F8 trace links retrieval to final turn

## Suite G — AGENTS.md

G1 root instructions  
G2 nested instructions  
G3 override  
G4 conflict precedence  
G5 byte/token limit  
G6 scoped behavior

## Suite H — Skills

H1 install a local standard skill  
H2 install pinned GitHub skill  
H3 discover metadata without loading full body  
H4 activate when relevant  
H5 execute referenced script under sandbox  
H6 remove/update

## Suite I — MCP

I1 start real stdio MCP fixture  
I2 discover tool  
I3 model invokes MCP tool  
I4 result returned  
I5 timeout/reconnect  
I6 HTTP MCP fixture

## Suite J — Plugin

J1 install plugin  
J2 plugin contributes skill/tool/hook  
J3 verify lifecycle  
J4 disable plugin  
J5 remove plugin

## Suite K — Autonomous Multi-Agent

K1 main agent given multi-part task  
K2 spawn 3 children  
K3 execute concurrently  
K4 selective wait  
K5 aggregate  
K6 final response  
K7 inspect parent/child trace tree

## Suite L — Workflow

L1 sequence  
L2 parallel  
L3 condition  
L4 router  
L5 retry  
L6 loop  
L7 resume from checkpoint

## Suite M — Hybrid

M1 workflow enters autonomous node  
M2 autonomous node spawns children  
M3 returns structured result  
M4 workflow continues  
M5 cancellation propagates

## Suite N — Full application demo

Build one end-to-end research/development agent using:
- DeepSeek
- Zhipu search
- Vision
- RAG
- AGENTS.md
- Skill
- MCP
- Plugin
- sandbox
- memory
- autonomous subagents
- workflow
- streaming
- persistence
- observability

The example must live under `examples/full_application/` and be documented on the website.
