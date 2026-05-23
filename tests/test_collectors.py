"""采集器单元测试"""
import time
import unittest
from unittest.mock import MagicMock, patch
from collections import namedtuple

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import SystemMetrics, ServiceStatus
from src.collectors.system_collector import SystemCollector
from src.collectors.log_collector import LogCollector


# 模拟 psutil 返回结构
MockVirtualMemory = namedtuple("MockVirtualMemory", ["percent", "used", "total"])
MockDiskUsage = namedtuple("MockDiskUsage", ["percent", "used", "total"])
MockNetIO = namedtuple("MockNetIO", ["bytes_sent", "bytes_recv"])
MockMemoryInfo = namedtuple("MockMemoryInfo", ["rss"])


class TestSystemCollector(unittest.TestCase):
    """测试 SystemCollector"""

    def setUp(self) -> None:
        self.collector = SystemCollector()

    @patch("src.collectors.system_collector.psutil")
    def test_collect_metrics_basic(self, mock_psutil: MagicMock) -> None:
        """测试基本指标采集"""
        mock_psutil.cpu_percent.return_value = 45.2
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MockVirtualMemory(
            percent=62.5, used=2 * 1024 ** 3, total=4 * 1024 ** 3
        )
        mock_psutil.disk_usage.return_value = MockDiskUsage(
            percent=55.0, used=100 * 1024 ** 3, total=200 * 1024 ** 3
        )
        mock_psutil.getloadavg.return_value = (1.5, 1.2, 1.0)
        mock_psutil.boot_time.return_value = time.time() - 86400  # 1 天前启动
        mock_psutil.net_io_counters.return_value = MockNetIO(
            bytes_sent=1024000, bytes_recv=2048000
        )

        metrics = self.collector.collect_metrics()

        self.assertIsInstance(metrics, SystemMetrics)
        self.assertEqual(metrics.cpu_percent, 45.2)
        self.assertEqual(metrics.cpu_count, 4)
        self.assertAlmostEqual(metrics.memory_percent, 62.5)
        self.assertAlmostEqual(metrics.memory_used_mb, 2048.0, places=0)
        self.assertAlmostEqual(metrics.disk_percent, 55.0)
        self.assertEqual(metrics.load_1m, 1.5)
        self.assertEqual(metrics.network_bytes_sent, 1024000)

    @patch("src.collectors.system_collector.psutil")
    def test_collect_metrics_error_handling(self, mock_psutil: MagicMock) -> None:
        """测试采集异常处理"""
        mock_psutil.cpu_percent.side_effect = RuntimeError("psutil error")

        with self.assertRaises(RuntimeError):
            self.collector.collect_metrics()

    @patch("src.collectors.system_collector.psutil")
    def test_collect_services_found(self, mock_psutil: MagicMock) -> None:
        """测试服务状态采集 — 服务存在"""
        mock_proc = MagicMock()
        mock_proc.info = {
            "pid": 1234,
            "name": "nginx",
            "cpu_percent": 2.5,
            "memory_info": MockMemoryInfo(rss=50 * 1024 * 1024),
        }
        mock_psutil.process_iter.return_value = [mock_proc]

        config = {
            "services": {
                "watch": [{"name": "nginx", "process": "nginx"}]
            }
        }

        services = self.collector.collect_services(config)

        self.assertEqual(len(services), 1)
        self.assertTrue(services[0].running)
        self.assertEqual(services[0].pid, 1234)
        self.assertEqual(services[0].name, "nginx")

    @patch("src.collectors.system_collector.psutil")
    def test_collect_services_not_found(self, mock_psutil: MagicMock) -> None:
        """测试服务状态采集 — 服务不存在"""
        mock_psutil.process_iter.return_value = []

        config = {
            "services": {
                "watch": [{"name": "nginx", "process": "nginx"}]
            }
        }

        services = self.collector.collect_services(config)

        self.assertEqual(len(services), 1)
        self.assertFalse(services[0].running)


class TestLogCollector(unittest.TestCase):
    """测试 LogCollector"""

    def setUp(self) -> None:
        self.collector = LogCollector()

    def test_collect_errors_basic(self) -> None:
        """测试基本日志错误采集"""
        import tempfile
        log_content = (
            "May 23 10:00:00 server sshd[1234]: Connection from 1.2.3.4\n"
            "May 23 10:00:01 server kernel: Out of memory: Kill process 5678\n"
            "May 23 10:00:02 server nginx: critical error in worker\n"
            "May 23 10:00:03 server sshd[1234]: Accepted publickey\n"
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(log_content)
            tmp_path = f.name

        try:
            config = {
                "logs": {
                    "paths": [tmp_path],
                    "error_patterns": ["error", "critical", "oom"],
                    "max_lines_per_check": 1000,
                }
            }
            errors = self.collector.collect_errors(config)

            self.assertGreater(len(errors), 0)
            messages = [e.message for e in errors]
            # "error" 匹配 "critical error in worker"，"critical" 也匹配该行
            self.assertTrue(any("critical" in m for m in messages))
        finally:
            os.unlink(tmp_path)

    def test_collect_errors_file_not_found(self) -> None:
        """测试日志文件不存在"""
        config = {
            "logs": {
                "paths": ["/nonexistent/file.log"],
                "error_patterns": ["error"],
                "max_lines_per_check": 1000,
            }
        }

        with patch("os.path.isfile", return_value=False):
            errors = self.collector.collect_errors(config)

        self.assertEqual(len(errors), 0)

    def test_incremental_read(self) -> None:
        """测试增量读取 — 只读新增行"""
        import tempfile
        content1 = "line1\nerror happened\nline3\n"
        self.collector._file_positions = {}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write(content1)
            tmp_path = f.name

        try:
            config = {
                "logs": {
                    "paths": [tmp_path],
                    "error_patterns": ["error"],
                    "max_lines_per_check": 1000,
                }
            }
            errors1 = self.collector.collect_errors(config)

            self.assertEqual(len(errors1), 1)
            self.assertIn(tmp_path, self.collector._file_positions)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
