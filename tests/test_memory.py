"""事件记忆存储单元测试"""
import os
import tempfile
import time
import unittest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models import (
    ActionType,
    Issue,
    IssueType,
    RemediationAction,
    RemediationResult,
    IncidentRecord,
    Severity,
)
from src.memory.incident_memory import IncidentMemory


def make_record(issue_type: IssueType = IssueType.CPU_HIGH, resolved: bool = True) -> IncidentRecord:
    """创建测试用 IncidentRecord"""
    issue = Issue(
        id=f"test-{issue_type.value}-{int(time.time())}",
        timestamp=time.time(),
        severity=Severity.WARNING,
        issue_type=issue_type,
        title=f"Test {issue_type.value}",
        description=f"Test description for {issue_type.value}",
        details={"test_key": "test_value"},
    )

    action = RemediationAction(
        action_type=ActionType.RESTART_SERVICE,
        target="nginx",
        command="systemctl restart nginx",
        issue_id=issue.id,
    )
    action_result = RemediationResult(
        action=action,
        success=resolved,
        output="restarted successfully" if resolved else "failed",
        timestamp=time.time(),
    )

    return IncidentRecord(
        issue=issue,
        root_cause="测试根因",
        action_taken=action_result,
        resolved=resolved,
        duration_seconds=1.5,
        lessons="测试教训",
    )


class TestIncidentMemory(unittest.TestCase):
    """测试 IncidentMemory"""

    def setUp(self) -> None:
        # 使用临时数据库
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_ops.db")
        self.memory = IncidentMemory(self.db_path)

    def tearDown(self) -> None:
        self.memory.close()
        # 清理临时文件
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)
        os.rmdir(self.tmp_dir)

    def test_save_and_query(self) -> None:
        """保存事件并查询"""
        record = make_record(IssueType.CPU_HIGH)
        record_id = self.memory.save_incident(record)

        self.assertIsNotNone(record_id)
        self.assertGreater(record_id, 0)

        results = self.memory.query_similar("cpu_high")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["issue_type"], "cpu_high")

    def test_query_with_keywords(self) -> None:
        """带关键词查询"""
        record = make_record(IssueType.MEMORY_HIGH)
        record.issue.title = "内存使用率过高: 95%"
        self.memory.save_incident(record)

        results = self.memory.query_similar("memory_high", keywords=["内存"])
        self.assertEqual(len(results), 1)

    def test_query_no_match(self) -> None:
        """查询不匹配的类型应返回空"""
        self.memory.save_incident(make_record(IssueType.CPU_HIGH))

        results = self.memory.query_similar("disk_high")
        self.assertEqual(len(results), 0)

    def test_get_stats_empty(self) -> None:
        """空数据库统计"""
        stats = self.memory.get_stats()

        self.assertEqual(stats["total_incidents"], 0)
        self.assertEqual(stats["resolution_rate"], 0.0)

    def test_get_stats_with_data(self) -> None:
        """有数据时统计"""
        self.memory.save_incident(make_record(IssueType.CPU_HIGH, resolved=True))
        self.memory.save_incident(make_record(IssueType.MEMORY_HIGH, resolved=True))
        self.memory.save_incident(make_record(IssueType.DISK_HIGH, resolved=False))

        stats = self.memory.get_stats()

        self.assertEqual(stats["total_incidents"], 3)
        self.assertEqual(stats["resolved_count"], 2)
        self.assertAlmostEqual(stats["resolution_rate"], 66.7, places=1)
        self.assertIn("cpu_high", stats["by_type"])
        self.assertIn("warning", stats["by_severity"])

    def test_cleanup(self) -> None:
        """清理过期记录"""
        # 插入 5 条记录
        for _ in range(5):
            self.memory.save_incident(make_record(IssueType.CPU_HIGH))

        # 保留 3 条
        deleted = self.memory.cleanup(max_records=3)

        self.assertEqual(deleted, 2)

        stats = self.memory.get_stats()
        self.assertEqual(stats["total_incidents"], 3)

    def test_cleanup_no_action(self) -> None:
        """记录数未超限时不应清理"""
        self.memory.save_incident(make_record())

        deleted = self.memory.cleanup(max_records=100)

        self.assertEqual(deleted, 0)

    def test_multiple_saves(self) -> None:
        """多次保存不同类型事件"""
        for issue_type in IssueType:
            self.memory.save_incident(make_record(issue_type))

        stats = self.memory.get_stats()
        self.assertEqual(stats["total_incidents"], len(IssueType))

    def test_save_without_action(self) -> None:
        """无处置动作的事件也能保存"""
        record = make_record()
        record.action_taken = None

        record_id = self.memory.save_incident(record)

        self.assertIsNotNone(record_id)
        results = self.memory.query_similar(record.issue.issue_type.value)
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
