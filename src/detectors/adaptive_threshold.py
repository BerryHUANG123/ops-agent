"""自适应阈值引擎 — 基于历史数据动态调整告警阈值"""
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ThresholdStats:
    """单指标的统计信息"""
    mean: float = 0.0
    std: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    sample_count: int = 0
    min_val: float = 0.0
    max_val: float = 0.0


@dataclass
class AdaptiveThresholdConfig:
    """自适应阈值配置"""
    # 基础倍率：阈值 = mean + multiplier * std
    warning_multiplier: float = 2.0
    critical_multiplier: float = 3.0
    # 最小样本数（低于此数使用静态阈值）
    min_samples: int = 30
    # 滑动窗口大小
    window_size: int = 1440  # 24小时（假设每分钟一个采样点）
    # 各指标的绝对下限（无论如何不低于此值）
    floor: Dict[str, float] = field(default_factory=lambda: {
        "cpu_percent": 70.0,
        "memory_percent": 80.0,
        "disk_percent": 85.0,
        "load_per_cpu": 1.5,
    })
    # 各指标的绝对上限（无论如何不高于此值）
    ceiling: Dict[str, float] = field(default_factory=lambda: {
        "cpu_percent": 98.0,
        "memory_percent": 98.0,
        "disk_percent": 98.0,
        "load_per_cpu": 10.0,
    })


class AdaptiveThreshold:
    """自适应阈值引擎

    工作原理：
    1. 维护每个指标的滑动窗口历史值
    2. 定期计算统计量（均值、标准差、P95/P99）
    3. 动态生成告警阈值：mean + k * std
    4. 用 floor/ceiling 约束阈值范围
    5. 样本不足时回退到静态阈值
    """

    def __init__(self, config: Optional[AdaptiveThresholdConfig] = None):
        self.config = config or AdaptiveThresholdConfig()
        # 每个指标的滑动窗口
        self._windows: Dict[str, deque] = {}
        # 缓存的统计结果
        self._stats_cache: Dict[str, ThresholdStats] = {}
        self._cache_time: float = 0
        self._cache_ttl: float = 60  # 缓存 60 秒

    def record(self, metric_name: str, value: float) -> None:
        """记录一个指标值到滑动窗口

        Args:
            metric_name: 指标名（如 "cpu_percent"）
            value: 指标值
        """
        if metric_name not in self._windows:
            self._windows[metric_name] = deque(maxlen=self.config.window_size)
        self._windows[metric_name].append(value)
        # 新数据进来时清除缓存
        if metric_name in self._stats_cache:
            del self._stats_cache[metric_name]

    def get_thresholds(self, metric_name: str) -> tuple:
        """获取某指标的自适应告警阈值

        Args:
            metric_name: 指标名

        Returns:
            (warning_threshold, critical_threshold) 元组
            样本不足时返回 (None, None)，调用方应使用静态阈值
        """
        window = self._windows.get(metric_name)
        if not window or len(window) < self.config.min_samples:
            return (None, None)

        stats = self._compute_stats(metric_name)

        warning = stats.mean + self.config.warning_multiplier * stats.std
        critical = stats.mean + self.config.critical_multiplier * stats.std

        # 应用 floor/ceiling 约束
        floor = self.config.floor.get(metric_name, 0)
        ceiling = self.config.ceiling.get(metric_name, 100)

        warning = max(floor, min(ceiling, warning))
        critical = max(warning, min(ceiling, critical))  # critical >= warning

        logger.debug(
            "自适应阈值 %s: warning=%.1f critical=%.1f (mean=%.1f std=%.1f n=%d)",
            metric_name, warning, critical, stats.mean, stats.std, stats.sample_count
        )

        return (round(warning, 1), round(critical, 1))

    def get_stats(self, metric_name: str) -> Optional[ThresholdStats]:
        """获取某指标的统计信息"""
        if metric_name not in self._windows or len(self._windows[metric_name]) < 2:
            return None
        return self._compute_stats(metric_name)

    def has_enough_data(self, metric_name: str) -> bool:
        """判断某指标是否有足够样本进行自适应"""
        window = self._windows.get(metric_name)
        return window is not None and len(window) >= self.config.min_samples

    def reset(self, metric_name: Optional[str] = None) -> None:
        """重置指定指标或全部指标的历史数据"""
        if metric_name:
            self._windows.pop(metric_name, None)
            self._stats_cache.pop(metric_name, None)
        else:
            self._windows.clear()
            self._stats_cache.clear()

    def _compute_stats(self, metric_name: str) -> ThresholdStats:
        """计算统计量（带缓存）"""
        if metric_name in self._stats_cache:
            return self._stats_cache[metric_name]

        window = list(self._windows[metric_name])
        n = len(window)

        mean = sum(window) / n
        variance = sum((x - mean) ** 2 for x in window) / n
        std = variance ** 0.5

        sorted_vals = sorted(window)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        stats = ThresholdStats(
            mean=round(mean, 2),
            std=round(std, 2),
            p95=round(sorted_vals[min(p95_idx, n - 1)], 2),
            p99=round(sorted_vals[min(p99_idx, n - 1)], 2),
            sample_count=n,
            min_val=round(sorted_vals[0], 2),
            max_val=round(sorted_vals[-1], 2),
        )

        self._stats_cache[metric_name] = stats
        return stats
