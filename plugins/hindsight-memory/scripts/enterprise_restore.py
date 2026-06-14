import json
import os
import sys
import time
import zipfile
import shutil
from pathlib import Path


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


def main():
    if not BACKUP_DIR.exists():
        print("No backups found.")
        return 1
        
    backups = list(BACKUP_DIR.glob("hindsight_backup_*.zip"))
    if not backups:
        print("No backup zips found.")
        return 1
        
    latest = max(backups, key=lambda p: p.stat().st_mtime)
    print(f"Restoring from {latest.name}...")
    
    targets = {
        "AGENTS.md": CODEX / "AGENTS.md",
        "AGENTS.md.bak": CODEX / "AGENTS.md.bak",
        "HERMES_AGENTS.md": CODEX / "HERMES_AGENTS.md",
        "hindsight_fallback.json": PLUGIN_ROOT / "hindsight_fallback.json",
        "hermes_hindsight_fallback.json": PLUGIN_ROOT / "hermes_hindsight_fallback.json",
    }
    
    restored = []
    try:
        with zipfile.ZipFile(latest, "r") as zf:
            for name in zf.namelist():
                if name in targets:
                    dest = targets[name]
                    # backup existing if present
                    if dest.exists():
                        shutil.copy2(dest, dest.with_suffix(dest.suffix + ".pre-restore"))
                    
                    with dest.open("wb") as f_out, zf.open(name) as f_in:
                        shutil.copyfileobj(f_in, f_out)
                    restored.append(name)
                    
        log_audit("restore", "ok", f"source={latest.name} files={len(restored)}")
        return 0
    except Exception as e:
        log_audit("restore", "failed", f"source={latest.name} error={str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
