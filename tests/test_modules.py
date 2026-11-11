# SPDX-License-Identifier: MIT
"""Offline behavior checks. Run from the repository root:

    python -B -m unittest discover -s tests -v

Install the module dependencies listed in tests/requirements.txt first.
All module imports use temporary copies. HTTP and WebSocket access are blocked;
individual tests replace responses or send methods with mocks.
"""
import sys

sys.dont_write_bytecode = True

import asyncio
import datetime as dt
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_GROUP = 123456789


def group_event(text, *, at_bot=False):
    message = text
    if at_bot:
        message = [
            {"type": "at", "data": {"qq": "10001"}},
            {"type": "text", "data": {"text": text}},
        ]
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": EXAMPLE_GROUP,
        "self_id": 10001,
        "user_id": 10002,
        "message": message,
    }


class OfflineModuleCase(unittest.TestCase):
    module_name = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="qqbot-module-test-")
        self.addCleanup(temporary.cleanup)
        self.module_dir = Path(temporary.name)
        source_dir = REPO_ROOT / self.module_name
        source_path = self.module_dir / (self.module_name + ".py")
        shutil.copyfile(source_dir / source_path.name, source_path)
        config_name = "schedule" if self.module_name == "scheduler" else self.module_name
        self.config_path = self.module_dir / (config_name + ".json")
        shutil.copyfile(source_dir / (config_name + ".example.json"), self.config_path)
        if (source_dir / "msg").is_dir():
            shutil.copytree(source_dir / "msg", self.module_dir / "msg")
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))

        self.http_blocker = self.enterContext(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Real HTTP access is forbidden in offline tests"),
        ))
        self.websocket_blocker = self.enterContext(patch(
            "websockets.connect",
            side_effect=AssertionError("Real WebSocket access is forbidden in offline tests"),
        ))
        spec = importlib.util.spec_from_file_location(
            "offline_" + self.module_name, source_path
        )
        self.module = importlib.util.module_from_spec(spec)
        with (
            patch("logging.FileHandler", return_value=logging.NullHandler()),
            patch("logging.basicConfig"),
            patch("logging.Logger.addHandler"),
        ):
            spec.loader.exec_module(self.module)
        self.module.log = MagicMock()
        # Even accidentally swallowed connection errors fail the test afterward.
        self.addCleanup(self.http_blocker.assert_not_called)
        self.addCleanup(self.websocket_blocker.assert_not_called)


class RadarTests(OfflineModuleCase):
    module_name = "radar"

    def setUp(self):
        super().setUp()
        self.bot = self.module.Radar()
        self.bot.load(force=True)

    def test_commands_accept_supported_regions_and_optional_prefix(self):
        pattern = self.bot.command_regex()
        cases = {
            "查询全国雷达图": "全国",
            "小Q 查询华东降水雷达图": "华东",
            "小Q，查询华北雷达示意图！": "华北",
        }
        for command, region in cases.items():
            with self.subTest(command=command):
                match = pattern.fullmatch(command)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), region)
        for command in ("查询不存在地区雷达图", "这是查询全国雷达图的说明", "早上好"):
            with self.subTest(command=command):
                self.assertIsNone(pattern.fullmatch(command))

    def test_image_url_from_imgpath_removes_query(self):
        response = MagicMock()
        response.text = '<img id=imgpath src="https://example.invalid/radar.png?v=2">'
        with patch.object(self.module.requests, "get", return_value=response) as fetch:
            result = self.bot.latest_image_url("https://example.invalid/page")
        self.assertEqual(result, "https://example.invalid/radar.png")
        fetch.assert_called_once()

    def test_image_url_falls_back_to_product_png(self):
        response = MagicMock()
        response.text = 'data-url="https://image.nmc.cn/product/test-radar.PNG"'
        with patch.object(self.module.requests, "get", return_value=response):
            result = self.bot.latest_image_url("https://example.invalid/page")
        self.assertEqual(result, "https://image.nmc.cn/product/test-radar.PNG")

    def test_image_url_reports_missing_image(self):
        response = MagicMock(text="<html>No radar image</html>")
        with patch.object(self.module.requests, "get", return_value=response):
            with self.assertRaises(RuntimeError):
                self.bot.latest_image_url("https://example.invalid/page")

    def test_empty_groups_do_not_handle_messages(self):
        with patch.object(self.bot, "handle", new_callable=AsyncMock) as handle:
            asyncio.run(self.bot.on_event(group_event("查询全国雷达图")))
        handle.assert_not_awaited()


