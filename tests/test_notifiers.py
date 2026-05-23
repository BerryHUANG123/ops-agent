"""飞书通知器单元测试"""
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.models import (
    ActionType,
    Issue,
    IssueType,
    RemediationAction,
    RemediationResult,
    Severity,
)
from src.notifiers.feishu_notifier import FeishuNotifier


class TestFeishuNotifier(unittest.TestCase):
    """FeishuNotifier 测试"""

    def setUp(self) -> None:
        """初始化测试用 Notifier"""
        self.notifier = FeishuNotifier(
            webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
            secret="test_secret",
        )
        self.server_name = "test-server"

    def _make_issue(self, severity: Severity = Severity.CRITICAL, idx: int = 0) -> Issue:
        """创建测试用 Issue"""
        return Issue(
            id=f"issue-{idx}",
            timestamp=datetime.now(),
            severity=severity,
            issue_type=IssueType.CPU_HIGH,
            title=f"CPU 使用率过高 #{idx}",
            description=f"CPU 使用率达到 95%，超过阈值 85%",
            details={"cpu_percent": 95.0},
        )

    def _make_remediation_result(self, success: bool = True) -> RemediationResult:
        """创建测试用 RemediationResult"""
        action = RemediationAction(
            action_type=ActionType.RESTART_SERVICE,
            target="nginx",
            command="systemctl restart nginx",
            issue_id="issue-0",
        )
        return RemediationResult(
            action=action,
            success=success,
            output="ok" if success else "failed",
            timestamp=datetime.now(),
        )

    # ---- 卡片构建测试 ----

    def test_build_alert_card_single_critical(self) -> None:
        """单个 CRITICAL Issue 的告警卡片结构正确"""
        issues = [self._make_issue(Severity.CRITICAL)]
        card = self.notifier._build_alert_card(issues, self.server_name)

        # 校验顶层结构
        self.assertEqual(card["msg_type"], "interactive")
        self.assertIn("card", card)
        self.assertIn("header", card["card"])
        self.assertIn("elements", card["card"])

        # 校验 header
        header = card["card"]["header"]
        self.assertEqual(header["template"], "red")  # CRITICAL → red
        self.assertIn("test-server", header["title"]["content"])
        self.assertIn("1 个异常", header["title"]["content"])
        self.assertIn("🚨", header["title"]["content"])

        # 校验 elements
        elements = card["card"]["elements"]
        self.assertTrue(any(e.get("tag") == "markdown" for e in elements))
        self.assertTrue(any(e.get("tag") == "hr" for e in elements))
        self.assertTrue(any(e.get("tag") == "note" for e in elements))

    def test_build_alert_card_multiple_mixed_severity(self) -> None:
        """混合严重级别时，header 使用最高级别"""
        issues = [
            self._make_issue(Severity.INFO, 0),
            self._make_issue(Severity.WARNING, 1),
            self._make_issue(Severity.CRITICAL, 2),
        ]
        card = self.notifier._build_alert_card(issues, self.server_name)
        header = card["card"]["header"]
        self.assertEqual(header["template"], "red")  # 最高 CRITICAL
        self.assertIn("3 个异常", header["title"]["content"])

    def test_build_alert_card_max_10_display(self) -> None:
        """超过 10 个 Issue 只显示前 10 个"""
        issues = [self._make_issue(Severity.WARNING, i) for i in range(15)]
        card = self.notifier._build_alert_card(issues, self.server_name)
        md_element = [e for e in card["card"]["elements"] if e.get("tag") == "markdown"][0]
        self.assertIn("... 还有 5 个问题", md_element["content"])

    def test_build_remediation_card_all_success(self) -> None:
        """全部成功的处置卡片"""
        results = [self._make_remediation_result(True) for _ in range(3)]
        card = self.notifier._build_remediation_card(results, self.server_name)

        self.assertEqual(card["card"]["header"]["template"], "green")
        self.assertIn("3成功/0失败", card["card"]["header"]["title"]["content"])
        self.assertIn("✅", card["card"]["elements"][0]["content"])

    def test_build_remediation_card_partial_failure(self) -> None:
        """部分失败的处置卡片使用 orange"""
        results = [
            self._make_remediation_result(True),
            self._make_remediation_result(False),
        ]
        card = self.notifier._build_remediation_card(results, self.server_name)
        self.assertEqual(card["card"]["header"]["template"], "orange")
        self.assertIn("1成功/1失败", card["card"]["header"]["title"]["content"])

    def test_build_daily_card(self) -> None:
        """日报卡片结构正确"""
        stats = {
            "cpu_avg": 45.2,
            "mem_avg": 68.1,
            "disk_avg": 72.5,
            "total_alerts": 5,
            "total_actions": 3,
            "uptime": "3d 12h",
        }
        card = self.notifier._build_daily_card(stats, self.server_name)

        self.assertEqual(card["card"]["header"]["template"], "blue")
        self.assertIn("每日巡检摘要", card["card"]["header"]["title"]["content"])
        md = card["card"]["elements"][0]["content"]
        self.assertIn("45.2%", md)
        self.assertIn("68.1%", md)
        self.assertIn("72.5%", md)
        self.assertIn("3d 12h", md)

    # ---- 发送逻辑测试 ----

    @patch("src.notifiers.feishu_notifier.urllib.request.urlopen")
    def test_send_success(self, mock_urlopen: MagicMock) -> None:
        """Webhook 返回成功时 send_alert 返回 True"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"code": 0, "msg": "ok"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        issues = [self._make_issue()]
        result = self.notifier.send_alert(issues, self.server_name)
        self.assertTrue(result)
        mock_urlopen.assert_called_once()

    @patch("src.notifiers.feishu_notifier.urllib.request.urlopen")
    def test_send_failure_response(self, mock_urlopen: MagicMock) -> None:
        """Webhook 返回非 0 code 时 send_alert 返回 False"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"code": 9499, "msg": "bad"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        issues = [self._make_issue()]
        result = self.notifier.send_alert(issues, self.server_name)
        self.assertFalse(result)

    @patch("src.notifiers.feishu_notifier.urllib.request.urlopen")
    def test_send_network_error_no_crash(self, mock_urlopen: MagicMock) -> None:
        """网络异常时不应崩溃，返回 False"""
        mock_urlopen.side_effect = ConnectionError("connection refused")

        issues = [self._make_issue()]
        result = self.notifier.send_alert(issues, self.server_name)
        self.assertFalse(result)

    def test_send_empty_issues_returns_true(self) -> None:
        """空 Issue 列表直接返回 True，不发请求"""
        result = self.notifier.send_alert([], self.server_name)
        self.assertTrue(result)

    def test_send_empty_remediation_returns_true(self) -> None:
        """空处置结果列表直接返回 True"""
        result = self.notifier.send_remediation_report([], self.server_name)
        self.assertTrue(result)

    @patch("src.notifiers.feishu_notifier.urllib.request.urlopen")
    def test_send_timeout_no_crash(self, mock_urlopen: MagicMock) -> None:
        """请求超时不崩溃，返回 False"""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timed out")

        issues = [self._make_issue()]
        result = self.notifier.send_alert(issues, self.server_name)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
