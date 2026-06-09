# AI Werewolf Agent Architecture Comparison

> Date: 2026-06-08
> Scope: current `CognitiveAgent` / `AgentLoop` / `WerewolfGame` engineering design compared with Claude Code-style agentic coding and mainstream open-source agent frameworks.

## Executive Conclusion

The current Agent design is reasonable and mostly accurate for a domain-specific, adversarial multi-agent game system. It should not be judged as a general-purpose autonomous coding agent. Its strongest design choice is that autonomy is bounded: each player Agent reasons, retrieves, and proposes a `Decision`, while `WerewolfGame` remains the only authority that mutates game state, validates legality, resolves phases, and records evidence.

Overall assessment: **8/10 for the current project stage**.

It already satisfies the core expectations of an engineered Agent system:

- explicit lifecycle protocol;
- isolated per-player observation surface;
- tool-calling decision loop;
- role/persona/memory/retrieval separation;
- structured `Decision` output;
- engine-side validation and audit trail;
- LLM-only runtime policy with test-only fake provider.

The main gaps are not conceptual. They are production engineering concerns: process-global trace caches, limited durable checkpointing, hardcoded tool budgets, mixed fallback semantics, and role/action extensibility still being coupled to Python protocol methods.

## Current Architecture Evidence

Current path:

```text
GameState
  -> Visibility.for_player()
  -> PlayerView
  -> CognitiveAgent.update()
  -> Observation / Memory / BeliefTracker / SocialModel / Planner
  -> AgentLoop(tools + LLM)
  -> Decision
  -> WerewolfGame validation / settlement / DecisionAudit
```

Evidence in code:

| Area | Evidence | Meaning |
|---|---|---|
| Agent protocol | `backend/agents/base.py:9` | AIWolf-style lifecycle: initialize, update, talk, vote, attack, divine, guard, finish, etc. |
| Action contract | `backend/engine/models.py:126` | `Decision` is a typed intent object, not arbitrary text. |
| Decision audit | `backend/engine/models.py:137` | Per-step evidence fields include observation, parsed action, usage, fallback, provider/model, metadata. |
| Information isolation | `backend/engine/visibility.py:13` and `backend/engine/visibility.py:31` | Every Agent receives only `PlayerView`, not full `GameState`. |
| LLM-only enforcement | `backend/agents/factory.py:139` and `backend/agents/factory.py:164` | `heuristic` is rejected for game AI seats; AI seats instantiate `CognitiveAgent`. |
| Cognitive boundary | `backend/agents/cognitive/agent.py:1` | `CognitiveAgent` is a protocol adapter and delegates cognitive work to smaller modules. |
| Tool loop | `backend/agents/cognitive/agent_loop.py:1` and `backend/agents/cognitive/agent_loop.py:307` | Bounded tool-calling loop with final structured decision. |
| Retrieval tools | `backend/agents/cognitive/tools.py:21` | Tools are closures over the current observation and memory. |
| Strategy retrieval | `backend/agents/cognitive/retrieval_prod.py:1` | Search-first, grep/BM25 strategy retrieval with policy filters. |
| Engine boundary | `backend/engine/game.py:1549` | Engine builds the view, calls the Agent, and records the returned `Decision`. |
| Audit persistence path | `backend/engine/game.py:2083` | `_record_decision()` serializes observation, action, usage, retrieval metadata and fallback flags. |

## Fit Against Agent Design Norms

An Agent system usually needs five things:

1. **Perception**: a controlled observation of the environment.
2. **State**: memory, beliefs, goals, or task context.
3. **Reasoning loop**: one or more model/tool iterations before acting.
4. **Action interface**: structured action output with validation.
5. **Feedback/evaluation**: logs, traces, and post-action learning.

AI Werewolf has all five:

