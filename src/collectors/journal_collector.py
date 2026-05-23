"""systemd journal 日志采集与分析器"""
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class JournalEntry:
    """journal 日志条目"""
    timestamp: str
    unit: str
    priority: int        # 0=emergency, 1=alert, 2=critical, 3=error, 4=warning, ...
    priority_name: str   # emerg, alert, crit, err, warning, notice, info, debug
    message: str
    pid: Optional[int] = None


class JournalCollector:
    """systemd journal 日志采集器

    通过 journalctl 命令采集结构化日志，
    支持按 unit、优先级、时间范围过滤。
    """

    # 优先级名称映射
    PRIORITY_NAMES = {
        0: "emerg", 1: "alert", 2: "crit", 3: "err",
        4: "warning", 5: "notice", 6: "info", 7: "debug",
    }

    def __init__(self, journalctl_bin: str = "journalctl"):
        self.journalctl_bin = journalctl_bin
        self._available: Optional[bool] = None
        # 记录每个 unit 的上次查询时间，实现增量采集
        self._last_query: Dict[str, datetime] = {}

    def is_available(self) -> bool:
        """检测 journalctl 是否可用"""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                [self.journalctl_bin, "--version"],
                capture_output=True, timeout=5
            )
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        if not self._available:
            logger.warning("journalctl 不可用")
        return self._available

    def collect_errors(
        self,
        units: Optional[List[str]] = None,
        max_priority: int = 3,  # 0-3 = emerg/alert/crit/err
        since_minutes: int = 60,
        max_entries: int = 500,
    ) -> List[JournalEntry]:
        """采集指定 unit 的错误级别日志

        Args:
            units: systemd unit 名称列表（如 ["sshd", "nginx"]），None 则采集全部
            max_priority: 最大优先级（0=最高，数字越大越低），默认 3=error
            since_minutes: 采集最近 N 分钟的日志
            max_entries: 最大条目数

        Returns:
            List[JournalEntry]: 日志条目列表
        """
        if not self.is_available():
            return []

        entries: List[JournalEntry] = []

        # 如果指定了 units，按 unit 分别采集
        target_units = units or [None]
        for unit in target_units:
            try:
                unit_entries = self._query_journal(
                    unit=unit,
                    max_priority=max_priority,
                    since_minutes=since_minutes,
                    max_entries=max_entries,
                )
                entries.extend(unit_entries)
            except Exception as e:
                logger.error("采集 journal 日志失败 (unit=%s): %s", unit, e)

        # 按时间排序
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        logger.info("journal 采集完成: %d 条日志 (units=%s, priority<=%d)",
                     len(entries), units, max_priority)
        return entries

    def collect_unit_summary(self, units: List[str], since_minutes: int = 60) -> Dict[str, dict]:
        """获取指定 unit 的日志摘要（各级别数量）

        Args:
            units: unit 名称列表
            since_minutes: 最近 N 分钟

        Returns:
            dict: {unit_name: {priority_name: count, ...}}
        """
        if not self.is_available():
            return {}

        summary: Dict[str, dict] = {}
        for unit in units:
            try:
                result = subprocess.run(
                    [
                        self.journalctl_bin,
                        "-u", unit,
                        f"--since=-{since_minutes}min",
                        "-p", "0..7",  # 所有优先级
                        "-o", "json",
                        "--no-pager",
                    ],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    summary[unit] = {}
                    continue

                counts: Dict[str, int] = {}
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        pri = int(data.get("PRIORITY", 6))
                        name = self.PRIORITY_NAMES.get(pri, "unknown")
                        counts[name] = counts.get(name, 0) + 1
                    except (json.JSONDecodeError, ValueError):
                        continue

                summary[unit] = counts

            except subprocess.TimeoutExpired:
                logger.warning("journal 日志摘要超时: %s", unit)
                summary[unit] = {}
            except Exception as e:
                logger.error("获取 journal 摘要失败 %s: %s", unit, e)
                summary[unit] = {}

        return summary

    def _query_journal(
        self,
        unit: Optional[str],
        max_priority: int,
        since_minutes: int,
        max_entries: int,
    ) -> List[JournalEntry]:
        """执行 journalctl 查询"""
        cmd = [
            self.journalctl_bin,
            f"--since=-{since_minutes}min",
            "-p", f"0..{max_priority}",
            "-o", "json",
            "--no-pager",
            "-n", str(max_entries),
        ]
        if unit:
            cmd.extend(["-u", unit])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            logger.warning("journalctl 返回非零: %s", result.stderr[:200])
            return []

        entries: List[JournalEntry] = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = self._parse_entry(line)
                entries.append(entry)
            except Exception as e:
                logger.debug("解析 journal 条目失败: %s", e)
                continue

        return entries

    def _parse_entry(self, json_line: str) -> JournalEntry:
        """解析单条 journalctl JSON 输出"""
        data = json.loads(json_line)

        # 解析时间戳（微秒级 Unix 时间戳）
        ts_usec = data.get("__REALTIME_TIMESTAMP", 0)
        if ts_usec:
            ts = datetime.fromtimestamp(int(ts_usec) / 1_000_000)
            timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp = "unknown"

        priority = int(data.get("PRIORITY", 6))
        unit = data.get("_SYSTEMD_UNIT", data.get("SYSLOG_IDENTIFIER", "unknown"))
        # 去掉 .service 后缀
        if unit.endswith(".service"):
            unit = unit[:-8]

        message = data.get("MESSAGE", "")
        pid = data.get("_PID")
        if pid is not None:
            try:
                pid = int(pid)
            except ValueError:
                pid = None

        return JournalEntry(
            timestamp=timestamp,
            unit=unit,
            priority=priority,
            priority_name=self.PRIORITY_NAMES.get(priority, "unknown"),
            message=message,
            pid=pid,
        )
