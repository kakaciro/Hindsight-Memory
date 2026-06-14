---
name: hermes-hindsight-memory-loop
description: Isolated Hermes Hindsight Memory loop. Use only for Hermes memory, rules, and operational learning.
---

# Hermes Hindsight Memory Loop

Hermes has its own isolated Hindsight memory bank: `hermes`.

Do not mix Hermes memory with Codex memory. Hermes writes to:
- Hindsight bank: `hermes`
- Fallback file: `C:\Users\123\plugins\hermes_hindsight_fallback.json`
- Rules file: `C:\Users\123\.codex\HERMES_AGENTS.md`

1. **Automatic Initialization Check**:
   - When working as or for Hermes, call `recall_hermes_memory` once with query `"Hermes profile and identity"`.
   - If no matching facts exist, treat Hermes as a fresh isolated agent memory space.

2. **Hermes Memory Persistence**:
   - Store Hermes-specific preferences, operational decisions, fixes, and recurring lessons with `retain_hermes_memory`.
   - Do not store Codex-only facts in Hermes memory.

3. **System-Level Error Hook**:
   - For every failed Hermes shell command, tool call, API call, test run, container operation, or code execution, call `record_hermes_error` with source, error, root cause, and fix when known.

4. **Conservative Rule Evolution**:
   - Repeated Hermes failures evolve into rules only for materially matching contexts.
   - Avoid broad universal Hermes rules unless the repeated evidence is universal.
   - Evolved Hermes rules are written to `HERMES_AGENTS.md`, not Codex `AGENTS.md`.

5. **Fine-Grained Fallback**:
   - If Hindsight DB is unavailable, Hermes recall/retain must continue using the local fallback file.
   - Fallback search uses token overlap, fuzzy similarity, frequency weighting, and rule priority.

6. **Maintenance**:
   - At the end of Hermes work, call `maintain_hermes_memory` once.
   - Maintenance deduplicates fallback, compacts Hermes rules, validates the `hermes` bank, and logs health.
