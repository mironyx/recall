---
name: pr-review-v2
description: Review code changes for bugs, design principles, contract adherence, framework best practices, and design conformance. Use before committing (/pr-review-v2) or on a PR (/pr-review-v2 123). Adaptive: 1 agent for small diffs, 2 agents for large diffs. Agent B (framework patterns) only runs when framework files changed.
allowed-tools: Read, Write, Bash, Glob, Grep, Agent, TodoWrite, WebSearch
---

# PR Review v2

Two modes:

- `/pr-review-v2` — reviews local uncommitted changes (`git diff HEAD`)
- `/pr-review-v2 <pr-number>` — reviews a pull request; posts the result as a PR comment

**Cost-adaptive architecture.** Agent count scales with diff size:
- Diff < 150 lines → **1 agent** (Quality, covering all checks)
- Diff ≥ 150 lines → **2 agents** (Quality + Design Conformance in parallel)
- Agent B (framework patterns) only runs if framework or config files changed

---

## Process

### Step 1: Gather context

Determine mode from `$ARGUMENTS`:

- Number present → **PR mode**
- Otherwise → **local mode**

Run ALL of the following in parallel:

1. **PR mode:** `gh pr diff <number>` — full diff, untruncated.
   **Local mode:** `git diff HEAD` (fall back to `git diff --cached` if empty).
2. **PR mode:** `gh pr diff --name-only <number>`.
   **Local mode:** `git diff --name-only HEAD`.
3. Read `CLAUDE.md` (root).
4. Read `pyproject.toml` — capture exact versions of direct dependencies under
   `[project].dependencies` and `[project.optional-dependencies]`.

If diff is empty, print "Nothing to review — diff is empty." and stop.

### Step 2: Classify the review

From the gathered data, compute:

- `DIFF_LINE_COUNT` — total lines in the diff (added + removed)
- `CHANGED_FILES` — `.py` files added or modified (not deleted)
- `FRAMEWORK_DEPS` — top 5 packages imported in changed files that appear in
  `pyproject.toml`'s runtime dependencies (not dev / optional-dev extras)
- `PATTERNS_NEEDED` — true if ANY of these appear in the changed file list:
  - `pyproject.toml`, `uv.lock`
  - `.env`, `.env.*`
  - Any file importing a framework package (`langgraph`, `langmem`, `mcp`,
    `asyncpg`, `pgvector`, `structlog`, `opentelemetry`, `openai`, etc.)
  - Any config file (`ruff.toml`, `mypy.ini`, `pytest.ini`, `alembic.ini`,
    `src/recall/config*.py`)

Then fetch in parallel:
- **Issue body:** extract linked issue from PR body (`Closes #N`, `Fixes #N`, `Resolves #N`).
  Fetch `gh issue view <N>` for acceptance criteria and design doc paths. (PR mode only)
- **Commits:** `gh pr view <number> --json commits` (PR mode) or `git log main..HEAD --oneline`
  (local mode).

### Step 3: Launch agents (count depends on diff size)

---

#### If DIFF_LINE_COUNT < 150: launch ONE agent

**Agent Q — Quality (all checks, single agent)**

**Tools:** Read, Bash, Glob, Grep

```
You are a senior engineer doing a focused code review on a small diff. Cover all areas
in one pass: bugs, code justification, design principles, CLAUDE.md compliance, framework
anti-patterns, and design conformance.

## Part 1: Bugs (block if found)
- Logic errors, off-by-one, None dereferences, incorrect error handling
- Missing awaits on async coroutines (async function called without `await`)
- Race conditions or incorrect state transitions
- Security issues (SQL injection, credential exposure, missing auth checks)
- Silent `except` blocks that discard errors without at least a structured
  `logger.exception(...)` or re-raise — always a bug

## Part 2: Code justification (block if severe)
- Does this code solve the stated problem without over-engineering?
- YAGNI: is anything added not required by the current task?
- Helpers or abstractions introduced for a single use?
- Complexity that could be replaced by simpler alternatives?

## Part 3: Design principles (block if severe)
This project uses a layered architecture with clear boundaries:
- **Core rule:** `src/recall/services/` (business logic) must have no imports
  from framework specifics beyond the injected context — no `mcp.*` types,
  no direct `asyncpg` usage, no OpenAI SDK imports. Dependencies must point
  inward (services depend on the store and embedding **interfaces**, not
  concrete implementations).
- Single Responsibility: does each new function/module do one thing?
- Dependency Inversion: stores, embedders, and MCP context are injected into
  services, not imported as concrete implementations.
- Interface Segregation: no overly broad protocols forced on callers.
- Open/Closed: a change should not require modifying multiple unrelated modules.
- Functions over classes unless state genuinely requires a class.
- Respect the storage namespace invariant from REQUIREMENTS.md S3.7:
  `(scope, project_id)` and nothing else.

## Part 4: CLAUDE.md compliance
Only check these:
- `typing.Any` or `# type: ignore` without a one-line justification comment (warn)
- Mocking `AsyncPostgresStore` in any test under `tests/integration/` (block) —
  see CLAUDE.md "Things to never do"
