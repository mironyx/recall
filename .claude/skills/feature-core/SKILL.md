---
name: feature-core
description: Core implementation cycle: read design, TDD, verify, silent-swallow check, diagnostics, commit, PR, CI probe, review, report. Called by /feature and /feature-team skills after branch setup.
allowed-tools: Read, Write, Edit, MultiEdit, Bash, Glob, Grep, Agent, Skill, TodoWrite
---

# Feature Core — Implementation Cycle

Executes the implementation cycle from design reading through PR review. Called after:

- The feature branch is checked out and current
- The board item is set to In Progress
- The session has been tagged

**Usage:** `/feature-core <issue-number>` — not typically invoked directly; called by `/feature` and `/feature-team` skills.

## Steps

Execute sequentially. Do not skip steps. Do not ask for confirmation — only pause on blockers.

### Step 3: Read design context

1. Read the issue body: `gh issue view <issue-number>`.
2. **Epic guard:** Check the issue labels. If the issue has the `epic` label, stop: "Issue #N is an epic, not a task. Use `/feature epic <N>` to pick a task within it."
3. Read all files referenced in the issue body (design docs, LLDs, type files, related source).
4. Read any existing source files in the target directory.
5. Understand the contract: inputs, outputs, types, error cases.

### Step 3b: Pick the simplest approach

Before writing any code, list 2-3 approaches in 1-2 sentences each. Pick the one that fixes the root cause with the least code. State why. Prefer fixing data at the source over adding complexity downstream (CLAUDE.md: "Simplicity first").

### Step 4: Implement with independent test authorship

The tests must be written by a separate agent, against the spec only, before any
implementation behaviour is written. This is the only way to stop the LLM from picking
assertions it already knows its about-to-be-written code will satisfy.

The flow is four sub-steps: interface → independent tests → implementation → green.

#### Step 4a: Write the interface, not the behaviour

Main agent writes only the *public surface* of the unit under change: types, function
signatures, class skeletons, and stub bodies that `raise NotImplementedError`. No
behaviour logic, no happy-path code, no error handling. The surface is derived from the
LLD or issue contract, not from any implementation choice.

For bug fixes the interface usually already exists — skip to Step 4b. If the bug fix
requires a new signature (e.g. adding a parameter), commit the signature change first.

The PostToolUse hook opens edited files in the editor automatically for diagnostics analysis.
If the hook fires with inline findings, address them before moving on.

#### Step 4b: Hand off to the `test-author` sub-agent

Launch the `test-author` agent with:

```
Launch Agent: test-author
Input:
  issue_number: <N>
  requirements_paths: <list of paths, e.g. ["docs/requirements/v2-requirements.md"]>
  lld_path: <path or "none">
  target_test_file: <tests/.../<test_unit>.py>
  unit_under_test: <src/recall/.../<unit>.py>
  mode: "feature" | "bugfix"
```

For `requirements_paths`: pass the project requirements doc plus any per-feature
requirements files the issue or LLD references. The requirements are the contract of
record — the test-author will cross-reference all three sources (requirements, LLD,
issue) and flag contradictions in its report.

The sub-agent reads the issue and LLD only, enumerates every observable property of the
contract, and writes the complete test file. It does not read implementation bodies. It
returns a report listing each property and the test that covers it.

**If the sub-agent reports fewer than three observable properties** or reports unresolved
spec gaps, **stop and escalate to the user** — the spec is too vague to implement against.
Do not try to paper over this by writing the tests yourself; that re-introduces the
same-agent bias the sub-agent exists to prevent.

**Before writing the first test**, the sub-agent should scan for reusable fixtures:

