# SPDX-License-Identifier: MIT
import asyncio
import base64
import json
import logging
import random
import re
import sys
from pathlib import Path

import requests
import websockets

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "radar.json"
LOG_FILE = BASE_DIR / "radar.log"
WS_RETRY_SECONDS = 5
FETCH_TIMEOUT = 20
NAPCAT_HTTP = "http://127.0.0.1:3001"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
if sys.stdout is not None:
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
log = logging.getLogger("radar")


class Radar:
    def __init__(self):
        self.data = {}
        self._mtime = None

    def load(self, force=False):
        try:
            mtime = DATA_FILE.stat().st_mtime
        except OSError:
            log.error("radar.json 不存在: %s", DATA_FILE)
            return
        if not force and mtime == self._mtime:
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("who"), list) or not isinstance(data.get("regions"), dict):
                raise ValueError("顶层需为对象，且含 who 数组与 regions 对象")
            if not data.get("who") or not data.get("regions"):
                raise ValueError("who 与 regions 不能为空")
            self.data = data
            global NAPCAT_HTTP
            NAPCAT_HTTP = data.get("napcat_http") or NAPCAT_HTTP
            self._mtime = mtime
            log.info("radar 已加载: 触发词=%s, 地区=%s", data["who"], list(data["regions"].keys()))
        except Exception as e:
            self._mtime = mtime
            log.error("radar.json 读取/解析失败，继续用旧数据: %s", e)

    def command_regex(self):
        who = "|".join(re.escape(w) for w in self.data.get("who", []))
        regions = "|".join(re.escape(r) for r in self.data.get("regions", {}))
        return re.compile(
            rf"^\s*(?:(?:{who})[,，、:：\s]*)?[,，、:：\s]*查询\s*({regions})(?:降水)?雷达(?:图|示意图)?\s*[。.！!？?]*\s*$"
        )

    @staticmethod
    def extract_text(event):
        if event.get("post_type") != "message":
            return None, None
        if event.get("message_type") != "group":
            return None, None
        gid = event.get("group_id")
        msg = event.get("message")
        texts = []
        if isinstance(msg, str):
            texts.append(msg)
        elif isinstance(msg, list):
            for seg in msg:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    texts.append(str((seg.get("data") or {}).get("text", "")))
        return gid, "".join(texts).strip()

    @staticmethod
    def latest_image_url(page_url):
        html = requests.get(page_url, timeout=FETCH_TIMEOUT, headers=HEADERS).text
        m = re.search(r'id=imgpath[^>]*\bsrc="([^"]+)"', html, re.S)
        if not m:
            m = re.search(r"(https://image\.nmc\.cn/product/[^\"\s?]+\.PNG)", html, re.I)
        if not m:
            raise RuntimeError("页面未找到雷达图地址")
        url = m.group(1).split("?")[0]
        return url

    @staticmethod
    def download(url):
        resp = requests.get(url, timeout=FETCH_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return resp.content

    @staticmethod
    def send_text(group_id, text):
        try:
            resp = requests.post(
                NAPCAT_HTTP + "/send_group_msg",
                json={"group_id": group_id, "message": text},
                timeout=20,
            )
            data = resp.json()
            return isinstance(data, dict) and data.get("status") == "ok"
        except Exception as e:
            log.error("发送文本失败: %s", e)
            return False

    @staticmethod
    def send_image(group_id, image_bytes):
        try:
            b64 = "base64://" + base64.b64encode(image_bytes).decode("ascii")
            msg = [{"type": "image", "data": {"file": b64}}]
            resp = requests.post(
                NAPCAT_HTTP + "/send_group_msg",
                json={"group_id": group_id, "message": msg},
                timeout=120,
            )
            data = resp.json()
            ok = isinstance(data, dict) and data.get("status") == "ok"
            log.info("发图 %s (%d bytes)", "ok" if ok else data, len(image_bytes))
            return ok
        except Exception as e:
            log.error("发送图片失败: %s", e)
            return False

    def pick(self, key):
        items = self.data.get(key) or []
        return random.choice(items) if items else ""

    async def handle(self, group_id, region):
        ack = self.pick("ack_phrases")
        ok = await asyncio.to_thread(self.send_text, group_id, ack)
        log.info("[%s] ack=%r sent=%s", region, ack[:20], ok)
        await asyncio.sleep(0.8)
        page = (self.data.get("regions") or {}).get(region)
        try:
            url = await asyncio.to_thread(self.latest_image_url, page)
            log.info("[%s] 最新雷达图: %s", region, url)
            image_bytes = await asyncio.to_thread(self.download, url)
            if not image_bytes:
                raise RuntimeError("图片内容为空")
            await asyncio.to_thread(self.send_image, group_id, image_bytes)
        except Exception as e:
            log.error("[%s] 拉取雷达图失败: %s", region, e)
            fail = self.pick("fail_phrases")
            await asyncio.to_thread(self.send_text, group_id, fail)

    async def on_event(self, payload):
        events = payload if isinstance(payload, list) else [payload]
        for event in events:
            if not isinstance(event, dict):
                continue
            gid, text = self.extract_text(event)
            if gid is None or not text:
                continue
            if str(gid) not in {str(g) for g in self.data.get("groups", [])}:
                continue
            m = self.command_regex().match(text)
            if not m:
                continue
            region = m.group(1)
            log.info("[群 %s] 收到雷达指令 %r -> %s", gid, text[:40], region)
            await self.handle(gid, region)

    async def run(self):
        self.load(force=True)
        ws_url = self.data.get("ws_url") or "ws://127.0.0.1:3002"
        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    log.info("WS 已连接: %s", ws_url)
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
    radar = Radar()
    try:
        asyncio.run(radar.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
