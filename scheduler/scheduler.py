# SPDX-License-Identifier: MIT
import asyncio
import datetime as dt
import json
import logging
import random
import re
import sys
import time
from pathlib import Path

import requests
from croniter import croniter

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "schedule.json"
LOG_FILE = BASE_DIR / "scheduler.log"
CONFIG_RELOAD_SECONDS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("scheduler")

_WEEKDAY_CN = {
    "周日": 0, "星期天": 0, "星期日": 0, "周天": 0, "礼拜天": 0, "礼拜日": 0,
    "周一": 1, "星期一": 1, "礼拜一": 1,
    "周二": 2, "星期二": 2, "礼拜二": 2,
    "周三": 3, "星期三": 3, "礼拜三": 3,
    "周四": 4, "星期四": 4, "礼拜四": 4,
    "周五": 5, "星期五": 5, "礼拜五": 5,
    "周六": 6, "星期六": 6, "礼拜六": 6,
}


def _dow_num(token):
    token = token.strip()
    if not token:
        return None
    if token in _WEEKDAY_CN:
        return _WEEKDAY_CN[token]
    if token.isdigit():
        v = int(token)
        return 7 if v == 7 else v
    return None


def parse_days(days):
    """把用户友好的 days 写法转成 cron 的第 5 段(DOW)。"""
    if days is None:
        return "*"
    s = str(days).strip()
    if s in ("", "*", "每天"):
        return "*"
    if s == "工作日":
        return "1-5"
    if s == "周末":
        return "0,6"
    if re.fullmatch(r"[0-7,\-*/]+", s):
        return s
    nums = []
    for part in re.split(r"[,，、\s/]+", s):
        n = _dow_num(part)
        if n is None:
            raise ValueError(f"[days] 无法识别的星期写法: {part!r}（可用：每天/工作日/周末/周一…周日）")
        nums.append(n)
    nums = sorted(set(nums))
    return ",".join(str(n) for n in nums)


def cron_expr(entry):
    """条目时间规则 → 标准 5 段 cron。支持 'cron' 或 'at' + 'days'。"""
    name = entry.get("name", "?")
    if entry.get("cron"):
        expr = str(entry["cron"]).strip()
    elif entry.get("at"):
        try:
            hh, mm = str(entry["at"]).split(":")
            hh, mm = int(hh), int(mm)
        except Exception:
            log.error("[%s] 'at' 格式错误: %r（应为 HH:MM，如 09:00）", name, entry.get("at"))
            return None
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            log.error("[%s] 'at' 超出范围: %r", name, entry.get("at"))
            return None
        try:
            dow = parse_days(entry.get("days"))
        except ValueError as e:
            log.error("[%s] %s", name, e)
            return None
        expr = f"{mm} {hh} * * {dow}"
    else:
        log.error("[%s] 缺少时间规则：请给 'cron' 或 'at'（如 \"at\": \"09:00\"）", name)
        return None
    try:
        croniter(expr, dt.datetime.now())
    except Exception as e:
        log.error("[%s] 无效的 cron 表达式 %r: %s", name, expr, e)
        return None
    return expr



def onebot_call(cfg, action, params, timeout=15):
    url = cfg["napcat_url"].rstrip("/") + "/" + action
    headers = {"Content-Type": "application/json"}
    token = cfg.get("token")
    if token:
        headers["Authorization"] = "Bearer " + token
    resp = requests.post(url, json=params, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def group_ids(cfg):
    data = onebot_call(cfg, "get_group_list", {})
    groups = data.get("data") or []
    return {int(g["group_id"]) for g in groups}


def handle_text(cfg, entry):
    group_id = int(entry["group_id"])
    file_path = BASE_DIR / entry["file"]
    if not file_path.exists():
        log.error("[%s] file not found: %s", entry.get("name", "?"), file_path)
        return
    try:
        members = group_ids(cfg)
    except Exception as e:
        log.error("[%s] get_group_list failed, skip this run: %s", entry.get("name", "?"), e)
        return
    if group_id not in members:
        log.warning("[%s] bot not in group %s, skip", entry.get("name", "?"), group_id)
        return
    content = file_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        log.warning("[%s] empty content in %s, skip", entry.get("name", "?"), file_path)
        return
    result = onebot_call(cfg, "send_group_msg", {"group_id": group_id, "message": content})
    ok = (result.get("status") == "ok") if isinstance(result, dict) else False
    log.info("[%s] sent %d chars to group %s -> %s", entry.get("name", "?"), len(content), group_id, "ok" if ok else result)


ACTIONS = {
    "text": handle_text,
}


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data


def next_fire(expr, after):
    return croniter(expr, after).get_next(dt.datetime)


LAST_FIRE = {}


async def run_tick(cfg):
    now = dt.datetime.now()
    for entry in cfg.get("schedule", []):
        if not entry.get("enabled", True):
            continue
        action = entry.get("type", "text")
        handler = ACTIONS.get(action)
        if handler is None:
            log.error("unknown type %r in entry %r", action, entry.get("name", "?"))
            continue
        expr = cron_expr(entry)
        if expr is None:
            continue
        name = str(entry.get("name") or "?")
        if name not in LAST_FIRE:
            try:
                nxt = next_fire(expr, now)
            except Exception as e:
                log.error("bad cron %r in %r: %s", expr, name, e)
                continue
            LAST_FIRE[name] = now
            log.info("[%s] armed, next fire ~%s (%s)", name, nxt.strftime("%Y-%m-%d %H:%M:%S"), expr)
            continue
        try:
            nxt = next_fire(expr, LAST_FIRE[name])
        except Exception as e:
            log.error("bad cron %r in %r: %s", expr, name, e)
            continue
        if nxt <= now:
            if now - nxt > dt.timedelta(minutes=2):
                log.warning("[%s] catching up (was due at %s)", name, nxt.strftime("%Y-%m-%d %H:%M:%S"))
            log.info("[%s] firing at %s", name, now.strftime("%Y-%m-%d %H:%M:%S"))
            try:
                handler(cfg, entry)
            except Exception as e:
                log.error("[%s] handler error: %s", name, e)
            LAST_FIRE[name] = now


def cfg_sig(cfg):
    return json.dumps(cfg, sort_keys=True, ensure_ascii=False)


def main():
    log.info("scheduler started, config=%s", CONFIG_FILE)
    cfg = load_config()
    sig = cfg_sig(cfg)
    last_reload = time.monotonic()
    while True:
        now = dt.datetime.now()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(run_tick(cfg))
        loop.close()
        if time.monotonic() - last_reload >= CONFIG_RELOAD_SECONDS:
            try:
                new_cfg = load_config()
                new_sig = cfg_sig(new_cfg)
                if new_sig != sig:
                    cfg, sig = new_cfg, new_sig
                    log.info("config reloaded and changed")
                last_reload = time.monotonic()
            except Exception as e:
                log.error("config reload failed: %s", e)
        sleep_s = 60 - now.second + (1 - now.microsecond / 1_000_000)
        time.sleep(max(sleep_s, 0.5))


if __name__ == "__main__":
    main()