- Every commit uses conventional format (`feat:`, `fix:`, etc.) AND references an
  issue (warn)

## Part 5: Design conformance (if design references exist)
For each changed `.py` file, look for a module-level comment near the top:
  # Design reference: <path> §<section>

If found:
1. Read the referenced doc section.
2. Extract every function / class name specified in that section.
3. For each function in the diff NOT in the designed list:
   - No justification comment → **block** (add `# Justification:` or update LLD)
   - Justification comment exists → **warn**
4. Exported/public unspecified functions are always **block** regardless of justification.

Also scan for silent `except` blocks (error not passed to any logger) → **block**.

## Part 6: Known framework anti-patterns (always check, no web search)
Read `.claude/skills/shared/anti-patterns.md` and apply all checks from that file.

## What NOT to report
- Pre-existing issues not made worse by this diff
- Anything CI catches automatically (lint, types, tests)
- Nitpicks a senior engineer would wave through

## Confidence rule
Only report if you would stake your review reputation on it.

## Input

CLAUDE.md:
<claude_md>
{{CLAUDE_MD}}
</claude_md>

Diff:
<diff>
{{DIFF}}
</diff>

Commits:
<commits>
{{COMMIT_MESSAGES}}
</commits>

Issue body:
<issue>
{{ISSUE_BODY}}
</issue>

## Output format

JSON array. Each element:
{
  "type": "bug" | "justification" | "design-principle" | "compliance" | "unspecified-function" | "silent-swallow" | "anti-pattern",
  "severity": "block" | "warn",
  "file": "relative/path.py",
  "line": 42,
  "finding": "one sentence",
  "evidence": "quoted code or rule"
}

Return [] if nothing warrants reporting.
```

Skip to **Step 4** with the single agent's output. Do not launch Agent A or Agent C.

---

#### If DIFF_LINE_COUNT ≥ 150: launch TWO agents in parallel (single message)

**Agent A — Code Quality & Correctness**

**Tools:** Read, Bash, Glob, Grep

```
You are a senior engineer doing a code review. Your job: bugs, code justification,
design principles, CLAUDE.md compliance, and known framework anti-patterns.
Design conformance (LLD matching) is handled by a separate agent.

## Bugs (block)
- Logic errors, off-by-one, None dereferences, incorrect error handling
- Missing awaits on async coroutines (async function called without `await`)
- Race conditions or incorrect state transitions
- Security issues (SQL injection, credential exposure, missing auth checks)
- Silent `except` blocks that discard errors without at least a structured
  `logger.exception(...)` or re-raise — always a bug

## Code justification (block if severe)
- Does this code solve the stated problem without over-engineering?
- YAGNI: is anything added not required by the current task?
- Helpers or abstractions introduced for a single use?
- Complexity replaceable by simpler alternatives?

## Design principles (block if severe)
This project uses a layered architecture with clear boundaries:
- **Core rule:** `src/recall/services/` (business logic) must have no imports
  from framework specifics beyond the injected context — no `mcp.*` types,
  no direct `asyncpg` usage, no OpenAI SDK imports. Services depend on the
  store and embedding **interfaces**, not concrete implementations.
- Single Responsibility: does each new function/module do one thing?
- Dependency Inversion: stores, embedders, and MCP context are injected into
  services, not imported as concrete implementations.
- Interface Segregation: no overly broad protocols forced on callers.
- Open/Closed: a change should not require modifying multiple unrelated modules.
- Functions over classes unless state genuinely requires a class.
- Respect the storage namespace invariant from REQUIREMENTS.md S3.7:
  `(scope, project_id)` and nothing else.

## CLAUDE.md compliance
Only check these:
- `typing.Any` or `# type: ignore` without a one-line justification comment (warn)
- Mocking `AsyncPostgresStore` in any test under `tests/integration/` (block)
- Every commit uses conventional format AND references an issue (warn)

