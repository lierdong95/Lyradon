# SPDX-License-Identifier: MIT
import argparse
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "persona-sync.log"

# All configurable paths are relative to this public project root.
PROJECT_ROOT = BASE_DIR.parent
CONFIG_FILE = BASE_DIR / "persona-sync.json"
PERSONA_FILE = PROJECT_ROOT / "persona.txt"
LANGBOT_DIR = PROJECT_ROOT / "langbot"
LANGBOT_START_PS1 = LANGBOT_DIR / "start_langbot.ps1"
LANGBOT_PID_FILE = LANGBOT_DIR / "langbot.pid"
LANGBOT_EXE = PROJECT_ROOT / "langbot-venv" / "Scripts" / "langbot.exe"
DB_PATH = LANGBOT_DIR / "data" / "langbot.db"
PIPELINE_UUID = ""
POLL_SECONDS = 2.0
STABLE_ROUNDS = 3
RESTART_COOLDOWN_SECONDS = 150
RESTART_LANGBOT = False
log = logging.getLogger("persona-sync")


def configure(path):
    global PERSONA_FILE, DB_PATH, PIPELINE_UUID, RESTART_LANGBOT
    global LANGBOT_START_PS1, LANGBOT_PID_FILE, LANGBOT_EXE
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if cfg.get("enabled") is not True:
        print("Persona sync is disabled; no database or process access.")
        return False
    def resolved(key, fallback):
        value = Path(cfg.get(key) or fallback)
        return (value if value.is_absolute() else PROJECT_ROOT / value).resolve()
    PERSONA_FILE = resolved("persona_file", "persona.txt")
    DB_PATH = resolved("database_file", "langbot/data/langbot.db")
    PIPELINE_UUID = str(cfg.get("pipeline_uuid") or "").strip()
    RESTART_LANGBOT = cfg.get("restart_langbot") is True
    LANGBOT_START_PS1 = resolved("langbot_start_script", "langbot/start_langbot.ps1")
    LANGBOT_PID_FILE = resolved("langbot_pid_file", "langbot/langbot.pid")
    LANGBOT_EXE = resolved("langbot_executable", "langbot-venv/Scripts/langbot.exe")
    if not PIPELINE_UUID or PIPELINE_UUID.startswith("YOUR_"):
        raise ValueError("Set the target pipeline_uuid before enabling this tool")
    if not PERSONA_FILE.is_file() or not DB_PATH.is_file():
        raise ValueError("The configured persona file and existing database are required")
    if RESTART_LANGBOT and (not LANGBOT_START_PS1.is_file() or not LANGBOT_EXE.is_file()):
        raise ValueError("Restart requires an existing launcher and executable")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()])
    return True


def connect_database():
    # mode=rw refuses to create a missing database.
    if not DB_PATH.is_file():
        raise FileNotFoundError("The configured database does not exist")
    return sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=rw", uri=True, timeout=10)


def read_persona() -> str | None:
    try:
        return PERSONA_FILE.read_text(encoding="utf-8-sig")
    except OSError as e:
        log.error("读取 persona.txt 失败: %s", e)
        return None


def db_persona() -> str | None:
    try:
        con = connect_database()
        try:
            cfg = con.execute(
                "select config from legacy_pipelines where uuid=?",
                (PIPELINE_UUID,),
            ).fetchone()
            if cfg is None:
                log.error("流水线 %s 不存在", PIPELINE_UUID)
                return None
            import json
            return json.loads(cfg[0])["ai"]["local-agent"]["prompt"][0]["content"]
        finally:
            con.close()
    except Exception as e:
        log.error("读取 DB persona 失败: %s", e)
        return None


def write_persona(text: str) -> bool:
    import json
    for attempt in range(8):
        try:
            con = connect_database()
            try:
                row = con.execute(
                    "select config from legacy_pipelines where uuid=?", (PIPELINE_UUID,)
                ).fetchone()
                cfg = json.loads(row[0])
                cfg["ai"]["local-agent"]["prompt"][0]["content"] = text
                con.execute(
                    "update legacy_pipelines set config=? where uuid=?",
                    (json.dumps(cfg, ensure_ascii=False), PIPELINE_UUID),
                )
                con.commit()
            finally:
                con.close()
            return True
        except sqlite3.OperationalError as e:
            log.warning("写库被锁(%d/8): %s", attempt + 1, e)
            time.sleep(2)
        except Exception as e:
            log.error("写库失败: %s", e)
            return False
    return False