class StargazeTests(OfflineModuleCase):
    module_name = "stargaze"

    def setUp(self):
        super().setUp()
        self.bot = self.module.Stargaze()
        self.bot.load(force=True)

    def evaluate(self, *, cloud=1, seeing=1, transparency=1, precipitation="none", moon=0):
        point = {
            "cloudcover": cloud,
            "seeing": seeing,
            "transparency": transparency,
            "prec_type": precipitation,
        }
        with (
            patch.object(self.bot, "astro_point", return_value=(None, point)) as weather,
            patch.object(self.bot, "moon", return_value=("合成月相", moon)),
        ):
            result = self.bot.evaluate(0.0, 0.0)
        weather.assert_called_once_with(0.0, 0.0)
        return result

    def test_clear_dark_sky_scores_higher_than_overcast_sky(self):
        clear = self.evaluate()
        overcast = self.evaluate(cloud=9, seeing=8, transparency=8)
        self.assertEqual(clear["idx"], 100)
        self.assertEqual(clear["grade"], "极佳")
        self.assertEqual(overcast["idx"], 0)
        self.assertEqual(overcast["grade"], "不适合")

    def test_rain_reduces_observing_score(self):
        dry = self.evaluate()
        rainy = self.evaluate(precipitation="rain")
        self.assertLess(rainy["idx"], dry["idx"])
        self.assertGreaterEqual(rainy["idx"], 0)
        self.assertLessEqual(rainy["idx"], 100)

    def test_bright_moon_reduces_score_and_adds_note(self):
        dark = self.evaluate(moon=0)
        bright = self.evaluate(moon=100)
        self.assertLess(bright["idx"], dark["idx"])
        self.assertEqual(bright["moon_ill"], 100)
        self.assertTrue(any("月光较亮" in note for note in bright["notes"]))


class SchedulerTests(OfflineModuleCase):
    module_name = "scheduler"

    def test_disabled_template_tasks_never_send(self):
        config = self.module.load_config()
        self.assertTrue(config["schedule"])
        for entry in config["schedule"]:
            self.assertIs(entry["enabled"], False)
            self.module.LAST_FIRE[entry["name"]] = dt.datetime.now() - dt.timedelta(days=2)
        handler = MagicMock()
        with (
            patch.dict(self.module.ACTIONS, {"text": handler}),
            patch.object(self.module, "onebot_call") as onebot,
        ):
            asyncio.run(self.module.run_tick(config))
        handler.assert_not_called()
        onebot.assert_not_called()

    def test_template_message_files_are_local_and_nonempty(self):
        config = self.module.load_config()
        for entry in config["schedule"]:
            with self.subTest(task=entry["name"]):
                relative = Path(entry["file"])
                self.assertFalse(relative.is_absolute())
                target = (self.module_dir / relative).resolve()
                self.assertTrue(target.is_relative_to(self.module_dir.resolve()))
                self.assertTrue(target.is_file())
                self.assertTrue(target.read_text(encoding="utf-8").strip())
                self.assertIsNotNone(self.module.cron_expr(entry))

    def test_text_handler_reads_template_and_uses_mocked_send(self):
        entry = self.config["schedule"][0]
        expected = (self.module_dir / entry["file"]).read_text(encoding="utf-8").strip()
        with (
            patch.object(self.module, "group_ids", return_value={EXAMPLE_GROUP}),
            patch.object(self.module, "onebot_call", return_value={"status": "ok"}) as onebot,
        ):
            self.module.handle_text(self.config, entry)
        onebot.assert_called_once_with(
            self.config, "send_group_msg", {"group_id": EXAMPLE_GROUP, "message": expected}
        )

    def test_text_handler_skips_group_without_membership(self):
        with (
            patch.object(self.module, "group_ids", return_value=set()),
            patch.object(self.module, "onebot_call") as onebot,
        ):
            self.module.handle_text(self.config, self.config["schedule"][0])
        onebot.assert_not_called()


class WordlibTests(OfflineModuleCase):
    module_name = "wordlib"

    def setUp(self):
        super().setUp()
        self.bot = self.module.Wordlib()
        self.bot.load(force=True)

    def test_empty_groups_do_not_reply(self):
        self.assertEqual(self.bot.data["groups"], [])
        with patch.object(self.bot, "send_text", return_value=True) as send:
            asyncio.run(self.bot.on_event(group_event("早上好")))
        send.assert_not_called()

    def test_keyword_matches_and_prefixed_message_is_skipped(self):
        phrase, replies = self.bot.decide("大家早上好")
        self.assertEqual(phrase, "早上好")
        self.assertEqual(replies, self.config["rules"]["早上好"])
        self.assertIsNone(self.bot.decide("小Q 早上好"))
        self.assertIsNone(self.bot.decide("没有匹配项的测试文本"))

    def test_enabled_example_group_sends_only_mocked_reply(self):
        self.bot.data["groups"] = [EXAMPLE_GROUP]
        with patch.object(self.bot, "send_text", return_value=True) as send:
            asyncio.run(self.bot.on_event(group_event("早上好")))
        send.assert_called_once()
        group, reply = send.call_args.args
        self.assertEqual(group, EXAMPLE_GROUP)
        self.assertIn(reply, self.config["rules"]["早上好"])

    def test_at_bot_message_is_skipped(self):
        self.bot.data["groups"] = [EXAMPLE_GROUP]
        with patch.object(self.bot, "send_text", return_value=True) as send:
            asyncio.run(self.bot.on_event(group_event("早上好", at_bot=True)))
        send.assert_not_called()

    def test_configurable_endpoints_are_loaded_without_connecting(self):
        self.config["napcat_http"] = "https://example.invalid/onebot"
        self.config["ws_url"] = "wss://example.invalid/events"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.bot.load(force=True)
        self.assertEqual(self.module.NAPCAT_HTTP, self.config["napcat_http"])
        self.assertEqual(self.module.WS_URL, self.config["ws_url"])


if __name__ == "__main__":
    unittest.main()
