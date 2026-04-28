#!/usr/bin/env python3
"""
Parse pytest stdout/stderr and emit a compact summary.
Reads from stdin; writes to stdout.

Pass:  PASS N/N -- Xs
Fail:  FAIL N/N
         [test_file.py::TestClass::test_name]: first error line
"""
import sys
import re

raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")

# Strip ANSI colour codes
ansi = re.compile(r"\x1b\[[0-9;]*[mK]")
clean = ansi.sub("", raw)
lines = clean.splitlines()

# --- Locate summary line ---
# pytest summary: "5 passed in 1.23s" or "2 failed, 3 passed in 0.98s"
# It appears near the end on the "=== short test summary ===" line or the final "===" line.
summary_line = None
for line in reversed(lines):
    if re.search(r"\d+ (passed|failed|error)", line) and "==" in line:
        summary_line = line
        break

is_fail = summary_line is not None and re.search(r"\d+ (failed|error)", summary_line) is not None

# --- Extract counts ---
passed = 0
failed = 0
if summary_line:
    m = re.search(r"(\d+) passed", summary_line)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) (failed|error)", summary_line)
    if m:
        failed = int(m.group(1))
total = passed + failed

duration = ""
if summary_line:
    m = re.search(r"in ([\d.]+s)", summary_line)
    if m:
        duration = m.group(1)

# --- PASS path ---
if not is_fail:
    n = total if total > 0 else passed
    print(f"PASS {n}/{n} -- {duration}")
    sys.exit(0)

# --- FAIL path ---
print(f"FAIL {failed}/{total}")

# Extract failing test IDs and first error line from the FAILURES section.
# pytest prints: "FAILED tests/unit/test_foo.py::TestFoo::test_bar - AssertionError: ..."
# and in the detailed block: "_ _ _ TestFoo.test_bar _ _ _" followed by "AssertionError: ..."
fail_blocks: list[tuple[str, str]] = []

# First pass: collect from short summary lines "FAILED path::test - reason"
for line in lines:
    m = re.match(r"FAILED\s+(\S+)\s+-\s+(.*)", line.strip())
    if m:
        test_id = m.group(1)
        reason = m.group(2).strip()[:120]
        fail_blocks.append((test_id, reason))

# Fallback: collect from "FAILED path::test" lines with no inline reason
if not fail_blocks:
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"FAILED\s+\S+::", stripped):
            test_id = re.sub(r"^FAILED\s+", "", stripped)
            error = ""
            for j in range(i + 1, min(i + 20, len(lines))):
                candidate = lines[j].strip()
                if re.match(r"(AssertionError|assert |E\s+)", candidate):
                    error = candidate.lstrip("E").strip()[:120]
                    break
            fail_blocks.append((test_id, error))

for name, err in fail_blocks[:5]:
    if err:
        print(f"  [{name}]: {err}")
    else:
        print(f"  [{name}]")

if failed > 5:
    print(f"  ... and {failed - 5} more failures")
