import json
import os
import re
import sys
import traceback
import hashlib
import subprocess
from datetime import datetime, timezone
from difflib import SequenceMatcher

import requests


BANK_ID = os.environ.get("HINDSIGHT_BANK_ID", "hermes")
BASE_ROOT = os.environ.get("HINDSIGHT_BASE_ROOT", "http://localhost:8888/v1/default/banks")
BASE_URL = f"{BASE_ROOT}/{BANK_ID}"

PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FALLBACK_PATH = os.environ.get("HINDSIGHT_FALLBACK_PATH") or os.path.join(PLUGIN_ROOT, "hermes_hindsight_fallback.json")
MAINTENANCE_LOG = os.path.join(PLUGIN_ROOT, "hermes_hindsight_maintenance.log")
AGENTS_PATH = os.environ.get("AGENTS_MD_PATH") or os.path.join(os.path.expanduser("~"), ".codex", "HERMES_AGENTS.md")

META_RE = re.compile(r"^\[freq:(\d+)\]\[ts:([^\]]+)\]\s*")
RULE_META_RE = re.compile(r"^\[RULE\]\[freq:(\d+)\]\[ts:([^\]]+)\]\s*")
RULE_RE = re.compile(r"^\[RULE\]")
PLACEHOLDER = "(No evolved rules yet. Rules will be appended here automatically as error patterns are learned.)"


def log(msg):
    sys.stderr.write(f"[Hindsight-MCP] {msg}\n")
    sys.stderr.flush()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def canonical_text(text):
    text = strip_meta(strip_rule_meta(text or ""))
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"\|\s*when:.*$", "", text)
    text = re.sub(r"\|\s*involving:.*$", "", text)
    text = re.sub(r"\(evolved from \d+ repeated incidents, [^)]+\)", "", text)
    text = re.sub(r"freq(?:uency)?[=: ]+\d+", "freq=n", text)
    return text.strip(" -.;:")


def stable_key(text):
    return hashlib.sha256(canonical_text(text).encode("utf-8")).hexdigest()[:24]


def similarity(a, b):
    return SequenceMatcher(None, canonical_text(a), canonical_text(b)).ratio()


def parse_meta(text):
    text = text or ""
    rm = RULE_META_RE.match(text)
    if rm:
        return int(rm.group(1)), rm.group(2), text[rm.end():]
    m = META_RE.match(text)
    if m:
        return int(m.group(1)), m.group(2), text[m.end():]
    return 1, now_iso(), text


def strip_meta(text):
    return META_RE.sub("", text or "")


def strip_rule_meta(text):
    return RULE_META_RE.sub("", text or "")


def is_rule(text):
    return bool(RULE_META_RE.match(text or "") or RULE_RE.match(text or ""))


def make_meta(freq, ts):
    return f"[freq:{freq}][ts:{ts}] "


def make_rule_meta(freq, ts):
    return f"[RULE][freq:{freq}][ts:{ts}] "


def empty_fallback():
    return {"version": 2, "facts": {}, "rules": {}, "failures": [], "last_maintenance": None}


def normalize_fallback(data):
    if not isinstance(data, dict):
        data = empty_fallback()
    data.setdefault("version", 2)
    data.setdefault("facts", {})
    data.setdefault("rules", {})
    data.setdefault("failures", [])
    data.setdefault("last_maintenance", None)
    if isinstance(data.get("rules"), list):
        rules = {}
        for item in data["rules"]:
            if isinstance(item, dict) and item.get("text"):
                key = stable_key(item["text"])
                if key not in rules or int(item.get("freq", 1)) > int(rules[key].get("freq", 1)):
                    rules[key] = item
        data["rules"] = rules
    return data


def load_fallback():
    try:
        if os.path.exists(FALLBACK_PATH):
            with open(FALLBACK_PATH, "r", encoding="utf-8") as f:
                return normalize_fallback(json.load(f))
    except Exception as e:
        # Do not overwrite corrupt fallback. Preserve for forensic recovery.
        corrupt = FALLBACK_PATH + ".corrupt." + datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            os.replace(FALLBACK_PATH, corrupt)
            log(f"Fallback was corrupt; moved to {corrupt}: {e}")
        except Exception:
            log(f"Fallback load failed and could not move corrupt file: {e}")
    return empty_fallback()


def save_fallback(data):
    data = normalize_fallback(data)
    os.makedirs(os.path.dirname(FALLBACK_PATH), exist_ok=True)
    tmp = FALLBACK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, FALLBACK_PATH)


