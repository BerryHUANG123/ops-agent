"""自动处置器单元测试"""
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import ActionType, IssueType, RemediationAction, RemediationResult
from src.remediators.auto_remediator import AutoRemediator


class TestAutoRemediator(unittest.TestCase):
    """测试 AutoRemediator (dry_run 模式)"""

    def setUp(self) -> None:
        self.remediator = AutoRemediator(dry_run=True)
        self.config = {
            "remediation": {
                "enabled": True,
                "allowed_actions": ["restart_service", "clear_logs", "kill_process"],
                "max_log_size_mb": 500,
                "log_cleanup_paths": ["/var/log/*.log.1", "/tmp/ops-agent-*"],
            }
        }

    def test_remediate_service_down(self) -> None:
        """服务宕机应规划重启动作"""
        analysis = {
            "root_causes": [
                {
                    "issue_id": "test-001",
                    "issue_type": IssueType.SERVICE_DOWN.value,
                    "title": "服务宕机: nginx",
                    "details": {"service_name": "nginx"},
                    "root_cause": "进程崩溃",
                }
            ]
        }

        results = self.remediator.remediate(analysis, self.config)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)
        self.assertEqual(results[0].action.action_type, ActionType.RESTART_SERVICE)
        self.assertEqual(results[0].action.target, "nginx")
        self.assertIn("systemctl restart nginx", results[0].action.command)
        self.assertIn("DRY_RUN", results[0].output)

    def test_remediate_disk_high(self) -> None:
        """磁盘满应规划清理动作"""
        analysis = {
            "root_causes": [
                {
                    "issue_id": "test-002",
                    "issue_type": IssueType.DISK_HIGH.value,
                    "title": "磁盘使用率过高: 90%",
                    "details": {},
                    "root_cause": "日志堆积",
                }
            ]
        }

        results = self.remediator.remediate(analysis, self.config)

        self.assertGreater(len(results), 0)
        clear_actions = [r for r in results if r.action.action_type == ActionType.CLEAR_LOGS]
        self.assertGreater(len(clear_actions), 0)

    def test_remediate_disabled(self) -> None:
        """处置禁用时应返回空列表"""
        config = {"remediation": {"enabled": False}}
        analysis = {"root_causes": [
            {"issue_id": "x", "issue_type": IssueType.SERVICE_DOWN.value,
             "title": "svc down", "details": {"service_name": "sshd"}, "root_cause": "crash"}
        ]}

        results = self.remediator.remediate(analysis, config)

        self.assertEqual(len(results), 0)

    def test_remediate_not_allowed(self) -> None:
        """不在白名单中的动作不应执行"""
        config = {
            "remediation": {
                "enabled": True,
                "allowed_actions": [],  # 空白名单
            }
        }
        analysis = {"root_causes": [
            {"issue_id": "x", "issue_type": IssueType.SERVICE_DOWN.value,
             "title": "svc down", "details": {"service_name": "sshd"}, "root_cause": "crash"}
        ]}

        results = self.remediator.remediate(analysis, config)

        self.assertEqual(len(results), 0)

    def test_dry_run_no_actual_execution(self) -> None:
        """dry_run 模式不应实际执行命令"""
        analysis = {
            "root_causes": [
                {
                    "issue_id": "test-003",
                    "issue_type": IssueType.SERVICE_DOWN.value,
                    "title": "服务宕机: sshd",
                    "details": {"service_name": "sshd"},
                    "root_cause": "进程崩溃",
                }
            ]
        }

        results = self.remediator.remediate(analysis, self.config)

        for result in results:
            self.assertIn("DRY_RUN", result.output)
            self.assertTrue(result.success)

    def test_empty_analysis(self) -> None:
        """空分析结果应返回空列表"""
        results = self.remediator.remediate({"root_causes": []}, self.config)
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    unittest.main()