| Norm | Current implementation | Assessment |
|---|---|---|
| Perception | `PlayerView` from `Visibility.for_player()` | Strong. This is the most important correctness boundary for Werewolf. |
| State | `Memory`, `BeliefTracker`, `SocialModel`, `Planner`, role state | Strong for current scope. Persistence can improve. |
| Reasoning loop | `AgentLoop` with `search_strategies`, `recall_memory`, `check_rules`, etc. | Reasonable and cost-controlled. |
| Action interface | `Decision` + `ActionType` + engine validation | Strong. Agent cannot directly mutate state. |
| Feedback/evaluation | `DecisionAudit`, Track B/C review, strategy usage metadata | Strong for research traceability. |

So the answer to “does it conform to an Agent specification?” is:

**Yes, if the target is a domain-specific autonomous decision Agent.**

It is not, and should not be, a generic autonomous operating-system/coding Agent like Claude Code. In this domain, the moderator engine is the orchestrator and authority. The player Agents are bounded autonomous actors.

## Comparison With Claude Code-Style Agentic Design

Claude Code is a general-purpose coding agent: it reads files, searches code, edits, runs commands, verifies, and iterates under a permission model. The public Claude Code documentation emphasizes terminal/editor integration, codebase context, workflow iteration, and user-controlled execution. Anthropic's broader agent guidance also recommends starting with simple workflows and only adding autonomous loops when the task needs them.

AI Werewolf mirrors the right subset:

| Claude Code-style pattern | AI Werewolf equivalent | Fit |
|---|---|---|
| Search before broad generation | `search_strategies` count/overview/content modes; grep/BM25 retrieval | Good. Domain-size corpus makes search-first practical. |
| Tool use under bounded control | `AgentLoop` with action-specific tool rounds | Good. Avoids open-ended loops in a live game. |
| Context separation | static system prompt + dynamic context in `AgentLoop` | Good. Similar motivation to prompt caching/context hygiene. |
| Verify before accepting action | `WerewolfGame` validates and settles decisions | Strong. Better than trusting the model. |
| Traceability | `DecisionAudit`, raw output, metadata, retrieval IDs | Strong. Good for research and debugging. |
| Permission boundary | `PlayerView` visibility + legal targets | Strong and domain-specific. |
| Long-running checkpoint/resume | Mostly in-memory, limited persistence | Gap. Fine for demo; weak for production experiments. |
| General subagent delegation | Not present | Not needed for current game player role. |

The current design is therefore **Claude Code-inspired in the useful engineering principles**, not equivalent in product category. That distinction matters. Trying to make every player a Claude Code-style free-form operator would weaken the game: it would expand action space, increase leakage risk, and make outcomes harder to audit.

## Comparison With Open Agent Frameworks

| Framework | Official design emphasis | Current AI Werewolf comparison | Verdict |
|---|---|---|---|
| Anthropic “Building Effective Agents” | Simple workflows first; agents for open-ended tool use; compose patterns carefully | The game loop is a deterministic workflow; each player decision is a bounded agentic subtask | Good fit. Current split is aligned. |
| Claude Code | Codebase search/edit/run/verify loop, terminal/editor integration, user-supervised permissions | AI Werewolf borrows search/tool/verification patterns, but replaces file system authority with game-rule authority | Correctly adapted, not copied. |
| LangGraph | Stateful graph, durable execution, human-in-the-loop, time travel/checkpointing | AI Werewolf has an implicit FSM in `WerewolfGame`, but not graph-level durable execution | Good enough now; adopt checkpoint ideas if long experiments need resume/replay. |
| AutoGen | Conversational agents, teams, tool agents, termination conditions | AI Werewolf is not a free group chat; engine-orchestrated adversarial agents are more appropriate | Current design is better for rule-bound Werewolf. |
| CrewAI | Role/task/crew abstractions and workflow Flows | AI Werewolf has roles and tasks, but the moderator engine is stricter than a crew manager | Use ideas for declarative tasks only if needed. |
| OpenAI Agents SDK | Agents, tools, handoffs, guardrails, tracing | AI Werewolf has tools, guardrails via engine/visibility, and tracing; no handoffs | Strong match on guardrails/tracing, handoffs unnecessary. |
| Semantic Kernel Agents | Agents as AI components with plugins/functions and process orchestration | AI Werewolf tools are plugin-like closures, while process orchestration lives in the engine | Reasonable custom implementation. |
| PydanticAI / typed agent libraries | Type-safe agent outputs, dependency injection, structured validation | AI Werewolf has dataclasses and schemas, but output validation could be stricter | Useful direction for hardening. |
| LlamaIndex Agents/Workflows | Data-centric agents with retrieval and workflow composition | AI Werewolf retrieval is domain-specific and inspectable rather than vector-first | Good choice for small, curated strategy corpus. |

