"""自适应阈值引擎测试"""
import unittest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.detectors.adaptive_threshold import (
    AdaptiveThreshold,
    AdaptiveThresholdConfig,
    ThresholdStats,
)


class TestAdaptiveThreshold(unittest.TestCase):
    """AdaptiveThreshold 测试套件"""

    def test_not_enough_data(self):
        """样本不足时返回 (None, None)"""
        at = AdaptiveThreshold()
        for i in range(20):
            at.record("cpu_percent", 50.0 + i)

        warn, crit = at.get_thresholds("cpu_percent")
        self.assertIsNone(warn)
        self.assertIsNone(crit)

    def test_enough_data_returns_thresholds(self):
        """足够样本后返回合理的阈值"""
        at = AdaptiveThreshold()
        for _ in range(30):
            at.record("cpu_percent", 50.0)

        warn, crit = at.get_thresholds("cpu_percent")
        self.assertIsNotNone(warn)
        self.assertIsNotNone(crit)
        # std=0，warning = mean + 2*0 = 50，但受 floor 70 约束
        self.assertGreaterEqual(warn, 70.0)
        self.assertGreaterEqual(crit, warn)

    def test_threshold_respects_floor(self):
        """阈值不低于 floor"""
        config = AdaptiveThresholdConfig(
            floor={"test_metric": 70.0},
            ceiling={"test_metric": 100.0},
            min_samples=5,
        )
        at = AdaptiveThreshold(config=config)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            at.record("test_metric", v)

        warn, crit = at.get_thresholds("test_metric")
        self.assertGreaterEqual(warn, 70.0)
        self.assertGreaterEqual(crit, 70.0)

    def test_threshold_respects_ceiling(self):
        """阈值不高于 ceiling"""
        config = AdaptiveThresholdConfig(
            floor={"test_metric": 0.0},
            ceiling={"test_metric": 90.0},
            warning_multiplier=10.0,
            critical_multiplier=20.0,
            min_samples=5,
        )
        at = AdaptiveThreshold(config=config)
        for v in [80.0, 82.0, 84.0, 86.0, 88.0]:
            at.record("test_metric", v)

        warn, crit = at.get_thresholds("test_metric")
        self.assertLessEqual(warn, 90.0)
        self.assertLessEqual(crit, 90.0)

    def test_stats_computation(self):
        """统计量计算正确"""
        config = AdaptiveThresholdConfig(min_samples=5)
        at = AdaptiveThreshold(config=config)
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for v in values:
            at.record("test_metric", v)

        stats = at.get_stats("test_metric")
        self.assertIsNotNone(stats)
        self.assertEqual(stats.sample_count, 5)
        self.assertEqual(stats.min_val, 10.0)
        self.assertEqual(stats.max_val, 50.0)
        self.assertEqual(stats.mean, 30.0)
        self.assertAlmostEqual(stats.std, 14.14, places=1)
        self.assertEqual(stats.p95, 50.0)
        self.assertEqual(stats.p99, 50.0)

    def test_reset(self):
        """重置清空数据"""
        at = AdaptiveThreshold()
        for i in range(30):
            at.record("cpu_percent", 50.0)
        self.assertTrue(at.has_enough_data("cpu_percent"))

        at.reset("cpu_percent")
        self.assertFalse(at.has_enough_data("cpu_percent"))

        for i in range(30):
            at.record("memory_percent", 60.0)
        self.assertTrue(at.has_enough_data("memory_percent"))
        at.reset()
        self.assertFalse(at.has_enough_data("memory_percent"))

    def test_window_eviction(self):
        """滑动窗口淘汰旧数据"""
        config = AdaptiveThresholdConfig(window_size=10, min_samples=5)
        at = AdaptiveThreshold(config=config)

        for _ in range(10):
            at.record("test_metric", 10.0)
        for _ in range(10):
            at.record("test_metric", 90.0)

        stats = at.get_stats("test_metric")
        self.assertIsNotNone(stats)
        self.assertEqual(stats.mean, 90.0)
        self.assertEqual(stats.min_val, 90.0)
        self.assertEqual(stats.max_val, 90.0)

    def test_critical_gt_warning(self):
        """critical 阈值始终 >= warning"""
        config = AdaptiveThresholdConfig(
            warning_multiplier=1.0,
            critical_multiplier=2.0,
            min_samples=5,
            floor={"test_metric": 0.0},
            ceiling={"test_metric": 100.0},
        )
        at = AdaptiveThreshold(config=config)
        for v in [10.0, 15.0, 20.0, 25.0, 30.0]:
            at.record("test_metric", v)

        warn, crit = at.get_thresholds("test_metric")
        self.assertGreaterEqual(crit, warn)

    def test_no_data_returns_none_stats(self):
        """无数据时 get_stats 返回 None"""
        at = AdaptiveThreshold()
        self.assertIsNone(at.get_stats("nonexistent"))

    def test_enough_data_flag(self):
        """has_enough_data 边界测试"""
        config = AdaptiveThresholdConfig(min_samples=5)
        at = AdaptiveThreshold(config=config)
        self.assertFalse(at.has_enough_data("test_metric"))

        for i in range(4):
            at.record("test_metric", float(i))
        self.assertFalse(at.has_enough_data("test_metric"))

        at.record("test_metric", 4.0)
        self.assertTrue(at.has_enough_data("test_metric"))


if __name__ == "__main__":
    unittest.main()
