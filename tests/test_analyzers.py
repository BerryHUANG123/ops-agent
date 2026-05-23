"""故障分析器单元测试"""
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import Issue, IssueType, Severity
from src.analyzers.fault_analyzer import FaultAnalyzer


def make_issue(issue_type: IssueType, severity: Severity = Severity.WARNING) -> Issue:
    """创建测试用 Issue"""
    return Issue(
        id=f"test-{issue_type.value}",
        timestamp=time.time(),
        severity=severity,
        issue_type=issue_type,
        title=f"Test {issue_type.value}",
        description=f"Test description for {issue_type.value}",
        details={},
    )


class TestFaultAnalyzer(unittest.TestCase):
    """测试 FaultAnalyzer"""

    def setUp(self) -> None:
        self.analyzer = FaultAnalyzer()

    def test_no_issues(self) -> None:
        """无问题时应返回正常状态"""
        result = self.analyzer.analyze([])

        self.assertEqual(result["category"], "正常")
        self.assertFalse(result["correlated"])
        self.assertEqual(result["issue_count"], 0)

    def test_single_issue(self) -> None:
        """单个问题应返回对应根因"""
        issues = [make_issue(IssueType.CPU_HIGH)]
        result = self.analyzer.analyze(issues)

        self.assertEqual(result["issue_count"], 1)
        self.assertFalse(result["correlated"])
        self.assertEqual(result["category"], "资源类")
        self.assertGreater(len(result["suggestions"]), 0)

    def test_correlation_memory_service(self) -> None:
        """内存高 + 服务宕机应触发关联分析"""
        issues = [
            make_issue(IssueType.MEMORY_HIGH, Severity.CRITICAL),
            make_issue(IssueType.SERVICE_DOWN, Severity.CRITICAL),
        ]
        result = self.analyzer.analyze(issues)

        self.assertTrue(result["correlated"])
        root_causes = result["root_causes"]
        self.assertGreater(len(root_causes), 0)
        # 应包含 OOM 相关根因
        cause_texts = [rc.get("root_cause", "") for rc in root_causes]
        self.assertTrue(any("OOM" in c for c in cause_texts))

    def test_correlation_disk_logs(self) -> None:
        """磁盘高 + 日志错误应触发关联分析"""
        issues = [
            make_issue(IssueType.DISK_HIGH, Severity.WARNING),
            make_issue(IssueType.LOG_ERROR, Severity.WARNING),
        ]
        result = self.analyzer.analyze(issues)

        self.assertTrue(result["correlated"])
        cause_texts = [rc.get("root_cause", "") for rc in result["root_causes"]]
        self.assertTrue(any("磁盘" in c for c in cause_texts))

    def test_correlation_cpu_load(self) -> None:
        """CPU 高 + 负载高应触发关联分析"""
        issues = [
            make_issue(IssueType.CPU_HIGH, Severity.CRITICAL),
            make_issue(IssueType.LOAD_HIGH, Severity.CRITICAL),
        ]
        result = self.analyzer.analyze(issues)

        self.assertTrue(result["correlated"])

    def test_service_category(self) -> None:
        """服务类问题应归类为服务类"""
        issues = [make_issue(IssueType.SERVICE_DOWN)]
        result = self.analyzer.analyze(issues)

        self.assertEqual(result["category"], "服务类")

    def test_log_category(self) -> None:
        """日志类问题应归类为日志类"""
        issues = [make_issue(IssueType.LOG_ERROR)]
        result = self.analyzer.analyze(issues)

        self.assertEqual(result["category"], "日志类")

    def test_suggestions_generated(self) -> None:
        """分析结果应包含建议"""
        issues = [
            make_issue(IssueType.MEMORY_HIGH),
            make_issue(IssueType.DISK_HIGH),
        ]
        result = self.analyzer.analyze(issues)

        self.assertGreater(len(result["suggestions"]), 0)
        # 应包含内存和磁盘相关建议
        suggestions_text = " ".join(result["suggestions"])
        self.assertTrue("内存" in suggestions_text or "磁盘" in suggestions_text)

    def test_critical_count(self) -> None:
        """应正确统计 CRITICAL 级别数量"""
        issues = [
            make_issue(IssueType.CPU_HIGH, Severity.CRITICAL),
            make_issue(IssueType.DISK_HIGH, Severity.WARNING),
            make_issue(IssueType.MEMORY_HIGH, Severity.CRITICAL),
        ]
        result = self.analyzer.analyze(issues)

        self.assertEqual(result["critical_count"], 2)

    def test_trend_analysis(self) -> None:
        """有历史数据时应进行趋势分析"""
        issues = [make_issue(IssueType.CPU_HIGH)]
        history = [
            {"issue_count": 2},
            {"issue_count": 3},
            {"issue_count": 2},
            {"issue_count": 1},
            {"issue_count": 2},
        ]
        result = self.analyzer.analyze(issues, history=history)

        self.assertIn("trend", result)
        self.assertIn(result["trend"]["direction"], ["恶化", "改善", "稳定"])


if __name__ == "__main__":
    unittest.main()