## What Is Especially Good

1. **Engine as authority**

   The most important architecture decision is that Agents do not mutate `GameState`. They submit `Decision`; the engine validates phase, role, target, death, victory, and events. This is the right design for a game and for research validity.

2. **Information isolation is centralized**

   `Visibility.for_player()` is the correct choke point. This is better than letting each Agent decide what to ignore. It also makes audits meaningful because `DecisionAudit.observation` can show what the Agent actually saw.

3. **Agent Protocol is stable and AIWolf-compatible**

   The lifecycle is familiar to AIWolf-style systems while still allowing the internal implementation to be richer than classic callback agents.

4. **CognitiveAgent has real module boundaries**

   `CognitiveAgent` is mostly an adapter. Observation, memory, belief tracking, prompt assembly, retrieval, tool loop, and social modeling are separated. This is a real engineering improvement over a monolithic prompt agent.

5. **Tool calling is bounded by action risk**

   Speech can use strategy lookup; vote/night are currently stricter. This is a pragmatic latency/cost/safety tradeoff.

6. **Retrieval is inspectable**

   For a small curated strategy corpus, grep/BM25 with count/overview/content modes is easier to debug than vector search. It also produces better evidence for “what knowledge was used.”

7. **Evaluation and evolution are connected to runtime evidence**

   Track B/C are not just reports. They depend on recorded decisions, observations, raw output, retrieval usage, and fallback metadata.

## Main Engineering Risks

### P0 Risks

1. **Process-global AgentLoop trace state**

   `agent_loop.py` uses module globals such as `_LAST_LOOP_TRACE`, `_LAST_RETRIEVED_STRATEGIES`, and `_TRACK_C_RETRIEVAL_CACHE`. This is acceptable for early single-process experiments, but risky under concurrent games, parallel LLM calls, or replay comparisons. Trace data should move to an explicit per-decision context object.

   Recommended fix:

   ```text
   AgentRunContext(game_id, player_id, phase, request, trace, retrieval_usage, usage)
     -> passed into AgentLoop / tools
     -> returned with Decision metadata
     -> recorded by _record_decision()
   ```

2. **Fallback semantics need one policy**

   The factory rejects `heuristic`, and `CognitiveAgent` raises on empty speech/reasoning. That is good. But retrieval tools and engine continuity still have fallback-like behavior in some paths. Formalize the difference between:

   - LLM decision fallback: forbidden in strict official runs.
   - format repair from the same LLM: allowed.
   - retrieval backend fallback: allowed only if logged and not changing visibility.
   - game continuity fallback: allowed only for interactive/user flows, excluded from strict metrics.

3. **Output schema validation can be stronger**

   `Decision` is typed, but LLM parsing still has regex/text fallback. That is practical, but official evaluation should validate every output through a stricter model before action construction.

### P1 Risks

4. **Hardcoded tool budgets**

   `MAX_TOOL_ROUNDS_BY_ACTION` is fixed in `agent_loop.py`. This should become config-driven by action, role, phase, and experiment tier.

