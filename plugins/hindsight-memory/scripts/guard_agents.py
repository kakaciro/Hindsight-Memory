from pathlib import Path
import time


AGENTS = Path.home() / ".codex" / "AGENTS.md"
BACKUP = AGENTS.with_name(AGENTS.name + ".bak")
LOG = Path.home() / "plugins" / "hindsight_agents_guard.log"


def log(message):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | {message}\n")


def main():
    AGENTS.parent.mkdir(parents=True, exist_ok=True)

    agents_ok = AGENTS.exists() and AGENTS.stat().st_size > 0
    backup_ok = BACKUP.exists() and BACKUP.stat().st_size > 0

    if not agents_ok and backup_ok:
        AGENTS.write_text(BACKUP.read_text(encoding="utf-8"), encoding="utf-8")
        log(f"restored AGENTS.md from backup; size={AGENTS.stat().st_size}")
        return

    if agents_ok and not backup_ok:
        BACKUP.write_text(AGENTS.read_text(encoding="utf-8"), encoding="utf-8")
        log(f"created backup from AGENTS.md; size={BACKUP.stat().st_size}")
        return

    if agents_ok and backup_ok:
        if AGENTS.stat().st_mtime > BACKUP.stat().st_mtime:
            BACKUP.write_text(AGENTS.read_text(encoding="utf-8"), encoding="utf-8")
            log(f"refreshed backup from newer AGENTS.md; size={BACKUP.stat().st_size}")
        else:
            log("ok")
        return

    log("missing AGENTS.md and backup; manual restore required")


if __name__ == "__main__":
    main()
