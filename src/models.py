"""核心数据模型"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Severity(Enum):
    """告警严重级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class IssueType(Enum):
    """问题类型枚举"""
    CPU_HIGH = "cpu_high"
    MEMORY_HIGH = "memory_high"
    DISK_HIGH = "disk_high"
    LOAD_HIGH = "load_high"
    SERVICE_DOWN = "service_down"
    LOG_ERROR = "log_error"
    DISK_SMART = "disk_smart"
    PROCESS_CRASH = "process_crash"


class ActionType(Enum):
    """处置动作类型"""
    RESTART_SERVICE = "restart_service"
    CLEAR_LOGS = "clear_logs"
    KILL_PROCESS = "kill_process"
    NONE = "none"


@dataclass
class SystemMetrics:
    """系统指标快照"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_total_mb: float
    disk_percent: float
    disk_used_gb: float
    disk_total_gb: float
    load_1m: float
    load_5m: float
    load_15m: float
    cpu_count: int
    uptime_seconds: float
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0


@dataclass
class ServiceStatus:
    """服务状态"""
    name: str
    running: bool
    pid: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None


@dataclass
class LogEntry:
    """日志条目"""
    timestamp: datetime
    source: str
    level: str
    message: str


@dataclass
class Issue:
    """检测到的问题"""
    id: str
    timestamp: datetime
    severity: Severity
    issue_type: IssueType
    title: str
    description: str
    details: dict = field(default_factory=dict)


@dataclass
class RemediationAction:
    """处置动作"""
    action_type: ActionType
    target: str
    command: str
    issue_id: str


@dataclass
class RemediationResult:
    """处置结果"""
    action: RemediationAction
    success: bool
    output: str
    timestamp: datetime


@dataclass
class IncidentRecord:
    """事件记录（用于记忆存储）"""
    issue: Issue
    root_cause: str
    action_taken: Optional[RemediationResult]
    resolved: bool
    duration_seconds: float
    lessons: str


@dataclass
class ContainerMetrics:
    """Docker 容器指标"""
    id: str
    name: str
    image: str
    status: str
    health: str
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    memory_percent: float
    net_rx_bytes: int
    net_tx_bytes: int
    restart_count: int