5. **Durable execution is limited**

   The game has snapshots and audit records, but cognitive memory and loop state are mostly in-memory. If experiments need exact replay, crash recovery, or time-travel debugging, borrow from LangGraph-style checkpointing without importing the entire framework.

6. **Role/action extensibility is still protocol-coupled**

   Adding a role may require changing enum, registry, engine phase handlers, Agent Protocol methods, frontend types, and tests. That is acceptable for a 7-12P Werewolf product, but not ideal for a role lab. A declarative action registry would reduce future friction.

### P2 Risks

7. **Tool contracts are text-heavy**

   Some tools return formatted text. That is convenient for LLM readability but weaker for machine checks. Keep the text prompt format, but also return structured payloads for audit and tests.

8. **Framework comparison claims need careful wording**

   Code comments say the retrieval approach is “inspired by Claude Code.” That is fine as an internal design analogy, but external reports should phrase this as “borrows search-first/tool-use principles” unless citing a specific public source.

## Recommended Optimization Roadmap

### P0: Make traces per-run, not global

Deliverable:

- Add `AgentRunContext` / `DecisionTrace` object.
- Pass it through `Pipeline -> AgentLoop -> tools`.
- Store `tool_trace`, `retrieved_doc_ids`, retrieval query summary, usage, and repair attempts in `Decision.metadata`.
- Remove or isolate `_LAST_LOOP_TRACE` and `_LAST_RETRIEVED_STRATEGIES`.

Why first: this directly improves concurrency safety and evidence quality without changing gameplay behavior.

### P0: Define strict-mode failure taxonomy

Deliverable:

- One table in code/docs mapping each failure type to behavior.
- Tests for LLM empty output, invalid target, retrieval backend failure, human pending action, and strict official run.
- Official experiment gate: `fallback_count=0` or explicit exclusion list.

Why second: it protects research claims.

### P1: Move agent policy knobs to config

Deliverable:

- YAML/env config for tool rounds, retrieval policy, repair rounds, and per-action strictness.
- Test one config fixture for “fast demo” and one for “strict experiment.”

Why: reduces code edits for experiments.

### P1: Add typed tool result envelope

Deliverable:

```text
ToolResult(
  tool_name,
  text_for_model,
  structured_payload,
  doc_ids,
  visibility_scope,
  latency_ms,
  error
)
```

Why: keeps LLM-friendly formatting while improving auditability.

### P1/P2: Consider checkpointing only if needed

Do not adopt LangGraph wholesale now. The current engine FSM is clearer for Werewolf. Add checkpoint primitives only when you need:

- crash recovery during expensive LLM games;
- exact replay from a decision point;
- time-travel debugging of Track B/C.

## Final Answer To The Design Question

The current Agent design is **reasonable, accurate, and defensible** for AI Werewolf.

It follows the right architecture for this domain:

```text
deterministic moderator engine
  + strict information projection
  + bounded autonomous player agents
  + structured decisions
  + validation/audit/replay/evolution
```

It should be described as:

> A rule-engine-orchestrated, domain-specific multi-agent system with bounded tool-using cognitive Agents.

It should not be described as:

> A fully general autonomous Agent platform equivalent to Claude Code.

That distinction is not a weakness. It is the reason the system can preserve Werewolf rules, information asymmetry, and reproducible evaluation.

## External References Checked

- Anthropic, “Building effective agents”: https://www.anthropic.com/engineering/building-effective-agents
- Claude Code overview: https://docs.anthropic.com/en/docs/claude-code/overview
- Claude Code “How Claude Code works”: https://code.claude.com/docs/en/how-claude-code-works
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- AutoGen AgentChat docs: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/index.html
- CrewAI docs: https://docs.crewai.com/
- OpenAI Agents SDK docs: https://openai.github.io/openai-agents-python/
- Semantic Kernel Agent Framework: https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/
- PydanticAI Agent docs: https://ai.pydantic.dev/agents/
- LlamaIndex Agent docs: https://docs.llamaindex.ai/en/stable/understanding/agent/
