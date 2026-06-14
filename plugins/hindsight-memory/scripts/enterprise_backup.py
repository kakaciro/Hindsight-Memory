import json
import os
import sys
import time
import zipfile
import hashlib
from pathlib import Path

import requests


ROOT = Path.home()
PLUGIN_ROOT = ROOT / "plugins"
CODEX = ROOT / ".codex"
BACKUP_DIR = PLUGIN_ROOT / "hindsight_backups"
LOG = PLUGIN_ROOT / "hindsight_enterprise_audit.log"


def log_audit(action, status, details):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{ts} | action={action} | status={status} | {details}\n")
    print(f"{ts} | action={action} | status={status} | {details}")


def hash_file(path):
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()


def get_api_banks():
    try:
        r = requests.get("http://localhost:8888/v1/default/banks", timeout=10)
        if r.status_code == 200:
            return r.json().get("banks", [])
    except Exception:
        pass
    return []


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    zip_path = BACKUP_DIR / f"hindsight_backup_{ts}.zip"

    targets = [
        {"name": "AGENTS.md", "path": CODEX / "AGENTS.md"},
        {"name": "AGENTS.md.bak", "path": CODEX / "AGENTS.md.bak"},
        {"name": "HERMES_AGENTS.md", "path": CODEX / "HERMES_AGENTS.md"},
        {"name": "hindsight_fallback.json", "path": PLUGIN_ROOT / "hindsight_fallback.json"},
        {"name": "hermes_hindsight_fallback.json", "path": PLUGIN_ROOT / "hermes_hindsight_fallback.json"},
    ]

    manifest = {
        "timestamp": ts,
        "files": {},
        "api_banks": get_api_banks(),
    }

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for target in targets:
                path = target["path"]
                if path.exists():
                    zf.write(path, arcname=target["name"])
                    manifest["files"][target["name"]] = {
                        "size": path.stat().st_size,
                        "sha256": hash_file(path)
                    }
            
            manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
            zf.writestr("manifest.json", manifest_json)
            
        log_audit("backup", "ok", f"file={zip_path.name} files={len(manifest['files'])}")
        return 0
    except Exception as e:
        log_audit("backup", "failed", f"error={str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
