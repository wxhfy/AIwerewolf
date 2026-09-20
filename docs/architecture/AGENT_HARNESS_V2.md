# Portable Agent Harness For Asymmetric-Information Environments

## Scope

The harness targets turn-based or phase-based environments where actors have
different information and must make constrained decisions. Werewolf is the
first adapter, not the architecture boundary. The same kernel should support
social deduction, hidden-role games, sealed auctions, card games, negotiation,
and other actor-observation-action environments.

```text
Environment Adapter
  -> DecisionRequest
       InformationState
       DecisionPoint
       ActionSpace
  -> Agent Harness
  -> ResolvedAction + append-only events
  -> Environment Adapter.apply_actions()
```

The environment owns truth. The harness owns bounded model execution. The
model owns neither environment state nor infrastructure access.

## Architectural Boundary

### Portable kernel

`backend/agent_harness` understands only:

- actor identity;
- actor-scoped information state;
- a domain-defined decision point;
- server-generated legal action options;
- Skill and Tool scopes;
- execution budgets, policy, validation, and audit events.

It does not understand roles, factions, day/night phases, votes, attacks,
potions, cards, bids, or win conditions.

### Environment runtime

`backend/game_runtime` defines the adapter and episode-driving seams:

```python
class EnvironmentAdapter(Protocol):
    def is_terminal(self, state) -> bool: ...
    def next_decision_batch(self, state) -> DecisionBatch: ...
    def apply_actions(self, state, batch, actions): ...
```

An adapter owns its full hidden state, state machine, visibility projection,
action-space generation, transition rules, and terminal conditions.

## Core Contracts

### InformationState

An Information State is an actor-scoped projection produced by the environment:

```text
schema identity and version
current observation
visible event history
actor-private memory
```

Hidden fields are absent rather than masked by prompts. The Harness and its
Tools never receive the environment's full state.

### DecisionPoint

The environment defines the semantic decision kind and sequence. Domain values
such as `werewolf.day.vote` or `auction.submit-bid` are opaque to the kernel.
An optional `simultaneous_group_id` identifies decisions that must be resolved
against the same frozen state.

### ActionSpace

The environment generates every legal `ActionOption` before model execution.
Each option has an opaque ID, canonical action type and canonical parameters.
The model selects an option ID; it cannot invent a target or overwrite trusted
parameters.

Open content such as speech is represented by an option with a constrained
response schema:

```json
{
  "option_id": "speak",
  "action_type": "speak",
  "response_schema": {
    "type": "object",
    "properties": {"text": {"type": "string", "minLength": 1}},
    "required": ["text"],
    "additionalProperties": false
  }
}
```

## Runtime Model

```text
DecisionRequest
  -> filter Skill catalog by request skill_scope
  -> intersect Tool scope with deployment policy
  -> append run.started with the complete request surface
  -> bounded model loop
       -> load one Skill
       -> call one scoped Tool
       -> select one ActionOption
  -> resolve and validate model response
  -> append action.accepted and run.completed
```

The append-only event log is the source of truth for a run. `run.started`
snapshots the information state, action space, scopes, schemas, metadata, and
budgets. Loaded Skill bodies, model steps, Tool calls, Tool results, and the
resolved action are recorded so historical runs remain reproducible after code
or strategy changes.

## Simultaneous Decisions

A simultaneous `DecisionBatch` is constructed from one frozen environment
state. The Episode Runner collects every action before calling
`apply_actions()`. A later actor therefore cannot observe an earlier actor's
sealed vote, bid, night action, or card choice.

Batch construction rejects mixed environments, mixed episodes, duplicate
request IDs, duplicate actors, and inconsistent simultaneous group IDs.

The current runner resolves model calls serially but preserves sealed-state
semantics. A later executor may parallelize calls without changing the adapter
contract.

## Skills

Skills are trusted strategy or procedure modules. The request explicitly
provides `skill_scope`; registry metadata may narrow it further by environment,
decision kind, and policy tags. Only names and descriptions are always visible;
full instructions load on demand.

Suggested layers:

- portable: `social-reasoning/evidence`, `negotiation/deception`;
- environment: `werewolf/day-speech`, `auction/value-estimation`;
- role/profile: `werewolf/role/seer`, `avalon/role/merlin`.

Visibility, legal actions, state transitions, and security policy are mandatory
runtime code, never optional Skills.

## Tools And Infrastructure

The model never receives SQL, database sessions, repositories, Redis clients,
filesystem access, shell access, unrestricted network clients, or full hidden
environment state.

Tool availability is the intersection of:

```text
deployment CapabilityPolicy
AND DecisionRequest.tool_scope
AND capability deny rules
```

Trusted Tool context fixes the environment, episode, actor, decision point,
and Information State. Tool arguments cannot change actor identity or visibility.

## Reference Harness Decisions

| Project | Mechanism retained |
|---|---|
| DeepSeek Harness | Append-only typed events, reconstructable requests, call-before-result ordering |
| OpenAI Codex | Explicit turn context, permission profiles, capability-aware tool boundaries |
| Pi | Small runtime core and progressive Skill disclosure |
| DeepAgents | Middleware composition and persistence seams without gameplay filesystem, shell, or subagents |

No framework is adopted wholesale. General coding-agent capabilities are not a
default fit for a hidden-information environment.

## Werewolf Adapter

The first production adapter is implemented in `backend/domains/werewolf`:

```text
Match Worker
  -> WerewolfGame selects the current actor or simultaneous actor set
  -> Visibility projects a role-safe PlayerView
  -> WerewolfDecisionAdapter generates DecisionRequest + legal ActionOptions
  -> per-seat AgentHarness calls the configured LLM planner
  -> Harness validates the selected option and emits an append-only trace
  -> adapter maps ResolvedAction back to engine Decision objects
  -> engine validates and applies the domain action
```

Role and faction remain `domain_metadata`. Role strategy is composed through
Agent Profile and scoped Skills rather than subclasses such as `SeerAgent` or
`WerewolfAgent`.

AI-only matches created by `backend.application.matches.executor.build_game`
use this path. Harness traces are included in decision metadata and flow
through the existing PostgreSQL decision persistence. Direct `WerewolfGame`
construction is domain-only and cannot execute AI decisions until a runtime is
attached.

## Remaining Replacement Work

There is no compatibility or shadow phase for the old cognitive lifecycle.

1. Add actor-scoped memory and narrow projection Tools.
2. Move harness traces from decision JSON metadata to a dedicated append-only PostgreSQL table/EventWriter.
3. Convert the internal engine `_ask` shell to explicit domain decision batches.

The portable kernel is wired into production AI-only match execution. Remote
Agent Service transport remains a later adapter; the current deployment uses
the same contract in-process inside the Match Worker.
