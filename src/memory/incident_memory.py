"""事件记忆存储 — 基于 SQLite 持久化事件记录，支持查询和统计"""
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.models import (
    ActionType,
    Issue,
    IssueType,
    RemediationAction,
    RemediationResult,
    IncidentRecord,
    Severity,
)

logger = logging.getLogger(__name__)


class IncidentMemory:
    """基于 SQLite 的事件记忆存储"""

    def __init__(self, db_path: str) -> None:
        """初始化数据库连接并建表

        Args:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        """创建事件表和索引"""
        cursor = self._conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                details TEXT,
                root_cause TEXT,
                action_type TEXT,
                action_target TEXT,
                action_command TEXT,
                action_success INTEGER,
                action_output TEXT,
                resolved INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                lessons TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_incidents_issue_type
                ON incidents(issue_type);
            CREATE INDEX IF NOT EXISTS idx_incidents_severity
                ON incidents(severity);
            CREATE INDEX IF NOT EXISTS idx_incidents_created_at
                ON incidents(created_at);
            CREATE INDEX IF NOT EXISTS idx_incidents_resolved
                ON incidents(resolved);
        """)
        self._conn.commit()
        logger.debug("数据库表初始化完成: %s", self.db_path)

    def save_incident(self, record: IncidentRecord) -> int:
        """保存事件记录

        Args:
            record: 事件记录对象

        Returns:
            int: 插入的记录 ID
        """
        now = time.time()
        details_json = json.dumps(record.issue.details, ensure_ascii=False)

        action_type = None
        action_target = None
        action_command = None
        action_success = None
        action_output = None

        if record.action_taken:
            action_type = record.action_taken.action.action_type.value
            action_target = record.action_taken.action.target
            action_command = record.action_taken.action.command
            action_success = 1 if record.action_taken.success else 0
            action_output = record.action_taken.output

        cursor = self._conn.cursor()
        cursor.execute("""
            INSERT INTO incidents (
                issue_id, issue_type, severity, title, description, details,
                root_cause, action_type, action_target, action_command,
                action_success, action_output, resolved, duration_seconds,
                lessons, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.issue.id,
            record.issue.issue_type.value,
            record.issue.severity.value,
            record.issue.title,
            record.issue.description,
            details_json,
            record.root_cause,
            action_type,
            action_target,
            action_command,
            action_success,
            action_output,
            1 if record.resolved else 0,
            record.duration_seconds,
            record.lessons,
            now,
            now,
        ))
        self._conn.commit()
        record_id = cursor.lastrowid
        logger.info("事件记录已保存: id=%d, issue_id=%s", record_id, record.issue.id)
        return record_id  # type: ignore

    def query_similar(self, issue_type: str, keywords: Optional[List[str]] = None) -> List[dict]:
        """查询相似的历史事件

        Args:
            issue_type: 问题类型
            keywords: 关键词列表（在标题和描述中搜索）

        Returns:
            List[dict]: 匹配的历史事件列表
        """
        query = "SELECT * FROM incidents WHERE issue_type = ?"
        params: list = [issue_type]

        if keywords:
            keyword_clauses = []
            for kw in keywords:
                keyword_clauses.append("(title LIKE ? OR description LIKE ?)")
                params.extend([f"%{kw}%", f"%{kw}%"])
            query += " AND (" + " OR ".join(keyword_clauses) + ")"

        query += " ORDER BY created_at DESC LIMIT 20"

        cursor = self._conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "issue_id": row["issue_id"],
                "issue_type": row["issue_type"],
                "severity": row["severity"],
                "title": row["title"],
                "description": row["description"],
                "root_cause": row["root_cause"],
                "resolved": bool(row["resolved"]),
                "lessons": row["lessons"],
                "created_at": datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M:%S"),
            })

        logger.debug("查询到 %d 条相似事件: type=%s", len(results), issue_type)
        return results

    def get_stats(self) -> dict:
        """获取事件统计信息

        Returns:
            dict: 统计信息，包含总数、解决率、常见故障类型等
        """
        cursor = self._conn.cursor()

        # 总数和解决率
        cursor.execute("SELECT COUNT(*) as total, SUM(resolved) as resolved FROM incidents")
        row = cursor.fetchone()
        total = row["total"] or 0
        resolved = row["resolved"] or 0

        # 按类型统计
        cursor.execute("""
            SELECT issue_type, COUNT(*) as cnt
            FROM incidents
            GROUP BY issue_type
            ORDER BY cnt DESC
        """)
        type_stats = {r["issue_type"]: r["cnt"] for r in cursor.fetchall()}

        # 按严重级别统计
        cursor.execute("""
            SELECT severity, COUNT(*) as cnt
            FROM incidents
            GROUP BY severity
        """)
        severity_stats = {r["severity"]: r["cnt"] for r in cursor.fetchall()}

        # 最近 7 天事件数
        week_ago = time.time() - 7 * 86400
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM incidents WHERE created_at >= ?",
            (week_ago,),
        )
        recent_count = cursor.fetchone()["cnt"]

        return {
            "total_incidents": total,
            "resolved_count": resolved,
            "resolution_rate": round(resolved / total * 100, 1) if total > 0 else 0.0,
            "by_type": type_stats,
            "by_severity": severity_stats,
            "recent_7days": recent_count,
        }

    def cleanup(self, max_records: int = 10000) -> int:
        """清理过期记录，保留最新的 max_records 条

        Args:
            max_records: 最大保留记录数

        Returns:
            int: 删除的记录数
        """
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM incidents")
        total = cursor.fetchone()["cnt"]

        if total <= max_records:
            return 0

        delete_count = total - max_records
        cursor.execute("""
            DELETE FROM incidents WHERE id IN (
                SELECT id FROM incidents ORDER BY created_at ASC LIMIT ?
            )
        """, (delete_count,))
        self._conn.commit()
        logger.info("清理了 %d 条过期事件记录", delete_count)
        return delete_count

    def close(self) -> None:
        """关闭数据库连接"""
        self._conn.close()
        logger.debug("数据库连接已关闭: %s", self.db_path)