def fallback_find(facts, text):
    key = stable_key(text)
    if key in facts:
        return key, facts[key]
    best_key = None
    best_score = 0.0
    for k, entry in facts.items():
        score = similarity(text, entry.get("text", ""))
        if score > best_score:
            best_score = score
            best_key = k
    if best_key and best_score >= 0.88:
        return best_key, facts[best_key]
    return key, None


def tokenize(text):
    return [t for t in re.findall(r"[a-z0-9_#+.-]+", canonical_text(text)) if len(t) > 1]


def fallback_score(query, text, freq=1):
    q_tokens = tokenize(query)
    t_tokens = tokenize(text)
    if not q_tokens or not t_tokens:
        return similarity(query, text)
    q = set(q_tokens)
    t = set(t_tokens)
    overlap = len(q & t) / max(len(q), 1)
    phrase = 0.25 if canonical_text(query) in canonical_text(text) else 0.0
    fuzzy = similarity(query, text) * 0.35
    freq_bonus = min(int(freq), 10) * 0.015
    return overlap * 0.5 + phrase + fuzzy + freq_bonus


def fallback_search(query, limit=8):
    fb = load_fallback()
    scored = []
    for entry in fb.get("facts", {}).values():
        score = fallback_score(query, entry.get("text", ""), entry.get("freq", 1))
        if score >= 0.25:
            scored.append((score, "fact", entry))
    for entry in fb.get("rules", {}).values():
        score = fallback_score(query, entry.get("text", ""), entry.get("freq", 1)) + 0.2
        if score >= 0.25:
            scored.append((score, "rule", entry))
    scored.sort(key=lambda x: (x[0], int(x[2].get("freq", 1))), reverse=True)
    return scored[:limit]


def dedupe_texts(texts, threshold=0.88):
    deduped = []
    for text in texts:
        body = text[2:] if text.startswith("- ") else text
        if any(similarity(body, existing[2:] if existing.startswith("- ") else existing) >= threshold for existing in deduped):
            continue
        deduped.append(text)
    return deduped


def db_recall(query, timeout=15):
    r = requests.post(f"{BASE_URL}/memories/recall", json={"query": query}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"DB recall HTTP {r.status_code}: {r.text[:200]}")
    return r.json().get("results", [])


def db_retain(content, timeout=20):
    r = requests.post(f"{BASE_URL}/memories", json={"items": [{"content": content}]}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"DB retain HTTP {r.status_code}: {r.text[:200]}")
    return r


def ensure_agents_section(content):
    if "## Auto-Evolved Rules" not in content:
        content += "\n\n---\n\n## Auto-Evolved Rules (Self-Generated by Hindsight Memory)\n\n"
        content += "These rules are automatically appended by Hindsight Memory when the same error pattern repeats 3+ times.\n"
        content += "They carry the highest priority and must not be violated under any circumstances.\n\n"
    return content.replace(PLACEHOLDER + "\n", "").replace(PLACEHOLDER, "")


