import json
import subprocess
import sys
import time
from pathlib import Path

import requests


ROOT = Path.home()
PLUGIN_ROOT = ROOT / "plugins"
CODEX = ROOT / ".codex"
OUT = PLUGIN_ROOT / "hindsight_enterprise_health.json"
LOG = PLUGIN_ROOT / "hindsight_enterprise_health.log"


def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "code": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except Exception as e:
        return {"ok": False, "code": None, "stdout": "", "stderr": str(e)}


def file_state(path):
    p = Path(path)
    return {
        "path": str(p),
        "exists": p.exists(),
        "size": p.stat().st_size if p.exists() else 0,
        "mtime": p.stat().st_mtime if p.exists() else None,
    }


def json_valid(path):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {"valid": False, "error": "missing_or_empty"}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return {"valid": True, "facts": len(data.get("facts", {})), "rules": len(data.get("rules", {})), "failures": len(data.get("failures", []))}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def redacted_env():
    info = run(["docker", "inspect", "hindsight", "--format", "{{range .Config.Env}}{{println .}}{{end}}"], timeout=20)
    env = {}
    if info["ok"]:
        for line in info["stdout"].splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if "KEY" in k or "TOKEN" in k or "SECRET" in k:
                v = "<redacted>"
            if k.startswith("HINDSIGHT_"):
                env[k] = v
    return {"ok": info["ok"], "env": env, "error": info["stderr"] if not info["ok"] else ""}


def api_banks():
    try:
        r = requests.get("http://localhost:8888/v1/default/banks", timeout=10)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "banks": []}
        banks = r.json().get("banks", [])
        return {"ok": True, "status": 200, "banks": [{"bank_id": b.get("bank_id"), "fact_count": b.get("fact_count"), "last_document_at": b.get("last_document_at")} for b in banks]}
    except Exception as e:
        return {"ok": False, "status": None, "error": str(e), "banks": []}


def task_info(name):
    result = run(["schtasks.exe", "/Query", "/TN", name, "/V", "/FO", "LIST"], timeout=20)
    return {"name": name, "ok": result["ok"], "raw": result["stdout"][-2000:], "error": result["stderr"]}


def main():
    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "docker": run(["docker", "ps", "--filter", "name=hindsight", "--format", "{{.Status}}"], timeout=20),
        "hindsight_env": redacted_env(),
        "api": api_banks(),
        "files": {
            "agents": file_state(CODEX / "AGENTS.md"),
            "agents_backup": file_state(CODEX / "AGENTS.md.bak"),
            "hermes_agents": file_state(CODEX / "HERMES_AGENTS.md"),
            "codex_fallback": {**file_state(PLUGIN_ROOT / "hindsight_fallback.json"), **json_valid(PLUGIN_ROOT / "hindsight_fallback.json")},
            "hermes_fallback": {**file_state(PLUGIN_ROOT / "hermes_hindsight_fallback.json"), **json_valid(PLUGIN_ROOT / "hermes_hindsight_fallback.json")},
        },
        "tasks": [
            task_info("CodexAgentsGuard"),
            task_info("CodexHindsightMaintenance"),
            task_info("HermesHindsightMaintenance"),
        ],
    }
    critical = []
    if not report["api"]["ok"]:
        critical.append("hindsight_api_unavailable")
    banks = {b["bank_id"] for b in report["api"].get("banks", [])}
    for bank in ("codex", "hermes"):
        if bank not in banks:
            critical.append(f"missing_bank_{bank}")
    if not report["files"]["agents"]["exists"] or report["files"]["agents"]["size"] == 0:
        critical.append("agents_missing_or_empty")
    if not report["files"]["agents_backup"]["exists"] or report["files"]["agents_backup"]["size"] == 0:
        critical.append("agents_backup_missing_or_empty")
    for name, state in (("codex_fallback", report["files"]["codex_fallback"]), ("hermes_fallback", report["files"]["hermes_fallback"])):
        if not state.get("valid"):
            critical.append(f"{name}_invalid")
    for task in report["tasks"]:
        if not task["ok"]:
            critical.append(f"task_missing_{task['name']}")
    report["status"] = "ok" if not critical else "degraded"
    report["critical"] = critical

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{report['ts']} | status={report['status']} | critical={','.join(critical) if critical else 'none'}\n")
    print(json.dumps({"status": report["status"], "critical": critical, "output": str(OUT)}, ensure_ascii=False))
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