## Known framework anti-patterns (always check, no web search)
Read `.claude/skills/shared/anti-patterns.md` and apply all checks from that file.

## What NOT to report
- Pre-existing issues not made worse by this diff
- Anything CI catches automatically
- Nitpicks a senior engineer would wave through

## Confidence rule
Only report if you would stake your review reputation on it.

## Input

CLAUDE.md:
<claude_md>
{{CLAUDE_MD}}
</claude_md>

Diff:
<diff>
{{DIFF}}
</diff>

Commits:
<commits>
{{COMMIT_MESSAGES}}
</commits>

Issue body:
<issue>
{{ISSUE_BODY}}
</issue>

## Output format

JSON array. Each element:
{
  "type": "bug" | "justification" | "design-principle" | "compliance" | "anti-pattern",
  "severity": "block" | "warn",
  "file": "relative/path.py",
  "line": 42,
  "finding": "one sentence",
  "evidence": "quoted code or rule"
}

Return [] if nothing warrants reporting.
```

---

**Agent C — Design Conformance**

**Tools:** Read, Bash, Glob, Grep

```
You are checking whether the implementation matches its LLD design references, and scanning
for silent error swallowing and diagnostics issues.

## Step 1: Identify design references

For each changed `.py` source file, look for a module-level comment near the top:
  # Design reference: <path> §<section>

If no such comment exists on a file, skip design-conformance checks for that file but still
run the silent-swallow and diagnostics checks.

## Step 2: Read the LLD and compare

