"""日志采集器 — 读取日志文件，匹配错误模式，增量采集"""
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.models import LogEntry

logger = logging.getLogger(__name__)


class LogCollector:
    """日志错误采集器，支持增量读取和多文件并发"""

    def __init__(self) -> None:
        # 记录每个日志文件上次读取的位置（字节偏移）
        self._file_positions: Dict[str, int] = {}

    def collect_errors(self, config: dict) -> List[LogEntry]:
        """读取配置中的日志文件，匹配错误模式

        Args:
            config: 配置字典，需包含 logs.paths、logs.error_patterns、logs.max_lines_per_check

        Returns:
            List[LogEntry]: 匹配到的错误日志条目
        """
        logs_config = config.get("logs", {})
        log_paths: List[str] = logs_config.get("paths", [])
        error_patterns: List[str] = logs_config.get("error_patterns", ["error", "critical", "fatal"])
        max_lines: int = logs_config.get("max_lines_per_check", 1000)

        # 编译正则，忽略大小写
        compiled_patterns = [
            re.compile(re.escape(p), re.IGNORECASE) for p in error_patterns
        ]

        all_errors: List[LogEntry] = []

        for log_path in log_paths:
            try:
                errors = self._read_log_file(log_path, compiled_patterns, max_lines)
                all_errors.extend(errors)
            except FileNotFoundError:
                logger.warning("日志文件不存在: %s", log_path)
            except PermissionError:
                logger.warning("无权限读取日志文件: %s", log_path)
            except Exception as e:
                logger.error("读取日志文件 %s 失败: %s", log_path, e)

        return all_errors

    def _read_log_file(
        self,
        log_path: str,
        patterns: List[re.Pattern],
        max_lines: int,
    ) -> List[LogEntry]:
        """增量读取单个日志文件，只处理新增行

        Args:
            log_path: 日志文件路径
            patterns: 编译后的错误模式正则列表
            max_lines: 单次最大读取行数

        Returns:
            List[LogEntry]: 匹配到的错误日志条目
        """
        if not os.path.isfile(log_path):
            raise FileNotFoundError(f"日志文件不存在: {log_path}")

        file_size = os.path.getsize(log_path)
        last_pos = self._file_positions.get(log_path, 0)

        # 文件被轮转（大小变小），重置位置
        if file_size < last_pos:
            logger.info("检测到日志轮转，重置读取位置: %s", log_path)
            last_pos = 0

        errors: List[LogEntry] = []
        lines_read = 0

        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_pos)
            for line in f:
                lines_read += 1
                if lines_read > max_lines:
                    logger.warning("达到最大读取行数 %d，跳过剩余: %s", max_lines, log_path)
                    break

                line = line.strip()
                if not line:
                    continue

                for pattern in patterns:
                    if pattern.search(line):
                        entry = self._parse_log_line(log_path, line, pattern.pattern)
                        errors.append(entry)
                        break  # 一行只匹配一次，避免重复

            # 记录当前位置
            self._file_positions[log_path] = f.tell()

        logger.debug("从 %s 读取 %d 行，发现 %d 条错误", log_path, lines_read, len(errors))
        return errors

    def _parse_log_line(self, source: str, line: str, matched_pattern: str) -> LogEntry:
        """解析单行日志，尝试提取时间戳

        Args:
            source: 日志来源文件
            line: 日志行内容
            matched_pattern: 匹配到的错误模式

        Returns:
            LogEntry: 解析后的日志条目
        """
        # 尝试从行首提取时间戳（常见 syslog 格式）
        timestamp = self._extract_timestamp(line)
        if timestamp is None:
            timestamp = datetime.now()

        return LogEntry(
            timestamp=timestamp,
            source=source,
            level=matched_pattern.upper(),
            message=line[:500],  # 截断过长的消息
        )

    @staticmethod
    def _extract_timestamp(line: str) -> Optional[datetime]:
        """尝试从日志行中提取时间戳

        支持格式：
        - "May 23 12:34:56" (syslog)
        - "2024-05-23 12:34:56" (ISO-like)
        - "2024-05-23T12:34:56" (ISO)

        Args:
            line: 日志行

        Returns:
            Optional[datetime]: 提取到的时间戳，无法解析则返回 None
        """
        # ISO 格式: 2024-05-23 12:34:56 或 2024-05-23T12:34:56
        iso_match = re.match(
            r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", line
        )
        if iso_match:
            try:
                return datetime.strptime(
                    f"{iso_match.group(1)} {iso_match.group(2)}", "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                pass

        return None
