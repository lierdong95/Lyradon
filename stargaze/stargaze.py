# SPDX-License-Identifier: MIT
import asyncio
import json
import logging
import math
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import websockets

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "stargaze.json"
LOG_FILE = BASE_DIR / "stargaze.log"
WS_RETRY_SECONDS = 5
TIMEOUT = 20
NAPCAT_HTTP = "http://127.0.0.1:3001"
UTC8 = timezone(timedelta(hours=8))
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMER_URL = "http://www.7timer.info/bin/api.pl"
HEADERS = {"User-Agent": "QQBot-stargazer/1.0 (local hobby bot)"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
if sys.stdout is not None:
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
log = logging.getLogger("stargaze")

PROVINCES = [
    "黑龙江", "内蒙古", "新疆", "广西", "宁夏", "西藏", "河北", "山西", "辽宁", "吉林",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东",
    "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "北京", "天津", "上海",
    "重庆", "香港", "澳门", "台湾",
]
FEATURE_RANK = {
    "PPLC": 6, "PPLA": 6, "PPLA2": 5, "PPLA3": 4, "PPLA4": 3,
    "PPL": 2, "PPLS": 1,
}
SYNODIC = 29.53058867
NEW_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


class StargazeError(Exception):
    pass


def load_db_data():
    pass


class Stargaze:
    def __init__(self):
        self.data = {}
        self._mtime = None

    def load(self, force=False):
        try:
            mtime = DATA_FILE.stat().st_mtime
        except OSError:
            log.error("stargaze.json 不存在: %s", DATA_FILE)
            return
        if not force and mtime == self._mtime:
            return
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("who"), list):
                raise ValueError("顶层需为对象且含 who 数组")
            self.data = data
            global NAPCAT_HTTP
            NAPCAT_HTTP = data.get("napcat_http") or NAPCAT_HTTP
            self._mtime = mtime
            log.info("stargaze 已加载: 触发词=%s", data["who"])
        except Exception as e:
            self._mtime = mtime
            log.error("stargaze.json 读取/解析失败，继续用旧数据: %s", e)

    def command_regex(self):
        who = "|".join(re.escape(w) for w in self.data.get("who", []))
        return re.compile(rf"^\s*(?:(?:{who})[,，、:：\s]*)?观星[ \t]+(\S.{{0,39}}?)[。.！!？?]*$")

    @staticmethod
    def extract(event):
        if event.get("post_type") != "message" or event.get("message_type") != "group":
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
    def _province_of(place):
        for p in PROVINCES:
            if place.startswith(p):
                return p
        return None

    def _alias(self, place):
        table = self.data.get("places") or {}
        if not isinstance(table, dict):
            return None
        best = None
        best_len = 0
        for key, val in table.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            if key in place and len(key) > best_len:
                best = (key, val)
                best_len = len(key)
        return best

    def geocode(self, place):
        alias = self._alias(place)
        if alias:
            key, val = alias
            lat = float(val.get("lat"))
            lon = float(val.get("lon"))
            label = str(val.get("label") or key)
            return {"latitude": lat, "longitude": lon, "name": label, "admin1": ""}, label
        province = self._province_of(place)
        base = place
        if province:
            rest = place[len(province):].strip()
            if rest:
                base = rest.lstrip("省市自治区特别行政区")
        variants = [base]
        if not re.search(r"(市|县|区|旗|盟|州|岛)$", base):
            variants.append(base + "市")
        merged = {}
        for variant in variants:
            data = []
            for attempt in range(3):
                try:
                    resp = requests.get(
                        GEO_URL,
                        params={"name": variant, "count": 20, "language": "zh", "format": "json"},
                        headers=HEADERS,
                        timeout=TIMEOUT,
                    )
                    if resp.status_code == 429:
                        raise StargazeError("geocode-net")
                    resp.raise_for_status()
                    data = (resp.json() or {}).get("results") or []
                except Exception as e:
                    if attempt >= 2:
                        raise StargazeError("geocode-net") from e
                    time.sleep(1.2)
                    continue
                if not data and attempt < 2:
                    time.sleep(1.2)
                    continue
                break
            for item in data:
                merged[str(item.get("id"))] = item
            time.sleep(0.4)
        items = list(merged.values())
        if province:
            items = [it for it in items if str(it.get("admin1") or "").startswith(province)]
        if not items:
            raise StargazeError("geocode-none")
        items.sort(
            key=lambda it: (
                FEATURE_RANK.get(str(it.get("feature_code")), 0),
                it.get("population") or 0,
            ),
            reverse=True,
        )
        best = items[0]
        name = str(best.get("name") or base)
        admin1 = str(best.get("admin1") or "")
        if admin1 and not name.startswith(admin1):
            label = f"{name}·{admin1}"
        else:
            label = name
        return best, label

    @staticmethod
    def astro_point(lat, lon):
        params = {"lon": round(float(lon), 2), "lat": round(float(lat), 2), "product": "astro", "output": "json"}
        try:
            resp = requests.get(TIMER_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise StargazeError("astro-net") from e
        init_s = str(data.get("init") or "")
        try:
            init_utc = datetime.strptime(init_s, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        except ValueError:
            raise StargazeError("astro-init") from None
        series = data.get("dataseries") or []
        if not series:
            raise StargazeError("astro-empty")
        now = datetime.now(timezone.utc)
        desired_local = (now + timedelta(hours=8)).replace(hour=21, minute=0, second=0, microsecond=0) - timedelta(hours=8)
        best = None
        best_d = None
        for tp in series:
            try:
                p = init_utc + timedelta(hours=int(tp.get("timepoint", 0)))
            except (TypeError, ValueError):
                continue
            if p < now - timedelta(hours=2):
                continue
            if p > desired_local + timedelta(hours=9):
                continue
            local_h = (p + timedelta(hours=8)).hour
            d = min((local_h - 21) % 24, (21 - local_h) % 24)
            key = (d, abs((p - desired_local).total_seconds()))
            if best_d is None or key < best_d:
                best_d = key
                best = tp
        if best is None:
            best = series[-1]
        return init_utc, best

    @staticmethod
    def moon():
        now = datetime.now(timezone.utc)
        days = (now - NEW_MOON_EPOCH).total_seconds() / 86400.0
        age = days % SYNODIC
        illum = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2.0
        table = [
            (0.0, 1.2, "新月"), (1.2, 6.2, "娥眉月"), (6.2, 8.6, "上弦月"),
            (8.6, 13.2, "盈凸月"), (13.2, 16.3, "满月"), (16.3, 21.3, "亏凸月"),
            (21.3, 23.6, "下弦月"), (23.6, 28.3, "残月"),
        ]
        name = "残月"
        for lo, hi, nm in table:
            if lo <= age < hi:
                name = nm
                break
        return name, round(illum * 100)

    @staticmethod
    def grade(idx):
        if idx >= 80:
            return "极佳"
        if idx >= 60:
            return "良好"
        if idx >= 40:
            return "一般"
        if idx >= 20:
            return "较差"
        return "不适合"

    def evaluate(self, lat, lon):
        _, point = self.astro_point(lat, lon)
        okta = int(point.get("cloudcover", 9))
        seeing = int(point.get("seeing", 4))
        transp = int(point.get("transparency", 4))
        prec = str(point.get("prec_type") or "")
        cloud_score = (9 - okta) / 8.0
        seeing_score = (8 - seeing) / 7.0
        trans_score = (8 - transp) / 7.0
        raw = (cloud_score * 0.55 + trans_score * 0.25 + seeing_score * 0.20) * 100.0
        if prec in ("rain", "snow"):
            raw *= 0.12
        elif okta >= 7 and prec == "none":
            raw *= 0.45
        moon_name, moon_ill = self.moon()
        idx = raw * (1.0 - 0.15 * (moon_ill / 100.0))
        idx = max(0, min(100, int(round(idx))))
        grade = self.grade(idx)
        notes = []
        if okta <= 2:
            notes.append("云量很低，天空通透度好。")
        elif okta <= 5:
            notes.append("云量不算多，部分时段可能受薄云影响。")
        else:
            notes.append("云量偏多，今晚得看运气。")
        if seeing >= 6:
            notes.append("视宁度一般，高倍看行星细节会受限。")
        elif seeing <= 2:
            notes.append("视宁度很好，适合高倍观测。")
        if moon_ill >= 60:
            notes.append(f"月光较亮（{moon_ill}%），深空目标会受明显影响。")
        elif moon_ill >= 35:
            notes.append(f"月相{moon_name}，月光有一定影响。")
        return {
            "okta": okta, "seeing": seeing, "transp": transp,
            "idx": idx, "grade": grade,
            "moon_name": moon_name, "moon_ill": moon_ill,
            "notes": notes,
        }

    def pick(self, key):
        items = self.data.get(key) or []
        return random.choice(items) if items else ""

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

    async def handle(self, group_id, place):
        ack = self.pick("ack_phrases") or "正在查询观星条件。"
        await asyncio.to_thread(self.send_text, group_id, ack)
        log.info("[观星 %s] 已发确认语", place[:20])
        await asyncio.sleep(1.0)
        try:
            best, label = await asyncio.to_thread(self.geocode, place)
            lat, lon = best["latitude"], best["longitude"]
            log.info("[观星 %s] 定位 %s %.4f,%.4f", place[:20], label, lat, lon)
            result = await asyncio.to_thread(self.evaluate, lat, lon)
        except StargazeError as e:
            log.error("[观星 %s] 数据获取失败: %s", place[:20], e)
            if str(e) == "geocode-none":
                hint = f"没找到「{place[:30]}」的位置，试试更完整的地名写法，例如：观星 云南丽江 / 观星 大理市"
                await asyncio.to_thread(self.send_text, group_id, hint)
            else:
                fail = self.pick("fail_phrases") or "没查到，稍后再试~"
                await asyncio.to_thread(self.send_text, group_id, fail)
            return
        lines = [
            f"观星助手 · {label}",
            f"观星适宜指数：{result['idx']}% ｜ {result['grade']}",
            f"云量 {result['okta']}/9 · 视宁度 {result['seeing']}/8 · 透明度 {result['transp']}/8 · 月相 {result['moon_name']}（照亮 {result['moon_ill']}%）",
            " ".join(result["notes"]),
        ]
        text = "\n".join(lines)
        ok = await asyncio.to_thread(self.send_text, group_id, text)
        log.info("[观星 %s] 结果已发 sent=%s idx=%s", label, ok, result["idx"])

    async def on_event(self, payload):
        events = payload if isinstance(payload, list) else [payload]
        for event in events:
            if not isinstance(event, dict):
                continue
            gid, text = self.extract(event)
            if gid is None or not text:
                continue
            if str(gid) not in {str(g) for g in self.data.get("groups", [])}:
                continue
            m = self.command_regex().match(text)
            if not m:
                continue
            place = m.group(1).strip()
            if not place:
                continue
            log.info("[群 %s] 观星指令 %r -> %s", gid, text[:40], place[:30])
            await self.handle(gid, place)

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
    sg = Stargaze()
    try:
        asyncio.run(sg.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