def kill_langbot() -> bool:
    # Only the PID file explicitly configured by the operator is consulted.
    # Verify that the PID still belongs to the expected LangBot executable.
    if sys.platform != "win32" or not LANGBOT_PID_FILE.is_file():
        log.warning("Restart skipped: Windows and the configured PID file are required")
        return False
    try:
        pid = int(LANGBOT_PID_FILE.read_text(encoding="utf-8-sig").strip())
        if pid <= 0:
            return False
        script = ("Get-CimInstance Win32_Process -Filter 'ProcessId = " + str(pid) +
                  "' | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                                capture_output=True, text=True, timeout=15)
        details = json.loads(result.stdout or "null")
        if (result.returncode != 0 or not isinstance(details, dict) or
                details.get("ProcessId") != pid or not details.get("ExecutablePath") or
                Path(details["ExecutablePath"]).resolve() != LANGBOT_EXE.resolve()):
            log.warning("Restart skipped: PID ownership could not be verified")
            return False
        stopped = subprocess.run(["taskkill", "/f", "/t", "/pid", str(pid)],
                                 capture_output=True, timeout=20)
        return stopped.returncode == 0
    except Exception as exc:
        log.warning("Restart skipped: %s", type(exc).__name__)
        return False


def start_langbot() -> None:
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LANGBOT_START_PS1),
        ],
        cwd=str(LANGBOT_DIR),
        creationflags=flags,
    )


class PersonaSync:
    def __init__(self):
        self.last_stat = None
        self.last_restart = 0.0

    def watch_file(self) -> bool:
        try:
            st = PERSONA_FILE.stat()
        except OSError:
            return False
        key = (st.st_mtime, st.st_size)
        if key == self.last_stat:
            return False
        stable = 0
        for _ in range(STABLE_ROUNDS):
            time.sleep(POLL_SECONDS)
            try:
                st2 = PERSONA_FILE.stat()
            except OSError:
                return False
            if (st2.st_mtime, st2.st_size) == key:
                stable += 1
            else:
                key = (st2.st_mtime, st2.st_size)
                stable = 0
        self.last_stat = key
        return True

    def restart_langbot_now(self) -> None:
        now = time.time()
        if now - self.last_restart < RESTART_COOLDOWN_SECONDS:
            log.info("距上次重启不足 %ss，跳过自动重启", RESTART_COOLDOWN_SECONDS)
            return
        if kill_langbot():
            log.info("LangBot 已停止，准备重启使其生效...")
            time.sleep(5)
            start_langbot()
            self.last_restart = now
            log.info("已重新拉起 LangBot，新人格约 30~60 秒后生效")
            return
        log.warning("未验证并停止目标进程；跳过启动，请按需要手动重启 LangBot")

    def sync_once(self, allow_restart: bool) -> None:
        text = read_persona()
        if text is None:
            return
        current = db_persona()
        if current == text:
            return
        log.info("检测到 persona 变化，开始覆写 DB（%d 字符）...", len(text))
        if not write_persona(text):
            log.error("persona 写库失败，跳过重启")
            return
        if db_persona() != text:
            log.error("写库后校验不一致，跳过重启")
            return
        log.info("DB 已更新并校验一致")
        if RESTART_LANGBOT and allow_restart:
            self.restart_langbot_now()
        else:
            log.info("未自动重启 LangBot，改动将在下次 LangBot 重启后生效")

    def run(self):
        log.info("persona-sync 启动，监视 %s", PERSONA_FILE)
        time.sleep(5)
        self.sync_once(allow_restart=True)
        while True:
            try:
                if self.watch_file():
                    self.sync_once(allow_restart=True)
            except Exception as e:
                log.error("循环异常: %s", e)
            time.sleep(POLL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="Optional local prompt synchronization")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    args = parser.parse_args()
    if not args.config.is_file():
        print("Copy persona-sync.example.json to persona-sync.json and configure it first.")
        return
    if not configure(args.config):
        return
    ps = PersonaSync()
    try:
        ps.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
