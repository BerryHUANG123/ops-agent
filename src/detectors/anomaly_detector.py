"""异常检测器 — 基于阈值检测系统异常，生成 Issue 列表"""
import hashlib
import logging
import time
from typing import Dict, List, Optional

from src.detectors.adaptive_threshold import AdaptiveThreshold, ThresholdStats
from src.models import (
    Issue,
    IssueType,
    LogEntry,
    ServiceStatus,
    Severity,
    SystemMetrics,
)

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """基于阈值的异常检测器，支持自适应阈值"""

    def __init__(self) -> None:
        """初始化检测器，创建自适应阈值引擎"""
        self.adaptive = AdaptiveThreshold()

    def detect(
        self,
        metrics: SystemMetrics,
        services: List[ServiceStatus],
        logs: List[LogEntry],
        config: dict,
        containers: Optional[List[dict]] = None,
    ) -> List[Issue]:
        """检测系统异常，返回 Issue 列表

        Args:
            metrics: 系统指标快照
            services: 服务状态列表
            logs: 日志错误条目列表
            config: 配置字典

        Returns:
            List[Issue]: 检测到的问题列表
        """
        issues: List[Issue] = []
        collectors_cfg = config.get("collectors", {})

        # 记录指标到自适应阈值引擎
        self.adaptive.record("cpu_percent", metrics.cpu_percent)
        self.adaptive.record("memory_percent", metrics.memory_percent)
        self.adaptive.record("disk_percent", metrics.disk_percent)
        if metrics.cpu_count > 0:
            self.adaptive.record("load_per_cpu", metrics.load_1m / metrics.cpu_count)

        # CPU 检测
        cpu_warn, cpu_crit = self.adaptive.get_thresholds("cpu_percent")
        if cpu_warn is None:
            # 样本不足，回退静态阈值
            cpu_warn = collectors_cfg.get("cpu_threshold", 85)
            cpu_crit = 95.0
        if metrics.cpu_percent >= cpu_crit:
            issues.append(self._make_issue(
                severity=Severity.CRITICAL,
                issue_type=IssueType.CPU_HIGH,
                title=f"CPU 使用率过高: {metrics.cpu_percent}%",
                description=f"CPU 使用率 {metrics.cpu_percent}% 超过阈值 {cpu_crit}%",
                details={"cpu_percent": metrics.cpu_percent, "threshold": cpu_crit},
            ))
        elif metrics.cpu_percent >= cpu_warn:
            issues.append(self._make_issue(
                severity=Severity.WARNING,
                issue_type=IssueType.CPU_HIGH,
                title=f"CPU 使用率过高: {metrics.cpu_percent}%",
                description=f"CPU 使用率 {metrics.cpu_percent}% 超过阈值 {cpu_warn}%",
                details={"cpu_percent": metrics.cpu_percent, "threshold": cpu_warn},
            ))

        # 内存检测
        mem_warn, mem_crit = self.adaptive.get_thresholds("memory_percent")
        if mem_warn is None:
            mem_warn = collectors_cfg.get("memory_threshold", 90)
            mem_crit = 95.0
        if metrics.memory_percent >= mem_crit:
            issues.append(self._make_issue(
                severity=Severity.CRITICAL,
                issue_type=IssueType.MEMORY_HIGH,
                title=f"内存使用率过高: {metrics.memory_percent}%",
                description=(
                    f"内存使用 {metrics.memory_used_mb}MB / {metrics.memory_total_mb}MB "
                    f"({metrics.memory_percent}%) 超过阈值 {mem_crit}%"
                ),
                details={
                    "memory_percent": metrics.memory_percent,
                    "memory_used_mb": metrics.memory_used_mb,
                    "memory_total_mb": metrics.memory_total_mb,
                    "threshold": mem_crit,
                },
            ))
        elif metrics.memory_percent >= mem_warn:
            issues.append(self._make_issue(
                severity=Severity.WARNING,
                issue_type=IssueType.MEMORY_HIGH,
                title=f"内存使用率过高: {metrics.memory_percent}%",
                description=(
                    f"内存使用 {metrics.memory_used_mb}MB / {metrics.memory_total_mb}MB "
                    f"({metrics.memory_percent}%) 超过阈值 {mem_warn}%"
                ),
                details={
                    "memory_percent": metrics.memory_percent,
                    "memory_used_mb": metrics.memory_used_mb,
                    "memory_total_mb": metrics.memory_total_mb,
                    "threshold": mem_warn,
                },
            ))

        # 磁盘检测
        disk_warn, disk_crit = self.adaptive.get_thresholds("disk_percent")
        if disk_warn is None:
            disk_warn = collectors_cfg.get("disk_threshold", 85)
            disk_crit = 95.0
        if metrics.disk_percent >= disk_crit:
            issues.append(self._make_issue(
                severity=Severity.CRITICAL,
                issue_type=IssueType.DISK_HIGH,
                title=f"磁盘使用率过高: {metrics.disk_percent}%",
                description=(
                    f"磁盘使用 {metrics.disk_used_gb}GB / {metrics.disk_total_gb}GB "
                    f"({metrics.disk_percent}%) 超过阈值 {disk_crit}%"
                ),
                details={
                    "disk_percent": metrics.disk_percent,
                    "disk_used_gb": metrics.disk_used_gb,
                    "disk_total_gb": metrics.disk_total_gb,
                    "threshold": disk_crit,
                },
            ))
        elif metrics.disk_percent >= disk_warn:
            issues.append(self._make_issue(
                severity=Severity.WARNING,
                issue_type=IssueType.DISK_HIGH,
                title=f"磁盘使用率过高: {metrics.disk_percent}%",
                description=(
                    f"磁盘使用 {metrics.disk_used_gb}GB / {metrics.disk_total_gb}GB "
                    f"({metrics.disk_percent}%) 超过阈值 {disk_warn}%"
                ),
                details={
                    "disk_percent": metrics.disk_percent,
                    "disk_used_gb": metrics.disk_used_gb,
                    "disk_total_gb": metrics.disk_total_gb,
                    "threshold": disk_warn,
                },
            ))

        # 负载检测
        if metrics.cpu_count > 0:
            load_per_cpu = metrics.load_1m / metrics.cpu_count
            load_warn, load_crit = self.adaptive.get_thresholds("load_per_cpu")
            if load_warn is None:
                load_warn = collectors_cfg.get("load_multiplier", 2.0)
                load_crit = load_warn * 1.5
            if load_per_cpu >= load_crit:
                issues.append(self._make_issue(
                    severity=Severity.CRITICAL,
                    issue_type=IssueType.LOAD_HIGH,
                    title=f"系统负载过高: {metrics.load_1m} ({load_per_cpu:.1f}/CPU)",
                    description=(
                        f"1分钟负载 {metrics.load_1m}，每 CPU 负载 {load_per_cpu:.2f}，"
                        f"超过阈值 {load_crit}"
                    ),
                    details={
                        "load_1m": metrics.load_1m,
                        "load_5m": metrics.load_5m,
                        "load_15m": metrics.load_15m,
                        "cpu_count": metrics.cpu_count,
                        "load_per_cpu": round(load_per_cpu, 2),
                    },
                ))
            elif load_per_cpu >= load_warn:
                issues.append(self._make_issue(
                    severity=Severity.WARNING,
                    issue_type=IssueType.LOAD_HIGH,
                    title=f"系统负载过高: {metrics.load_1m} ({load_per_cpu:.1f}/CPU)",
                    description=(
                        f"1分钟负载 {metrics.load_1m}，每 CPU 负载 {load_per_cpu:.2f}，"
                        f"超过阈值 {load_warn}"
                    ),
                    details={
                        "load_1m": metrics.load_1m,
                        "load_5m": metrics.load_5m,
                        "load_15m": metrics.load_15m,
                        "cpu_count": metrics.cpu_count,
                        "load_per_cpu": round(load_per_cpu, 2),
                    },
                ))

        # 服务宕机检测
        for svc in services:
            if not svc.running:
                issues.append(self._make_issue(
                    severity=Severity.CRITICAL,
                    issue_type=IssueType.SERVICE_DOWN,
                    title=f"服务宕机: {svc.name}",
                    description=f"服务 {svc.name} (进程: {svc.name}) 未运行",
                    details={"service_name": svc.name, "pid": svc.pid},
                ))

        # 日志错误聚合（相同错误去重）
        if logs:
            error_groups = self._aggregate_logs(logs)
            for group_key, entries in error_groups.items():
                count = len(entries)
                sample = entries[0].message[:200]
                issues.append(self._make_issue(
                    severity=Severity.WARNING if count < 10 else Severity.CRITICAL,
                    issue_type=IssueType.LOG_ERROR,
                    title=f"日志错误 ({count}次): {entries[0].level}",
                    description=f"在 {entries[0].source} 中检测到 {count} 条 {entries[0].level} 错误",
                    details={
                        "source": entries[0].source,
                        "level": entries[0].level,
                        "count": count,
                        "sample": sample,
                    },
                ))

        # Docker 容器异常检测
        if containers:
            for c in containers:
                c_status = c.get("status", "")
                c_name = c.get("name", "unknown")
                c_health = c.get("health", "none")
                c_cpu = c.get("cpu_percent", 0.0)
                c_mem = c.get("memory_percent", 0.0)
                c_restart = c.get("restart_count", 0)

                # 容器状态非 running
                if c_status and c_status != "running":
                    issues.append(self._make_issue(
                        severity=Severity.CRITICAL,
                        issue_type=IssueType.SERVICE_DOWN,
                        title=f"容器异常: {c_name} ({c_status})",
                        description=f"容器 {c_name} 状态为 {c_status}，非 running",
                        details={"container_name": c_name, "status": c_status},
                    ))

                # 容器 health 为 unhealthy
                if c_health == "unhealthy":
                    issues.append(self._make_issue(
                        severity=Severity.CRITICAL,
                        issue_type=IssueType.SERVICE_DOWN,
                        title=f"容器健康检查失败: {c_name}",
                        description=f"容器 {c_name} 健康检查状态为 unhealthy",
                        details={"container_name": c_name, "health": c_health},
                    ))

                # 容器 CPU > 90%
                if c_cpu > 90:
                    issues.append(self._make_issue(
                        severity=Severity.WARNING,
                        issue_type=IssueType.SERVICE_DOWN,
                        title=f"容器 CPU 过高: {c_name} ({c_cpu}%)",
                        description=f"容器 {c_name} CPU 使用率 {c_cpu}% 超过 90%",
                        details={"container_name": c_name, "cpu_percent": c_cpu},
                    ))

                # 容器内存 > 90%
                if c_mem > 90:
                    issues.append(self._make_issue(
                        severity=Severity.WARNING,
                        issue_type=IssueType.SERVICE_DOWN,
                        title=f"容器内存过高: {c_name} ({c_mem}%)",
                        description=f"容器 {c_name} 内存使用率 {c_mem}% 超过 90%",
                        details={"container_name": c_name, "memory_percent": c_mem},
                    ))

                # 容器重启次数 > 3
                if c_restart > 3:
                    issues.append(self._make_issue(
                        severity=Severity.WARNING,
                        issue_type=IssueType.SERVICE_DOWN,
                        title=f"容器频繁重启: {c_name} ({c_restart}次)",
                        description=f"容器 {c_name} 重启次数 {c_restart} 超过 3 次",
                        details={"container_name": c_name, "restart_count": c_restart},
                    ))

        logger.info("检测完成，发现 %d 个问题", len(issues))
        return issues

    def _make_issue(
        self,
        severity: Severity,
        issue_type: IssueType,
        title: str,
        description: str,
        details: dict,
    ) -> Issue:
        """生成 Issue 对象，ID 基于类型和时间戳哈希

        Args:
            severity: 严重级别
            issue_type: 问题类型
            title: 标题
            description: 描述
            details: 详细信息

        Returns:
            Issue: 问题对象
        """
        raw = f"{issue_type.value}:{time.time()}"
        issue_id = hashlib.md5(raw.encode()).hexdigest()[:12]
        return Issue(
            id=issue_id,
            timestamp=time.time(),
            severity=severity,
            issue_type=issue_type,
            title=title,
            description=description,
            details=details,
        )

    def get_adaptive_info(self) -> Dict[str, dict]:
        """获取各指标的自适应阈值状态

        Returns:
            字典，key 为指标名，value 包含：
            - enabled: 是否已启用自适应（样本是否充足）
            - warning: 当前 warning 阈值
            - critical: 当前 critical 阈值
            - stats: 统计信息（如有）
        """
        result: Dict[str, dict] = {}
        for metric_name in ("cpu_percent", "memory_percent", "disk_percent", "load_per_cpu"):
            enabled = self.adaptive.has_enough_data(metric_name)
            warn, crit = self.adaptive.get_thresholds(metric_name)
            stats_obj = self.adaptive.get_stats(metric_name)
            stats_dict = None
            if stats_obj:
                stats_dict = {
                    "mean": stats_obj.mean,
                    "std": stats_obj.std,
                    "p95": stats_obj.p95,
                    "p99": stats_obj.p99,
                    "min_val": stats_obj.min_val,
                    "max_val": stats_obj.max_val,
                    "sample_count": stats_obj.sample_count,
                }
            result[metric_name] = {
                "enabled": enabled,
                "warning": warn,
                "critical": crit,
                "stats": stats_dict,
            }
        return result

    @staticmethod
    def _aggregate_logs(logs: List[LogEntry]) -> dict:
        """按来源+级别+消息前50字符聚合日志，去重

        Args:
            logs: 日志条目列表

        Returns:
            dict: 聚合后的日志分组，key 为分组标识
        """
        groups: dict = {}
        for entry in logs:
            # 用来源+级别+消息前缀作为去重 key
            prefix = entry.message[:50].strip()
            key = f"{entry.source}|{entry.level}|{prefix}"
            if key not in groups:
                groups[key] = []
            groups[key].append(entry)
        return groups
