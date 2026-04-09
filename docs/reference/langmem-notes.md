# LangMem — Distilled Reference

Last fetched: 2026-04-09

Scope: just the bits Recall actually uses. Source of truth is upstream docs; this file exists
so we don't have to re-read them every task.

## What LangMem is

> "LangMem helps agents learn and adapt from their interactions over time."
> — <https://langchain-ai.github.io/langmem/>

LangMem ships:

- A **core memory API** (Memory Managers, Prompt Optimizers) that's storage-agnostic.
- **Memory management tools** agents call during a conversation (hot path).
- A **background memory manager** that extracts / consolidates memories after the fact.
- **Native integration with LangGraph's Long-term Memory Store** (`BaseStore`), which is what
  we care about for Recall.

Two layers, per the conceptual guide
(<https://langchain-ai.github.io/langmem/concepts/conceptual_guide/>):

1. **Core API** — functions that transform memory state, independent of storage.
2. **Stateful integration** — LangGraph-dependent components that persist via a `BaseStore`
   (Store Managers, Memory Management Tools).

## Install

```bash
pip install -U langmem
# or
uv pip install -U langmem
```

Source: <https://langchain-ai.github.io/langmem/> (overview page). The site does not pin a
version number on the landing page; check PyPI at install time and record the resolved
version in `uv.lock`.

## Memory taxonomy (conceptual)

From <https://langchain-ai.github.io/langmem/concepts/conceptual_guide/>:

- **Semantic memory** — facts & knowledge. Two shapes:
  - *Collections*: unbounded documents searched at runtime.
  - *Profiles*: schema-based, single document per subject.
- **Episodic memory** — past experiences; successful interactions as few-shot examples,
  preserving situation + reasoning.
- **Procedural memory** — how the agent should behave; evolves via prompt/instruction
  refinement.

Formation modes:

- **Active / "conscious"** — extracted during the conversation (hot path). Immediate, but
  adds latency.
- **Background / "subconscious"** — post-conversation reflection. Higher recall, no latency
  hit on the user turn.

Storage organisation: hierarchical namespaces (e.g. `organization → user → context`) with
template variables resolved from `RunnableConfig.configurable` at call time.

## Reference index (what's under `/reference/`)

The LangMem reference has five sections (<https://langchain-ai.github.io/langmem/reference/>):

| Section | Symbols | Relevant to Recall? |
| --- | --- | --- |
| Extractive Memory | `create_memory_manager`, `create_memory_store_manager` | Maybe — see below |
| Tools | `create_manage_memory_tool`, `create_search_memory_tool` | Yes — main surface |
| Prompt Optimization | `create_prompt_optimizer`, `create_multi_prompt_optimizer` | Not v1, but see note |
| Utils | `NamespaceTemplate`, `ReflectionExecutor` | Partial |
| Short Term Memory | `SummarizationNode`, `summarize_messages`, `RunningSummary` | No — conversation summarisation, not our use case |

## The two memory tools

Both live in `langmem` and are factory functions that return a LangChain/LangGraph `Tool`
bound to a `BaseStore`. Signatures below are verbatim from
<https://langchain-ai.github.io/langmem/reference/tools/>.

### `create_manage_memory_tool`

```python
create_manage_memory_tool(
    namespace: tuple[str, ...] | str,
    *,
    instructions: str = (
        "Proactively call this tool when you:\n\n"
        "1. Identify a new USER preference.\n"
        "2. Receive an explicit USER request to remember something or otherwise alter your behavior.\n"
        "3. Are working and want to record important context.\n"
        "4. Identify that an existing MEMORY is incorrect or outdated.\n"
    ),
    schema: Type = str,
    actions_permitted: Optional[tuple[Literal["create", "update", "delete"], ...]] = (
        "create", "update", "delete",
    ),
    store: Optional[BaseStore] = None,
    name: str = "manage_memory",
)
```

Returned tool callable:

```python
def manage_memory(
    content: str | None = None,
    id: str | None = None,
    action: Literal["create", "update", "delete"] = "create",
) -> str: ...
```

Key points:

- `namespace` accepts either a tuple template or a plain string; placeholder segments like
  `"{user_id}"` are substituted from `RunnableConfig.configurable` at invocation time.
- `schema` lets you store structured (Pydantic / TypedDict) memories instead of strings.
- `actions_permitted` is how you downgrade to e.g. append-only (`("create",)`).
- `store=None` means the tool resolves the store from the ambient LangGraph runtime via
  `get_store()` (contextvar).

### `create_search_memory_tool`

```python
create_search_memory_tool(
    namespace: tuple[str, ...] | str,
    *,
    instructions: str = _MEMORY_SEARCH_INSTRUCTIONS,
    store: BaseStore | None = None,
    response_format: Literal["content", "content_and_artifact"] = "content",
    name: str = "search_memory",
)
```

Returned tool callable:

```python
def search_memory(
    query: str,
    limit: int = 10,
    offset: int = 0,
    filter: dict | None = None,
) -> tuple[list[dict], list]: ...
```

Source: <https://langchain-ai.github.io/langmem/reference/tools/>.

- `query` drives vector search if the store has an index; otherwise it's lexical.
- `filter` is a metadata filter dict passed through to `BaseStore.search`; see the
  AsyncPostgresStore notes for operator semantics and gotchas.
- `response_format="content_and_artifact"` is the form LangGraph's tool-calling machinery
  wants if you need the raw hit list in downstream nodes.

## Memory managers (extractive memory)

Source: <https://langchain-ai.github.io/langmem/reference/memory/>. These are the LLM-driven
"read a conversation, emit memory records" helpers. They sit above the store, not inside it.

### `create_memory_manager` — stateless extractor

```python
create_memory_manager(
    model: str | BaseChatModel,
    /,
    *,
    schemas: Sequence[S] = (Memory,),
    instructions: str = _MEMORY_INSTRUCTIONS,
    enable_inserts: bool = True,
    enable_updates: bool = True,
    enable_deletes: bool = False,
) -> Runnable[MemoryState, list[ExtractedMemory]]
```

- Pure function: takes a conversation, returns extracted memory records. **Does not touch
  any store.** Caller persists.
- `schemas` accepts Pydantic models for structured memories; default is LangMem's built-in
  `Memory` (free text).
- Async-capable `Runnable`. Invoke with `await manager(messages)`.

### `create_memory_store_manager` — stateful, store-aware

```python
create_memory_store_manager(
    model: str | BaseChatModel,
    /,
    *,
    schemas: list[S] | None = None,
    instructions: str = _MEMORY_INSTRUCTIONS,
    default: str | dict | S | None = None,
    default_factory: Callable[[RunnableConfig], ...] | None = None,
    enable_inserts: bool = True,
    enable_deletes: bool = False,
    query_model: str | BaseChatModel | None = None,
    query_limit: int = 5,
    namespace: tuple[str, ...] = ("memories", "{langgraph_user_id}"),
    store: BaseStore | None = None,
    phases: list[MemoryPhase] | None = None,
) -> MemoryStoreManager
```

- Wraps `create_memory_manager` plus a `BaseStore`. On each call: searches the store for
  relevant prior memories, runs the extractor with that context, then upserts results.
- `query_model` lets you use a cheaper/faster model for the "which existing memories matter"
  step than for extraction itself.
- `namespace` template is resolved via `NamespaceTemplate` (see below) from
  `RunnableConfig.configurable`. Default placeholder is `{langgraph_user_id}`.
- Exposes `.search(query=..., config=...)` as a convenience on top of `BaseStore.search`.

## Utilities

Source: <https://langchain-ai.github.io/langmem/reference/utils/>.

### `NamespaceTemplate`

```python
NamespaceTemplate(("org", "{user_id}"))(
    {"configurable": {"user_id": "alice"}}
)  # -> ("org", "alice")
```

Substitutes `{name}` segments from `config["configurable"][name]`. Inside a LangGraph run
the config is picked up implicitly. Missing keys raise at resolution time.

### `ReflectionExecutor`

```python
ReflectionExecutor(
    reflector: Runnable | str,
    namespace: str | tuple[str, ...] | None = None,
    *,
    url: str | None = None,
    client: LangGraphClient | None = None,
    sync_client: SyncLangGraphClient | None = None,
    store: BaseStore | None = None,
) -> Executor
```

Schedules reflection (i.e. background memory extraction) either locally (pass `store=`) or
remotely against a deployed LangGraph instance (`url=` / `client=`). `reflector` can be a
callable or a string naming a remote graph. Local mode returns a `LocalReflectionExecutor`,
remote mode a `RemoteReflectionExecutor`.

## Prompt optimization (procedural memory engine)

Source: <https://langchain-ai.github.io/langmem/reference/prompt_optimization/>.

These optimizers don't touch a `BaseStore` — they transform `(trajectories, prompt)` →
`improved prompt`. They matter to Recall only as the mechanism behind **procedural memory**
(the conceptual guide's third memory type: "how the agent should behave"). If we ever let
agents store evolving instructions and refine them from feedback, these are the building
blocks; we would *not* reimplement them.

### `create_prompt_optimizer`

```python
create_prompt_optimizer(
    model: str | BaseChatModel,
    /,
    *,
    kind: Literal["gradient", "metaprompt", "prompt_memory"] = "gradient",
    config: GradientOptimizerConfig | MetapromptOptimizerConfig | None = None,
) -> Runnable[OptimizerInput, str]
```

- **Input:** `{"trajectories": [(conversation, feedback), ...], "prompt": str}`.
- **Output:** improved prompt string.
- **Strategies:**
  - `gradient` (default) — multi-iteration reflection; most expensive, highest quality.
  - `metaprompt` — single-pass analysis; fewer LLM calls.
  - `prompt_memory` — extracts recurring patterns from trajectories.

### `create_multi_prompt_optimizer`

```python
create_multi_prompt_optimizer(
    model: str | BaseChatModel,
    /,
    *,
    kind: Literal["gradient", "prompt_memory", "metaprompt"] = "gradient",
    config: dict | None = None,
) -> Runnable[MultiPromptOptimizerInput, list[Prompt]]
```

Optimises a set of interdependent prompts in one shot, preserving cross-prompt consistency.
Use case: multi-agent or multi-stage pipelines where improving one prompt in isolation
breaks another.

**Recall relevance:** Out of scope for v1 (REQUIREMENTS.md E2 has no "procedural memory"
kind). If/when we add one, storage is: a memory record whose `kind="procedural"` and whose
`text` is the prompt, plus `trajectories` stored alongside as embedded feedback. Evolution
is: periodically run the optimizer against the stored trajectories and upsert the refined
prompt. Record this as an ADR at that point — don't pre-build it.

## Wiring tools to a store

The idiomatic pattern (from the hot-path quickstart,
<https://langchain-ai.github.io/langmem/hot_path_quickstart/>):

```python
from langgraph.prebuilt import create_react_agent
from langmem import create_manage_memory_tool, create_search_memory_tool

agent = create_react_agent(
    "anthropic:claude-3-5-sonnet-latest",
    tools=[
        create_manage_memory_tool(namespace=("memories", "{user_id}")),
        create_search_memory_tool(namespace=("memories", "{user_id}")),
    ],
    store=store,  # any BaseStore, e.g. AsyncPostgresStore
)
```

Inside a node / prompt function you can pull the store out of the ambient context:

```python
from langgraph.utils.config import get_store

def prompt(state):
    store = get_store()
    memories = store.search(("memories",), query=state["messages"][-1].content)
```

## Namespace templating

From the hot-path quickstart:

| Pattern                                          | Purpose                                  |
| ------------------------------------------------ | ---------------------------------------- |
| `("memories", "{user_id}")`                      | per-user                                 |
| `("memories", "{assistant_id}")`                 | per-assistant, spans users               |
| `("memories", "{org_id}", "{user_id}")`          | org-wide search, per-user writes         |
| `("memories", "{user_id}", "manual_memories")`   | per-user, typed subspace                 |

Placeholders are resolved from `RunnableConfig.configurable` at call time, e.g.
`config={"configurable": {"user_id": "u-123"}}`. Missing keys raise at tool-invocation
time — treat them as required runtime inputs.

Source: <https://langchain-ai.github.io/langmem/hot_path_quickstart/>.

## Gotchas for Recall

- **Namespace shape is fixed by ADR.** Recall's namespace is `(scope, project_id)` — see
  ADR 0001 (storage namespace) and ADR 0004 (scope invariant). LangMem's templating is
  flexible enough to express this, but do **not** add a third segment (`user_id`, `kind`,
  etc.) without widening the ADR. REQUIREMENTS.md S1.7 / S3.7 is the backing invariant.
- **Do not expose raw LangMem tools as MCP tools.** We have a ≤6 MCP tool budget
  (REQUIREMENTS.md E2). LangMem's tools are an *implementation* of our MCP surface, not the
  surface itself. Wrap, don't re-export.
- **`kind` is data, not a subnamespace.** Store `kind` inside the memory's value/metadata so
  we can filter with `BaseStore.search(..., filter={...})` rather than multiplying
  namespaces. Keeps ADR 0001 intact.
- **`actions_permitted` is our knob for global scope.** If we ever want `scope=global` to be
  append-only for non-admin callers, set `actions_permitted=("create",)` on the manage tool
  bound to that scope.
- **Default `instructions` prompt leaks "USER preference" framing.** Our agents are coding
  agents, not chatbots. Override `instructions=` when we instantiate the tool so the prompt
  matches Recall's memory taxonomy (see REQUIREMENTS.md E2 for the kinds we care about).
- **`store=None` relies on `get_store()`.** That contextvar is only populated inside a
  LangGraph run. In the MCP server hot path we're outside a LangGraph graph, so we must
  pass `store=` explicitly or call `BaseStore` directly and skip LangMem's tool wrappers.
- **We probably do not use `create_memory_store_manager` or `ReflectionExecutor`.** These
  assume LangMem owns the extraction pipeline and the namespace template resolves from a
  LangGraph `RunnableConfig`. Recall's callers are coding agents that already decided what
  to store — they pass memories to us, we don't extract. If we ever add background
  consolidation, revisit. For v1, we use only `create_manage_memory_tool` /
  `create_search_memory_tool` — or skip LangMem's tool wrappers entirely and call
  `BaseStore` directly from our MCP handlers.
- **Short Term Memory module is irrelevant.** `SummarizationNode` / `summarize_messages`
  compress agent chat history within a graph run. Recall is the long-term store the agent
  queries across sessions — different layer. Do not import anything from
  `langmem.short_term`.
- **Version pinning.** LangMem is pre-1.0 and its tool signatures have changed between
  minor releases. Pin exactly in `pyproject.toml` and re-read this file's "Last fetched"
  date before bumping.

## Source index

- Overview + install: <https://langchain-ai.github.io/langmem/>
- Concepts: <https://langchain-ai.github.io/langmem/concepts/conceptual_guide/>
- Hot-path quickstart (store wiring + namespace templates):
  <https://langchain-ai.github.io/langmem/hot_path_quickstart/>
- Reference index: <https://langchain-ai.github.io/langmem/reference/>
- Tools reference: <https://langchain-ai.github.io/langmem/reference/tools/>
- Memory managers (extractive): <https://langchain-ai.github.io/langmem/reference/memory/>
- Utils (`NamespaceTemplate`, `ReflectionExecutor`):
  <https://langchain-ai.github.io/langmem/reference/utils/>
- Prompt optimization (procedural memory engine, not v1):
  <https://langchain-ai.github.io/langmem/reference/prompt_optimization/>
- Short-term memory (not relevant):
  <https://langchain-ai.github.io/langmem/reference/short_term/>