1. Grep existing `tests/` files in the same area (e.g. the neighbouring unit test for the
   module you're replacing or extending) for factory functions, shared input constants,
   and response helpers.
2. Check `tests/fixtures/` and `tests/helpers/` for anything already extracted.
3. **If the pattern you need already exists, import it** — never copy-paste boilerplate.
4. **If you are about to write a helper that looks similar to one in a neighbouring test
   file, extract both into `tests/fixtures/<topic>.py` first**, then import from
   both places. Do this in the same commit as the new tests. For integration tests
   that need a real store, use a shared pytest fixture in `tests/conftest.py` or
   `tests/integration/conftest.py` — never build a `testcontainers` Postgres per test.

**Never mock AsyncPostgresStore.** Integration tests hit real Postgres via testcontainers.

#### Step 4c: Implement against the tests

Main agent reads the test file written by the sub-agent and implements the stub bodies
to make the tests pass.

- You MAY NOT modify the tests to match what you built, except for: fixing typos in
  test names, fixing imports the sub-agent got wrong, and renaming a test for clarity
  without changing its assertion.
- If a test looks semantically wrong (the sub-agent misread the spec), stop and report
  to the user. Do not change the test unilaterally — the independence of the test
  authorship is the whole point.
- If a test is uncompilable because a type is wrong, fix the test's type annotation but
  keep the assertion identical.

Run `uv run pytest <test-file>` after each small increment. Continue until all tests
in the file pass.

#### Step 4d: Self-check coverage before Step 5

Before running the full suite, re-read the sub-agent's report and confirm every listed
property maps to a passing test. If the sub-agent missed a property you can see in the
spec, add the test yourself and note this in the Step 10 report (so we can feed it back
into the sub-agent's prompt).

### Step 5: Full verification

Run all checks. **All must pass — zero failures, including integration tests — before proceeding.**

```bash
uv run pytest                                    # full suite — unit + integration, not just new tests
uv run mypy                                      # strict mode — no type errors
uv run ruff check .                              # lint — no errors
uv run ruff format --check .                     # format — no drift
```

**Run the full suite, not just the test files you wrote.** `uv run pytest` with no filter runs
every test in the repo. If you see pre-existing failures, they are your problem — fix them.

**Integration test failures are not pre-existing — fix them.** If `uv run pytest` reports
failures under `tests/integration/` (tests marked `@pytest.mark.integration`), diagnose and
resolve before continuing. Do not dismiss integration failures as "unrelated to this PR" and
proceed to create the PR. Integration tests hit a real Postgres via testcontainers — if they
fail, something is actually broken.

### Step 5b: Silent-swallow check (blocking gate)

Before proceeding, grep for `except` blocks that may swallow errors without logging
or re-raise:

```bash
grep -rn -E "^\s*except( [A-Za-z_.]+( as [a-z_]+)?)?:" src/recall/ \
  | grep -v "logger\.\|log\.\|raise\b"
```

Any match must be resolved — narrow the exception, add `logger.exception(...)`, and either
recover or `raise`. A bare `except:` or `except Exception:` is never acceptable in `src/`.
Do not proceed to Step 6 with unguarded except blocks.

### Step 6: Diagnostics (blocking gate)

Run `/diag` on all files changed in this cycle. This is a **blocking gate** — do not proceed to Step 7 until clean.

**Both `src/` and `tests/` files must be checked.** Analysers flag Code Duplication in test
files (repeated fixtures, repeated arrange/act/assert scaffolding). These warnings are
blocking — fix them before proceeding to Step 7.

Then:

1. Run `/diag` on all changed files — including every modified test file under `tests/`.
2. If any findings exist, fix them all.
3. After fixing, re-run `/diag` to confirm the findings are gone — do not assume a fix worked without seeing the updated diagnostics.
4. Repeat until `/diag` reports zero findings.
5. Re-run Step 5 (full verification) after any fixes.

Only proceed to Step 6b when `/diag` reports zero findings on non-generated files.

### Step 6b: Evaluate (blocking gate)

Launch the `feature-evaluator` agent as a sub-agent. Its primary job is now a *coverage
audit*, not a test factory — Step 4b already produced independent tests, so the
evaluator's role is to confirm that the contract is fully covered and probe for genuine
gaps only.

Pass it:

- `requirements_paths` — same list passed to the test-author in Step 4b
- `lld_path` — the LLD file read in Step 3 (or the issue number if no LLD exists)
- `issue_number` — the current issue number
- `changed_files` — all `src/` files created or modified in this cycle
- `test_files` — all `tests/` files created or modified in this cycle (including the
  file the `test-author` sub-agent produced in Step 4b)

```
Launch Agent: feature-evaluator
Input: requirements_paths=<list> lld_path=<path> issue_number=<N> changed_files=<list> test_files=<list>
```

**Triage the verdict:**

- **PASS** — every acceptance criterion maps to at least one passing test, no gaps. Proceed to Step 7.
- **PASS WITH WARNINGS** — minor gaps found, evaluator added a small number of adversarial tests. Review warnings, fix quick wins, note the rest in the PR body. Proceed to Step 7.
- **FAIL** — a criterion is uncovered or an adversarial test exposed a real defect. Fix the implementation, re-run Step 5 (full verification) and Step 6 (`/diag`). Do NOT re-run the evaluator — proceed to Step 7 after verification passes.

**Volume signal (report-only, never blocks):** if the evaluator writes more than three
adversarial tests, note the count and the evaluator's per-test category breakdown in the
Step 10 report and in the PR body under "process notes". Do not pause, do not escalate,
do not re-run anything. The PR still ships on this commit — the signal exists purely so
the test-author prompt can be tightened in future iterations.

The evaluator writes tests, if any, to `tests/evaluation/test_<slug>_eval.py`. These
files are committed alongside the feature code in Step 7. They should be short or empty
when Step 4b did its job; volume here is diagnostic, not the point.

### Step 7: Commit

Stage and commit with a conventional commit message referencing the issue number:

```bash
git add <specific-files>
git commit -m "feat: <description> #<issue-number>"
```

One commit per issue. Do not batch multiple issues.

### Step 8: Push and create PR

```bash
git push -u origin HEAD
gh pr create --title "<short title>" --base main --body "$(cat <<'EOF'
## Summary
<1-3 bullet points of what was implemented>

## Issue
Closes #<number>

## Design reference
<path to design doc section>

## Test plan
- [ ] `uv run pytest` — all tests pass (unit + integration)
- [ ] `uv run mypy` — clean
- [ ] `uv run ruff check .` — clean
- [ ] Design contracts verified (field names, types, schemas match)

## Verification
- **Tests added:** N
- **Total tests:** N (M test files)
EOF
)"
```

### Step 8b: CI probe (background)

Immediately after the PR is created, launch the `ci-probe` agent in the background.
It will block on `gh run watch` and report back when CI completes — no polling needed.

```
Launch Agent: ci-probe
Input: pr=<pr-number>
run_in_background: true
```

Continue with Step 9 immediately — do not wait for the CI probe.
When the probe reports back, triage its findings the same way as review findings:

- **CI failure** — fix the root cause, push, note in the Step 10 report.
- **CI pass** — note in the Step 10 report.

### Step 9: Review

Run `/pr-review-v2 <pr-number>` on the PR just created. This posts a comment on the PR and
returns findings. Triage each finding:

- **Blocker / correctness issue** — fix it: update the code, re-run Step 5 (verification), add a commit, push.
- **Design contract mismatch** — check whether the design or the implementation is wrong:
  if the implementation is wrong, fix it; if the design is outdated, update the design doc in the same branch.
- **Non-blocking suggestion** — decide whether it is worth fixing now (quick win) or deferring. If deferring, note it in the Step 10 report.
- **Style / minor** — fix if trivial; otherwise note and move on.

After any fixes, re-run `/pr-review-v2 <pr-number>` to confirm no new issues were introduced.

### Step 10: Report

Summarise what was done:

- Issue number and title
- Branch and PR link
- Tests added / total
- Review outcome: what was found, what was fixed, what was deferred
- CI outcome: pass / fail / pending (if the ci-probe has not yet reported back)
- Any warnings or notes (PR size, diagnostics findings, design drift)
- Suggested next item from the board

**Stop here.** User reviews the PR. Post-PR workflow (merge, close, board update) is handled by `/feature-end`.

**DO NOT** move the board item to `done`. Leave it at `in progress` — `/feature-end` handles that after merge.

## Blocker policy

**Pause and report** (do not attempt workarounds) if:

- Design doc is missing or ambiguous for this issue
- Tests fail after 3 fix attempts on the same error
- Type errors that suggest a design contract mismatch
- External dependency is unavailable (e.g., a function from an unmerged PR)
- Issue has no acceptance criteria

**Do NOT pause for:**

- Linting issues (fix them)
- Minor test adjustments (refactor)
- Missing barrel exports (create them)
- Diagnostic warnings (fix them)
- PR size slightly over 200 lines (warn in PR description, continue)

**Never invoke `/simplify`** — it is too costly for routine features and redundant with `/pr-review-v2`'s code quality checks. Only run it if the user explicitly asks.