def upsert_agents_rule(rule_key, rule_md):
    if not os.path.exists(AGENTS_PATH):
        os.makedirs(os.path.dirname(AGENTS_PATH), exist_ok=True)
        content = "# AGENTS.md\n"
    else:
        with open(AGENTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    content = ensure_agents_section(content)
    lines = content.splitlines()
    out = []
    marker = f"<!-- hindsight-rule:{rule_key} -->"
    skip_next = False
    replaced = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.strip() == marker:
            out.append(marker)
            out.append(rule_md)
            skip_next = True
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(marker)
        out.append(rule_md)
    with open(AGENTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")


def make_conservative_rule(fact, freq, ts):
    # Conservative rule: preserve scope and require applicability check to avoid overgeneralization.
    clean = strip_meta(strip_rule_meta(fact)).strip()
    return (
        f"- When the same context recurs, apply this learned fix: {clean} "
        f"Only apply when the current error/context materially matches this pattern. "
        f"(evolved from {freq} repeated matching incidents, {ts})"
    )


def record_failure(source, detail):
    fb = load_fallback()
    fb.setdefault("failures", []).append({"source": source, "detail": detail, "ts": now_iso()})
    fb["failures"] = fb["failures"][-100:]
    save_fallback(fb)


def maintenance_report():
    fb = load_fallback()
    before_facts = len(fb.get("facts", {}))
    before_rules = len(fb.get("rules", {}))

    # Dedupe facts by stable key / high similarity, keep highest frequency and newest timestamp.
    facts = {}
    for entry in fb.get("facts", {}).values():
        if not isinstance(entry, dict) or not entry.get("text"):
            continue
        key, existing = fallback_find(facts, entry["text"])
        if existing:
            existing["freq"] = max(int(existing.get("freq", 1)), int(entry.get("freq", 1)))
            if entry.get("ts", "") > existing.get("ts", ""):
                existing["ts"] = entry.get("ts")
        else:
            facts[key] = entry
    fb["facts"] = facts

    rules = {}
    for entry in fb.get("rules", {}).values():
        if not isinstance(entry, dict) or not entry.get("text"):
            continue
        key = stable_key(entry["text"])
        if key not in rules or int(entry.get("freq", 1)) > int(rules[key].get("freq", 1)):
            rules[key] = entry
    fb["rules"] = rules
    fb["last_maintenance"] = now_iso()
    save_fallback(fb)

    report = (
        f"maintenance {fb['last_maintenance']} | facts {before_facts}->{len(facts)} | "
        f"rules {before_rules}->{len(rules)} | failures={len(fb.get('failures', []))}\n"
    )
    with open(MAINTENANCE_LOG, "a", encoding="utf-8") as f:
        f.write(report)
    return report.strip()


def handle_list_tools():
    return {
        "tools": [
            {
                "name": "recall_hermes_memory",
                "description": "Recall Hermes memories from Hindsight DB with fine-grained local fallback search.",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
            {
                "name": "retain_hermes_memory",
                "description": "Store facts, lessons, and decisions with strict dedupe, fallback, conservative rule evolution, and AGENTS.md persistence.",
                "inputSchema": {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
            },
            {
                "name": "record_hermes_error",
                "description": "System-level error hook endpoint: record command/tool/code failures and learned fixes into memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"source": {"type": "string"}, "error": {"type": "string"}, "root_cause": {"type": "string"}, "fix": {"type": "string"}},
                    "required": ["source", "error"],
                },
            },
            {
                "name": "maintain_hermes_memory",
                "description": "Run Hindsight Memory maintenance: fallback dedupe, rules compaction, health logging.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
    }


def handle_recall(query):
    try:
        results = db_recall(query)
        texts = [f"- {strip_meta(strip_rule_meta(item.get('text', '')))}" for item in results]
        texts = dedupe_texts(texts, threshold=0.84)
        if texts:
            return {"content": [{"type": "text", "text": "\n".join(texts)}]}
    except Exception as e:
        record_failure("db_recall", str(e))
        log(f"DB recall failed: {e}; using fallback")

    matches = fallback_search(query)
    if matches:
        lines = []
        for score, kind, entry in matches:
            prefix = "[local-rule]" if kind == "rule" else "[local]"
            lines.append(f"- {prefix} {entry.get('text')} (freq={entry.get('freq', 1)}, score={score:.2f})")
        lines.append("(Results from fine-grained local fallback search.)")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    return {"content": [{"type": "text", "text": f"No matching memories found for '{query}'."}]}


def handle_retain(fact):
    fact = (fact or "").strip()
    if not fact:
        return {"content": [{"type": "text", "text": "No fact provided."}], "isError": True}

    fb = load_fallback()
    key, fb_entry = fallback_find(fb["facts"], fact)
    fb_freq = int(fb_entry.get("freq", 1)) + 1 if fb_entry else 1
    db_freq = 1

    try:
        existing = db_recall(fact, timeout=8)
        for item in existing:
            ef, _, body = parse_meta(item.get("text", ""))
            if similarity(fact, body) >= 0.84:
                db_freq = max(db_freq, ef + 1)
    except Exception as e:
        record_failure("retain_recall_dedupe", str(e))

    freq = max(fb_freq, db_freq)
    ts = now_iso()
    results = []

    fb["facts"][key] = {"text": fact, "freq": freq, "ts": ts, "key": key}
    save_fallback(fb)

    try:
        # Strict DB dedupe at MCP layer: only retain when this is new or a meaningful frequency milestone.
        # This prevents one DB document per repeated call while preserving learning state in fallback.
        if not fb_entry or freq in (3, 5, 10) or freq % 10 == 0:
            db_retain(make_meta(freq, ts) + fact)
            results.append(f"DB stored milestone (freq={freq})")
        else:
            results.append(f"DB skipped duplicate; fallback updated (freq={freq})")
    except Exception as e:
        record_failure("db_retain", str(e))
        results.append(f"DB unavailable; fallback updated (freq={freq})")

    results.append(f"Fallback: upserted (freq={freq})")

    if freq >= 3:
        rule_key = stable_key(fact)
        rule_md = make_conservative_rule(fact, freq, ts)
        rule_entry = {"text": fact, "freq": freq, "ts": ts, "rule_md": rule_md, "key": rule_key, "scope": "same-context-only"}
        fb = load_fallback()
        fb["rules"][rule_key] = rule_entry
        save_fallback(fb)
        try:
            if freq in (3, 5, 10) or freq % 10 == 0:
                db_retain(make_rule_meta(freq, ts) + "[RULE] " + rule_md)
                results.append(f"DB rule stored milestone (freq={freq})")
        except Exception as e:
            record_failure("db_rule_retain", str(e))
            results.append("DB rule store skipped; fallback rule retained")
        try:
            upsert_agents_rule(rule_key, rule_md)
            results.append("Conservative rule upserted to AGENTS.md")
        except Exception as e:
            record_failure("agents_rule_write", str(e))
            results.append(f"AGENTS.md write failed: {e}")

    return {"content": [{"type": "text", "text": " | ".join(results)}]}


def handle_record_error(arguments):
    source = arguments.get("source", "unknown")
    error = arguments.get("error", "")
    root = arguments.get("root_cause", "unknown root cause")
    fix = arguments.get("fix", "fix not yet known")
    fact = f"System-level error from {source}: {error}. Root cause: {root}. Fix: {fix}."
    return handle_retain(fact)


def handle_call_tool(name, arguments):
    if name == "recall_hermes_memory":
        return handle_recall(arguments.get("query", ""))
    if name == "retain_hermes_memory":
        return handle_retain(arguments.get("fact", ""))
    if name == "record_hermes_error":
        return handle_record_error(arguments)
    if name == "maintain_hermes_memory":
        return {"content": [{"type": "text", "text": maintenance_report()}]}
    return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


def handle_list_prompts():
    return {"prompts": [{"name": "hermes-hindsight-system-booster", "description": "Inject prioritized Hindsight rules and observations."}]}


def handle_get_prompt(name):
    if name != "hermes-hindsight-system-booster":
        return {"messages": [], "isError": True}
    try:
        r = requests.get(f"{BASE_URL}/memories/list", params={"type": "observation"}, timeout=8)
        items = r.json().get("items", []) if r.status_code == 200 else []
    except Exception as e:
        record_failure("prompt_db_list", str(e))
        items = []

    fb = load_fallback()
    rules = []
    observations = []
    for item in items:
        text = item.get("text", "")
        freq, ts, body = parse_meta(text)
        body = strip_meta(strip_rule_meta(body))
        if is_rule(text):
            rules.append((freq, ts, body))
        else:
            observations.append((freq, ts, body))
    for entry in fb.get("rules", {}).values():
        rules.append((int(entry.get("freq", 1)), entry.get("ts", ""), entry.get("rule_md", entry.get("text", ""))))
    for entry in fb.get("facts", {}).values():
        observations.append((int(entry.get("freq", 1)), entry.get("ts", ""), entry.get("text", "")))

    rules.sort(key=lambda x: (x[0], x[1]), reverse=True)
    observations.sort(key=lambda x: (x[0], x[1]), reverse=True)
    rule_lines = dedupe_texts([f"  !! {body}" for _, _, body in rules], threshold=0.84)
    obs_lines = dedupe_texts([f"  - {body}" for _, _, body in observations], threshold=0.84)
    block = ""
    if rule_lines:
        block += "=== HARD RULES (same-context only unless explicitly universal) ===\n" + "\n".join(rule_lines[:12]) + "\n\n"
    if obs_lines:
        block += "=== Observations (deduped, ranked by frequency and recency) ===\n" + "\n".join(obs_lines[:20])
    if not block.strip():
        block = "None."
    system_instruction = (
        "You are connected to Hermes Hindsight Memory.\n"
        "Use HARD RULES only when the current context materially matches the learned pattern; do not overgeneralize.\n"
        "Fallback memories are included when DB data is unavailable.\n\n"
        f"{block}\n\nAlways follow these as behavioral memory."
    )
    return {"description": "Injected Hindsight Memory", "messages": [{"role": "user", "content": {"type": "text", "text": f"[SYSTEM RECALL INJECTION]\n{system_instruction}\n[END OF SYSTEM RECALL INJECTION]"}}]}


def main():
    log("Started Hindsight MCP Server (Stdio Bridge) v3.0")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            req_id = request.get("id")
            method = request.get("method")
            if req_id is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}, "prompts": {}}, "serverInfo": {"name": "hindsight-Hermes-mcp", "version": "3.0.0"}}
            elif method == "tools/list":
                result = handle_list_tools()
            elif method == "tools/call":
                params = request.get("params", {})
                result = handle_call_tool(params.get("name"), params.get("arguments", {}))
            elif method == "prompts/list":
                result = handle_list_prompts()
            elif method == "prompts/get":
                result = handle_get_prompt(request.get("params", {}).get("name"))
            else:
                result = {}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        except Exception as e:
            log(f"Error processing request: {e}")
            log(traceback.format_exc())


if __name__ == "__main__":
    main()

