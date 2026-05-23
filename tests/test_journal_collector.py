"""JournalCollector 单元测试"""
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.collectors.journal_collector import JournalCollector, JournalEntry


class TestJournalCollector(unittest.TestCase):
    """JournalCollector 测试"""

    def test_is_available_no_journalctl(self):
        """journalctl 不可用时返回 False"""
        collector = JournalCollector(journalctl_bin="nonexistent_journalctl")
        self.assertFalse(collector.is_available())

    def test_is_available_success(self):
        """journalctl 可用时返回 True"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            collector = JournalCollector()
            self.assertTrue(collector.is_available())
            # 缓存结果，再次调用不应再调用 subprocess
            mock_run.reset_mock()
            self.assertTrue(collector.is_available())
            mock_run.assert_not_called()

    def test_parse_entry(self):
        """解析 JSON 日志条目"""
        collector = JournalCollector()
        # 构造 journalctl JSON 输出
        # 时间戳 2026-05-23 00:00:00 UTC+8 = 1779465600 微秒级
        ts_usec = "1779465600000000"
        data = {
            "__REALTIME_TIMESTAMP": ts_usec,
            "_SYSTEMD_UNIT": "nginx.service",
            "PRIORITY": "3",
            "MESSAGE": "Connection refused",
            "_PID": "1234",
        }
        entry = collector._parse_entry(json.dumps(data))

        self.assertEqual(entry.unit, "nginx")  # .service 后缀已去除
        self.assertEqual(entry.priority, 3)
        self.assertEqual(entry.priority_name, "err")
        self.assertEqual(entry.message, "Connection refused")
        self.assertEqual(entry.pid, 1234)
        self.assertIn("2026", entry.timestamp)

    def test_parse_entry_no_timestamp(self):
        """无时间戳的处理"""
        collector = JournalCollector()
        data = {
            "PRIORITY": "6",
            "MESSAGE": "Hello world",
        }
        entry = collector._parse_entry(json.dumps(data))
        self.assertEqual(entry.timestamp, "unknown")
        self.assertEqual(entry.priority, 6)
        self.assertEqual(entry.priority_name, "info")
        self.assertEqual(entry.unit, "unknown")
        self.assertIsNone(entry.pid)

    def test_priority_names(self):
        """优先级名称映射正确"""
        collector = JournalCollector()
        expected = {
            0: "emerg", 1: "alert", 2: "crit", 3: "err",
            4: "warning", 5: "notice", 6: "info", 7: "debug",
        }
        self.assertEqual(collector.PRIORITY_NAMES, expected)

    def test_collect_errors_success(self):
        """成功采集（mock subprocess）"""
        with patch("subprocess.run") as mock_run:
            # 第一次调用：--version 检查可用性
            version_result = MagicMock(returncode=0)
            # 第二次调用：实际 journalctl 查询
            entry_data = {
                "__REALTIME_TIMESTAMP": "1779465600000000",
                "_SYSTEMD_UNIT": "sshd.service",
                "PRIORITY": "3",
                "MESSAGE": "Authentication failure",
                "_PID": "5678",
            }
            query_result = MagicMock(
                returncode=0,
                stdout=json.dumps(entry_data) + "\n",
            )
            mock_run.side_effect = [version_result, query_result]

            collector = JournalCollector()
            entries = collector.collect_errors(units=["sshd"], max_priority=3, since_minutes=30)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].unit, "sshd")
            self.assertEqual(entries[0].priority_name, "err")
            self.assertEqual(entries[0].message, "Authentication failure")

    def test_collect_errors_unavailable(self):
        """不可用时返回空列表"""
        collector = JournalCollector(journalctl_bin="nonexistent_journalctl")
        entries = collector.collect_errors()
        self.assertEqual(entries, [])

    def test_collect_unit_summary(self):
        """摘要统计"""
        with patch("subprocess.run") as mock_run:
            # 第一次：--version 检查
            version_result = MagicMock(returncode=0)
            # 第二次：journalctl 查询
            entry1 = {"PRIORITY": "3", "MESSAGE": "error 1"}
            entry2 = {"PRIORITY": "3", "MESSAGE": "error 2"}
            entry3 = {"PRIORITY": "6", "MESSAGE": "info 1"}
            stdout = "\n".join([
                json.dumps(entry1),
                json.dumps(entry2),
                json.dumps(entry3),
            ])
            query_result = MagicMock(returncode=0, stdout=stdout)
            mock_run.side_effect = [version_result, query_result]

            collector = JournalCollector()
            summary = collector.collect_unit_summary(["nginx"], since_minutes=30)

            self.assertIn("nginx", summary)
            self.assertEqual(summary["nginx"].get("err", 0), 2)
            self.assertEqual(summary["nginx"].get("info", 0), 1)

    def test_unit_suffix_strip(self):
        """后缀正确去除"""
        collector = JournalCollector()
        # 测试 .service 后缀
        data = {
            "__REALTIME_TIMESTAMP": "1779465600000000",
            "_SYSTEMD_UNIT": "nginx.service",
            "PRIORITY": "6",
            "MESSAGE": "test",
        }
        entry = collector._parse_entry(json.dumps(data))
        self.assertEqual(entry.unit, "nginx")

        # 测试无后缀
        data2 = {
            "__REALTIME_TIMESTAMP": "1779465600000000",
            "_SYSTEMD_UNIT": "sshd.socket",
            "PRIORITY": "6",
            "MESSAGE": "test",
        }
        entry2 = collector._parse_entry(json.dumps(data2))
        self.assertEqual(entry2.unit, "sshd.socket")

        # 测试 SYSLOG_IDENTIFIER 回退
        data3 = {
            "__REALTIME_TIMESTAMP": "1779465600000000",
            "SYSLOG_IDENTIFIER": "my-app",
            "PRIORITY": "6",
            "MESSAGE": "test",
        }
        entry3 = collector._parse_entry(json.dumps(data3))
        self.assertEqual(entry3.unit, "my-app")

    def test_parse_entry_invalid_pid(self):
        """PID 为非数字时返回 None"""
        collector = JournalCollector()
        data = {
            "__REALTIME_TIMESTAMP": "1779465600000000",
            "_SYSTEMD_UNIT": "test.service",
            "PRIORITY": "6",
            "MESSAGE": "test",
            "_PID": "abc",
        }
        entry = collector._parse_entry(json.dumps(data))
        self.assertIsNone(entry.pid)

    def test_collect_unit_summary_timeout(self):
        """摘要查询超时处理"""
        import subprocess as sp
        with patch("subprocess.run") as mock_run:
            version_result = MagicMock(returncode=0)
            mock_run.side_effect = [version_result, sp.TimeoutExpired(cmd="journalctl", timeout=10)]

            collector = JournalCollector()
            summary = collector.collect_unit_summary(["nginx"])
            self.assertIn("nginx", summary)
            self.assertEqual(summary["nginx"], {})


if __name__ == "__main__":
    unittest.main()
