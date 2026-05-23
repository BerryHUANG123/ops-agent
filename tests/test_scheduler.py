"""定时报表调度器单元测试"""
import threading
import time
import unittest
from unittest.mock import MagicMock

from src.scheduler.report_scheduler import ReportScheduler


class TestReportScheduler(unittest.TestCase):
    """ReportScheduler 测试用例"""

    def test_start_stop(self) -> None:
        """测试调度器启动和停止"""
        scheduler = ReportScheduler(interval_minutes=60)
        self.assertFalse(scheduler.is_running)

        scheduler.start()
        self.assertTrue(scheduler.is_running)
        self.assertIsNotNone(scheduler._thread)
        self.assertTrue(scheduler._thread.daemon)

        scheduler.stop(timeout=2.0)
        self.assertFalse(scheduler.is_running)

    def test_interval_trigger(self) -> None:
        """测试间隔触发（用短间隔 0.1 分钟 = 6 秒）"""
        call_count = {"value": 0}

        def on_report() -> None:
            call_count["value"] += 1

        scheduler = ReportScheduler(interval_minutes=0.1, on_report=on_report)
        scheduler.start()

        # 等待足够时间让回调触发至少一次
        time.sleep(8)

        scheduler.stop(timeout=2.0)
        self.assertGreaterEqual(call_count["value"], 1)

    def test_callback_called(self) -> None:
        """测试回调被正确调用"""
        callback = MagicMock()
        scheduler = ReportScheduler(interval_minutes=0.1, on_report=callback)
        scheduler.start()

        time.sleep(8)

        scheduler.stop(timeout=2.0)
        self.assertGreaterEqual(callback.call_count, 1)

    def test_callback_exception(self) -> None:
        """测试回调异常不影响调度器"""

        def bad_callback() -> None:
            raise RuntimeError("测试异常")

        callback = MagicMock(side_effect=bad_callback)
        scheduler = ReportScheduler(interval_minutes=0.1, on_report=callback)
        scheduler.start()

        time.sleep(8)

        # 调度器仍然运行
        self.assertTrue(scheduler.is_running)
        # 回调被调用了至少一次
        self.assertGreaterEqual(callback.call_count, 1)

        scheduler.stop(timeout=2.0)
        # 停止后累计运行次数正确
        self.assertGreaterEqual(scheduler.stats["run_count"], 1)

    def test_stats(self) -> None:
        """测试统计信息正确"""
        scheduler = ReportScheduler(interval_minutes=60)
        stats = scheduler.stats
        self.assertFalse(stats["running"])
        self.assertIsNone(stats["last_run"])
        self.assertEqual(stats["run_count"], 0)
        self.assertEqual(stats["mode"], "interval")
        self.assertEqual(stats["interval_minutes"], 60)

        scheduler.start()
        stats = scheduler.stats
        self.assertTrue(stats["running"])

        scheduler.stop(timeout=2.0)
        stats = scheduler.stats
        self.assertFalse(stats["running"])

    def test_daily_at_format(self) -> None:
        """测试每日时间格式解析"""
        scheduler = ReportScheduler(daily_at="08:00")
        stats = scheduler.stats
        self.assertEqual(stats["mode"], "daily")

        # 启动后应能正常停止
        scheduler.start()
        time.sleep(0.5)
        scheduler.stop(timeout=2.0)
        self.assertFalse(scheduler.is_running)

    def test_stop_idempotent(self) -> None:
        """测试多次 stop 不报错"""
        scheduler = ReportScheduler(interval_minutes=60)
        scheduler.start()
        time.sleep(0.5)

        # 多次 stop 不应抛异常
        scheduler.stop(timeout=2.0)
        scheduler.stop(timeout=2.0)
        scheduler.stop(timeout=2.0)
        self.assertFalse(scheduler.is_running)


if __name__ == "__main__":
    unittest.main()