For each design reference found:
1. Read the full referenced doc section.
2. Extract every function name explicitly specified (code blocks, bullet lists, "Internal
   decomposition" tables, signatures). Build DESIGNED_FUNCTIONS.
3. From the diff, collect every function declared in changed files. Build IMPLEMENTED_FUNCTIONS.

**If the LLD has an internal decomposition section:**
- Functions in IMPLEMENTED_FUNCTIONS not in DESIGNED_FUNCTIONS:
  - No justification comment → **block** (add `# Justification:` or update LLD)
  - Justification comment exists → **warn**

**If the LLD has NO internal decomposition section:**
- Unspecified private helpers → **warn** ("LLD gap — update internal decomposition")
- Unspecified exported/public functions → **block** regardless

Note: the LLD is not infallible. Surface the gap — the resolution is a human decision.

Exported/public functions are higher risk than private helpers — note this in findings.

## Step 3: Silent except/swallow check

Scan the diff for `except` blocks where the exception is not passed to at least a
`logger.exception` / `logger.error` / structured log call, and not re-raised.
Bare `except:` and `except Exception:` that end in `pass` or a silent return are
always findings.

For each match: **block** finding. Fallback behaviour does not excuse missing observability.

## Step 4: Diagnostics check

For each changed source file, check whether a diagnostics file exists at
`.diagnostics/<same relative path>`. If it exists, read it.

Surface any Error or Warning severity finding as a **warn**. Omit Info-level unless related
to a flagged function.

## Input

Diff:
<diff>
{{DIFF}}
</diff>

Changed files:
<changed_files>
{{CHANGED_FILES}}
</changed_files>

## Output format

JSON array. Each element:
{
  "type": "unspecified-function" | "silent-swallow" | "diagnostic",
  "severity": "block" | "warn",
  "file": "relative/path.py",
  "line": 42,
  "finding": "one sentence",
  "evidence": "function name, quoted code, or diagnostic text"
}

For "unspecified-function" findings, include the LLD path in the "evidence" field.

Return [] if nothing warrants reporting.
```

---

#### Agent B — Framework Best Practices (ONLY if PATTERNS_NEEDED is true)

**Tools:** Read, Bash, Glob, Grep, WebSearch

If `PATTERNS_NEEDED` is false, **skip Agent B entirely.**

If `PATTERNS_NEEDED` is true, launch Agent B in the same message as Agent A and Agent C
(three parallel agents total).

```
You are checking two things: (1) design contract adherence, and (2) whether the diff uses
outdated or discouraged patterns in the frameworks it touches — not just deprecated APIs,
but practices the framework community now considers harmful or superseded.

The distinction matters: a package can be current and non-deprecated while specific usage
patterns within it are wrong. Your job is to catch those patterns too.

## Part 1: Design contract

If the PR references a design doc:
1. Read the full design doc section.
2. Find renamed or deleted names in the diff.
3. Search the design doc for stale references not updated in this PR.
4. Verify function signatures, type shapes, API endpoint paths match the design.
5. Check acceptance criteria from the linked issue — are all addressed?

## Part 2: Framework best practices (web search per framework)

For each framework package below, run ONE targeted web search. Frame each search as:
  "<package>@<version> best practices discouraged patterns <year>"
  or "<package>@<version> security recommendations current"

Do NOT frame searches as just "deprecated APIs" — you are looking for:
- Security anti-patterns (e.g. using wrong key type server-side, insecure defaults)
- Patterns the framework has moved away from even if not formally deprecated
- Usage that works but violates the framework's current recommended approach
- Known footguns the community has documented

Cross-reference findings with the diff. Only report if the diff actively uses a discouraged
or insecure pattern. Do not report theoretical risks not present in the code.

Examples of the kind of findings to look for (not exhaustive):
- `langgraph` / `AsyncPostgresStore`: nested-key filters in `asearch`
  (filters match top-level keys only), numeric comparison on store values
  (lexicographic only — dates must be ISO strings), widening the namespace
  beyond `(scope, project_id)`
- `asyncpg`: blocking calls inside `async def`, missing connection pool
  lifecycle management, SQL built via string formatting instead of
  parameter binding
- `mcp` SDK: hand-rolling transport or session handling instead of using
  the library primitives, returning non-JSON-serialisable tool results
- `openai` / embeddings: synchronous client inside async code, missing
  timeout + single retry (REQUIREMENTS.md S6.5)
- `opentelemetry` / `structlog`: hand-rolled spans where auto-instrumentation
  already covers the path (ADR-0011 says auto-instrumentation only in v1)

Packages to check:
{{FRAMEWORK_DEPS_WITH_VERSIONS}}

Maximum web searches: one per package, five packages max.

## Input

Diff:
<diff>
{{DIFF}}
</diff>

Issue body:
<issue>
{{ISSUE_BODY}}
</issue>

## Output format

JSON array. Each element:
{
  "type": "design-contract" | "anti-pattern",
  "severity": "block" | "warn",
  "file": "relative/path.py",
  "line": 42,
  "finding": "one sentence — include WHY this pattern is discouraged",
  "evidence": "quoted code from diff",
  "source_url": "URL of framework docs or community guidance, if found"
}

Return [] if nothing warrants reporting.
```

---

### Step 4: Consolidate and output

Collect JSON arrays from all agents that ran. Merge and deduplicate (keep the more specific
finding). Sort by severity: `block` items first, then `warn`.

**If no findings:**

```
### PR Review

No issues found. Checked: bugs, code justification, design principles, CLAUDE.md compliance,
framework anti-patterns, design conformance.
[Framework best practices: skipped — no framework files changed.]
```

**If findings exist:**

```
### PR Review

#### Blockers (N)

**[type] file.py:line**
<finding>
> <evidence>

#### Warnings (N)

**[type] file.py:line**
<finding>
> <evidence>
```

Types: `[bug]`, `[justification]`, `[design-principle]`, `[compliance]`, `[design-contract]`,
`[anti-pattern]`, `[unspecified-function]`, `[silent-swallow]`, `[diagnostic]`.

**PR mode:** post as a PR comment:
```bash
gh pr comment <number> --body "<formatted report>"
```

---

## Notes

- Do not run builds, type-checks, or tests — CI handles those.
- In the ≥ 150 line path: launch Agent A and Agent C (and Agent B if PATTERNS_NEEDED)
  in the **same message** so they run concurrently.
- If the diff is empty, report "Nothing to review — diff is empty." and stop.
- The 150-line threshold is a guide. If a large diff is mostly trivial changes (whitespace,
  renames, generated code), use judgment and prefer the single-agent path.
- The static anti-pattern list in `.claude/skills/shared/anti-patterns.md` runs on EVERY
  review at no extra cost — no web search, no extra agent. Agent B supplements this with
  framework-specific research only when framework files changed.
- The "integration test mocks `AsyncPostgresStore`" check is deliberately **block** not
  warn: the whole point of integration tests is catching schema / migration drift against
  real Postgres, and a mock defeats that. This is a correctness invariant, not style.
- Add new static anti-patterns to `.claude/skills/shared/anti-patterns.md` as the team
  discovers them. That file is the institutional memory of "things we've learned the hard way."
