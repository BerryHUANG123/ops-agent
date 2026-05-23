"""异常检测器单元测试"""
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import (
    IssueType,
    LogEntry,
    ServiceStatus,
    Severity,
    SystemMetrics,
)
from src.detectors.anomaly_detector import AnomalyDetector


def make_metrics(**kwargs) -> SystemMetrics:
    """创建测试用 SystemMetrics"""
    defaults = {
        "timestamp": time.time(),
        "cpu_percent": 50.0,
        "memory_percent": 60.0,
        "memory_used_mb": 2048.0,
        "memory_total_mb": 4096.0,
        "disk_percent": 50.0,
        "disk_used_gb": 100.0,
        "disk_total_gb": 200.0,
        "load_1m": 1.0,
        "load_5m": 1.0,
        "load_15m": 1.0,
        "cpu_count": 4,
        "uptime_seconds": 86400,
    }
    defaults.update(kwargs)
    return SystemMetrics(**defaults)


class TestAnomalyDetector(unittest.TestCase):
    """测试 AnomalyDetector"""

    def setUp(self) -> None:
        self.detector = AnomalyDetector()
        self.config = {
            "collectors": {
                "cpu_threshold": 85,
                "memory_threshold": 90,
                "disk_threshold": 85,
                "load_multiplier": 2.0,
            }
        }

    def test_no_issues_normal(self) -> None:
        """正常指标不应产生告警"""
        metrics = make_metrics(cpu_percent=30, memory_percent=50, disk_percent=40, load_1m=0.5)
        issues = self.detector.detect(metrics, [], [], self.config)
        self.assertEqual(len(issues), 0)

    def test_cpu_high(self) -> None:
        """CPU 超阈值应产生告警"""
        metrics = make_metrics(cpu_percent=90)
        issues = self.detector.detect(metrics, [], [], self.config)

        cpu_issues = [i for i in issues if i.issue_type == IssueType.CPU_HIGH]
        self.assertEqual(len(cpu_issues), 1)
        self.assertEqual(cpu_issues[0].severity, Severity.WARNING)

    def test_cpu_critical(self) -> None:
        """CPU 超 95% 应为 CRITICAL"""
        metrics = make_metrics(cpu_percent=97)
        issues = self.detector.detect(metrics, [], [], self.config)

        cpu_issues = [i for i in issues if i.issue_type == IssueType.CPU_HIGH]
        self.assertEqual(cpu_issues[0].severity, Severity.CRITICAL)

    def test_memory_high(self) -> None:
        """内存超阈值应产生告警"""
        metrics = make_metrics(memory_percent=92)
        issues = self.detector.detect(metrics, [], [], self.config)

        mem_issues = [i for i in issues if i.issue_type == IssueType.MEMORY_HIGH]
        self.assertEqual(len(mem_issues), 1)

    def test_disk_high(self) -> None:
        """磁盘超阈值应产生告警"""
        metrics = make_metrics(disk_percent=88)
        issues = self.detector.detect(metrics, [], [], self.config)

        disk_issues = [i for i in issues if i.issue_type == IssueType.DISK_HIGH]
        self.assertEqual(len(disk_issues), 1)

    def test_load_high(self) -> None:
        """负载超阈值应产生告警（4 CPU，阈值 2.0 → 负载 > 8）"""
        metrics = make_metrics(load_1m=9.0, cpu_count=4)
        issues = self.detector.detect(metrics, [], [], self.config)

        load_issues = [i for i in issues if i.issue_type == IssueType.LOAD_HIGH]
        self.assertEqual(len(load_issues), 1)

    def test_service_down(self) -> None:
        """服务宕机应产生告警"""
        metrics = make_metrics()
        services = [ServiceStatus(name="nginx", running=False)]
        issues = self.detector.detect(metrics, services, [], self.config)

        svc_issues = [i for i in issues if i.issue_type == IssueType.SERVICE_DOWN]
        self.assertEqual(len(svc_issues), 1)
        self.assertEqual(svc_issues[0].severity, Severity.CRITICAL)

    def test_service_running_no_issue(self) -> None:
        """服务正常运行不应产生告警"""
        metrics = make_metrics()
        services = [ServiceStatus(name="nginx", running=True, pid=1234)]
        issues = self.detector.detect(metrics, services, [], self.config)

        svc_issues = [i for i in issues if i.issue_type == IssueType.SERVICE_DOWN]
        self.assertEqual(len(svc_issues), 0)

    def test_log_error_aggregation(self) -> None:
        """日志错误应被聚合去重"""
        metrics = make_metrics()
        # 创建多条相同类型的日志
        logs = [
            LogEntry(timestamp=time.time(), source="/var/log/syslog", level="ERROR", message="connection refused to db")
            for _ in range(5)
        ]
        issues = self.detector.detect(metrics, [], logs, self.config)

        log_issues = [i for i in issues if i.issue_type == IssueType.LOG_ERROR]
        # 相同消息应被聚合为 1 个 issue
        self.assertEqual(len(log_issues), 1)
        self.assertIn("5", log_issues[0].title)

    def test_multiple_issues(self) -> None:
        """多个指标同时异常应产生多个告警"""
        metrics = make_metrics(cpu_percent=90, memory_percent=95, disk_percent=90)
        issues = self.detector.detect(metrics, [], [], self.config)

        self.assertGreaterEqual(len(issues), 3)
        types = {i.issue_type for i in issues}
        self.assertIn(IssueType.CPU_HIGH, types)
        self.assertIn(IssueType.MEMORY_HIGH, types)
        self.assertIn(IssueType.DISK_HIGH, types)


if __name__ == "__main__":
    unittest.main()
