import json
import os
import sys
import time
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
FALLBACK = Path(os.environ.get("HINDSIGHT_FALLBACK_PATH") or ROOT.parent / "hermes_hindsight_fallback.json")
LOG = ROOT.parent / "hermes_hindsight_maintenance.log"
AGENTS = Path(os.environ.get("AGENTS_MD_PATH") or Path.home() / ".codex" / "HERMES_AGENTS.md")
BASE = os.environ.get("HINDSIGHT_BASE_ROOT", "http://localhost:8888/v1/default/banks")
BANKS = [b.strip() for b in os.environ.get("HINDSIGHT_MAINTENANCE_BANKS", os.environ.get("HINDSIGHT_BANK_ID", "hermes")).split(",") if b.strip()]


def load_json(path):
    if not path.exists():
        return {"version": 2, "facts": {}, "rules": {}, "failures": [], "last_maintenance": None}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        corrupt = path.with_suffix(path.suffix + f".corrupt.{int(time.time())}")
        path.replace(corrupt)
        return {"version": 2, "facts": {}, "rules": {}, "failures": [{"source": "maintenance", "detail": f"fallback corrupt moved to {corrupt}: {e}", "ts": time.time()}], "last_maintenance": None}
    if isinstance(data.get("rules"), list):
        data["rules"] = {str(i): r for i, r in enumerate(data["rules"]) if isinstance(r, dict)}
    data.setdefault("facts", {})
    data.setdefault("rules", {})
    data.setdefault("failures", [])
    return data


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def health():
    rows = []
    try:
        r = requests.get(f"{BASE}", timeout=8)
        rows.append(f"banks_api={r.status_code}")
        if r.status_code == 200:
            banks = r.json().get("banks", [])
            rows.append("banks=" + ",".join(f"{b.get('bank_id')}:{b.get('fact_count')}" for b in banks))
    except Exception as e:
        rows.append(f"banks_api_error={e}")
    for bank in BANKS:
        try:
            r = requests.get(f"{BASE}/{bank}/memories/list", timeout=8)
            rows.append(f"{bank}_list={r.status_code}")
        except Exception as e:
            rows.append(f"{bank}_list_error={e}")
    return " | ".join(rows)


def canonical_rule(line):
    text = line.strip().lower()
    text = text.replace("- ", "", 1)
    if "(evolved from" in text:
        text = text.split("(evolved from", 1)[0]
    return " ".join(text.split()).strip(" .")


def dedupe_agents_rules():
    if not AGENTS.exists():
        return "agents=missing"
    lines = AGENTS.read_text(encoding="utf-8").splitlines()
    rule_indices = []
    seen = {}
    for idx, line in enumerate(lines):
        if line.startswith("- ") and "evolved from" in line:
            key = canonical_rule(line)
            freq = 0
            if "evolved from" in line:
                try:
                    freq = int(line.split("evolved from", 1)[1].split("repeated", 1)[0].strip())
                except Exception:
                    freq = 0
            rule_indices.append(idx)
            if key not in seen or freq > seen[key][0]:
                seen[key] = (freq, idx)
    keep = {idx for _, idx in seen.values()}
    out = [line for idx, line in enumerate(lines) if idx not in rule_indices or idx in keep]
    removed = len(rule_indices) - len(keep)
    if removed:
        AGENTS.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return f"agents_rules={len(keep)} removed={removed}"


def main():
    data = load_json(FALLBACK)
    # Keep only highest-frequency rule per exact text.
    by_text = {}
    for rule in data.get("rules", {}).values():
        text = rule.get("text")
        if not text:
            continue
        if text not in by_text or int(rule.get("freq", 1)) > int(by_text[text].get("freq", 1)):
            by_text[text] = rule
    data["rules"] = {str(abs(hash(k))): v for k, v in by_text.items()}
    data["last_maintenance"] = time.time()
    save_json(FALLBACK, data)
    agents_report = dedupe_agents_rules()
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | fallback facts={len(data['facts'])} rules={len(data['rules'])} failures={len(data.get('failures', []))} | {agents_report} | {health()}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


if __name__ == "__main__":
    main()
