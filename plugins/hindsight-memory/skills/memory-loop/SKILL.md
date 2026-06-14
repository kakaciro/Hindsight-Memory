---
name: hindsight-memory-loop
description: Global system memory retrieval and reflection loop. This skill automatically activates for every conversation to load user identity and preferences.
---

# Hindsight Memory Loop

You are equipped with a local Hindsight memory plugin. 
To ensure you respond instantly and DO NOT waste tokens or run into infinite loops:

1. **Automatic Initialization Check (Strict Budget)**:
   - As your FIRST action in any session, you MUST call `recall_codex_memory` ONLY ONCE with the query `"user profile and identity"`.
   - **DO NOT** run recursive file scans (`Get-ChildItem -Recurse` or similar) to look for history or logs. Searching disk metadata is highly discouraged and wastes tokens.
   - If the memory search yields no matching facts, assume this is a fresh workspace and ask the user directly instead of spinning.

2. **Address the User Correctly**:
   - If the recalled memory contains `"User profile: The user is the boss (老板). Codex should always address the user as '老板'."`, you must immediately use this title.

3. **Active Memory Persistence**:
   - Only call `retain_codex_memory` when a significant preference is explicitly stated, or a critical bug fix is successfully completed.

4. **Session-End Self-Review (Mandatory)**:
   - Before ending any session, you MUST review the entire conversation and call `retain_codex_memory` for EVERY error that was encountered and fixed, every design decision made, and every non-trivial lesson learned.
   - The fact string must describe: what went wrong, root cause, fix applied, and why.
   - Do not skip this step even if the session seemed uneventful; at minimum confirm there were no new lessons.

5. **Error Tracking During Session**:
   - When you encounter any error (TypeError, SyntaxError, connection failure, misconfiguration, etc.), note it immediately.
   - For EVERY failed shell command, tool call, API call, test run, container operation, or code execution, you MUST call `record_codex_error` with source, error, root cause (if known), and fix (if known). This is the system-level hook contract for Codex operations.
   - After successfully resolving the error, call `retain_codex_memory` with a concise fact.
   - If the same error recurs later in the same session, call `retain_codex_memory` again with the same lesson text; the server will auto-increment the frequency counter so it ranks higher in future prompt injections.

6. **Before-Coding Mandatory Recall**:
   - Before writing or editing any code, you MUST call `recall_codex_memory` with a query that describes the task at hand (e.g., "Python type error debugging" or "Windows file operations").
   - Review the returned memories for relevant past failures or design decisions.
   - If any HARD RULE is returned, you MUST follow it without exception.

7. **Pattern Recognition and Rule Consolidation**:
   - When you notice 2 or more memories describing the same type of error or failure pattern across different sessions, you MUST call `retain_codex_memory` with a consolidated fact that begins with `[RULE]`.
   - A `[RULE]` fact is a hard constraint, but it MUST be scoped narrowly to the matching context. Do not create broad universal rules unless the evidence is universal.
   - Example: after seeing 3 separate `TypeError: int+str` bugs, store: `[RULE] In Python, ALWAYS cast inputs to int/float before arithmetic. Use try/int()/except ValueError.`
   - `[RULE]` entries are injected into every session with highest priority and strict mandatory language.

8. **Session-End Checklist (execute in order)**:
   1. Scan the entire conversation for every error, fix, and design decision.
   2. For each error: call `retain_codex_memory` with root cause + fix.
   3. Check if any error appeared 3+ times across this and prior sessions. If yes, call `retain_codex_memory` with a `[RULE]` consolidated fact.
   4. For each significant design/architecture decision: call `retain_codex_memory`.
   5. Confirm no lessons were missed.

9. **Self-Evolution: Automatic Hindsight → AGENTS.md Rules**:
   - The MCP server AUTOMATICALLY writes evolved rules to `C:\Users\123\.codex\AGENTS.md` when a fact reaches frequency >= 3.
   - You do NOT need to perform any manual action. The server handles the file write directly.
   - When retain returns a message containing `"Rule auto-written to AGENTS.md"`, the rule has been permanently persisted.
   - If retain returns `"AGENTS_MD_PATH not set or file not found"`, the rule was stored in the DB but not written to AGENTS.md. Report this to the user.
   - Rules in AGENTS.md are loaded before every session and have the highest priority. They constitute the permanent self-evolved behavioral genome of Codex.

10. **Maintenance and Reliability**:
   - At the end of any session that used Hindsight Memory, call `maintain_codex_memory` once.
   - Maintenance deduplicates fallback rules/facts, logs DB/bank health, and preserves corrupt fallback files instead of overwriting them.
   - If Hindsight DB is unavailable, continue using local fallback recall/retain and report DB health only after the task is complete.
