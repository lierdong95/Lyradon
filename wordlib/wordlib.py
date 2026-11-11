# SPDX-License-Identifier: MIT
import asyncio
import json
import logging
import random
import sys
from pathlib import Path

import requests
import websockets

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "wordlib.json"
LOG_FILE = BASE_DIR / "wordlib.log"
WS_URL = "ws://127.0.0.1:3002"
WS_RETRY_SECONDS = 5
NAPCAT_HTTP = "http://127.0.0.1:3001"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
if sys.stdout is not None:
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
log = logging.getLogger("wordlib")


class Wordlib:
    def __init__(self):
        self.data = {}
        self._mtime = None
        self._last_index = {}

    def load(self, force=False):
        try:
            mtime = DATA_FILE.stat().st_mtime
        except OSError:
            log.error("wordlib.json 不存在: %s", DATA_FILE)
            return
        if not force and mtime == self._mtime:
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("rules"), dict):
                raise ValueError("顶层需为对象，且含 rules 对象（触发语 -> 回复数组）")
            rules = data.get("rules", {})
            groups = data.get("groups")
            if not isinstance(groups, list):
                raise ValueError("groups 需为数组")
            for phrase, replies in rules.items():
                if not isinstance(phrase, str) or not phrase:
                    raise ValueError("rules 的键(触发语)必须是非空字符串")
                if not isinstance(replies, list) or not replies:
                    raise ValueError(f"触发语 {phrase!r} 的回复数组为空")
            self.data = data
            global NAPCAT_HTTP, WS_URL
            NAPCAT_HTTP = data.get("napcat_http") or NAPCAT_HTTP
            WS_URL = data.get("ws_url") or WS_URL
            self._mtime = mtime
            self._last_index = {
                k: v for k, v in self._last_index.items() if k in rules
            }
            log.info("wordlib 已加载: %d 个词条, groups=%s", len(rules), groups)
        except Exception as e:
            self._mtime = mtime
            log.error("wordlib.json 读取/解析失败，继续用旧数据: %s", e)

    @staticmethod
    def extract(event):
        if event.get("post_type") != "message":
            return None
        if event.get("message_type") != "group":
            return None
        gid = event.get("group_id")
        sid = str(event.get("self_id") or "")
        uid = event.get("user_id")
        if uid is not None and str(uid) == sid:
            return None
        msg = event.get("message")
        texts = []
        at_bot = False
        if isinstance(msg, str):
            texts.append(msg)
        elif isinstance(msg, list):
            for seg in msg:
                if not isinstance(seg, dict):
                    continue
                t = seg.get("type")
                d = seg.get("data") or {}
                if t == "text":
                    texts.append(str(d.get("text", "")))
                elif t == "at" and str(d.get("qq", "")) == sid:
                    at_bot = True
        text = "".join(texts).strip()
        if not text:
            return None
        return {"group_id": gid, "text": text, "at_bot": at_bot}

    def decide(self, text):
        for p in self.data.get("llm_prefixes") or []:
            if text.startswith(p):
                return None
        for phrase, replies in (self.data.get("rules") or {}).items():
            if phrase in text:
                return phrase, replies
        return None

    def pick(self, phrase, replies):
        idx = random.randrange(len(replies))
        if len(replies) > 1 and phrase in self._last_index:
            while idx == self._last_index[phrase]:
                idx = random.randrange(len(replies))
        self._last_index[phrase] = idx
        return replies[idx]

    async def on_event(self, payload):
        events = payload if isinstance(payload, list) else [payload]
        for event in events:
            if not isinstance(event, dict):
                continue
            info = self.extract(event)
            if info is None:
                continue
            self.load()
            if info["at_bot"]:
                return
            if str(info["group_id"]) not in {str(g) for g in self.data.get("groups", [])}:
                return
            hit = self.decide(info["text"])
            if hit is None:
                return
            phrase, replies = hit
            reply = self.pick(phrase, replies)
            log.info("命中 %r <- [%s] %s, 群 %s", phrase, info["group_id"], info["text"][:40], info["group_id"])
            ok = await asyncio.to_thread(self.send_text, info["group_id"], reply)
            log.info("发送 %s -> %s", "ok" if ok else "fail", reply[:40])

    @staticmethod
    def send_text(group_id, text):
        try:
            resp = requests.post(
                NAPCAT_HTTP + "/send_group_msg",
                json={"group_id": group_id, "message": text},
                timeout=15,
            )
            data = resp.json()
            return isinstance(data, dict) and data.get("status") == "ok"
        except Exception as e:
            log.error("发送失败: %s", e)
            return False

    async def run(self):
        self.load(force=True)
        while True:
            try:
                async with websockets.connect(WS_URL) as ws:
                    log.info("WS 已连接: %s", WS_URL)
                    async for raw in ws:
                        try:
                            payload = json.loads(raw)
                        except Exception:
                            continue
                        await self.on_event(payload)
            except Exception as e:
                log.error("WS 连接断开/失败: %s，%ds 后重连", e, WS_RETRY_SECONDS)
            await asyncio.sleep(WS_RETRY_SECONDS)


def main():
    wordlib = Wordlib()
    try:
        asyncio.run(wordlib.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
