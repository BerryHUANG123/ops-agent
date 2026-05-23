"""故障分析器 — 基于规则推断根因，关联分析多 Issue"""
import logging
from typing import Dict, List, Optional

from src.models import Issue, IssueType, Severity

logger = logging.getLogger(__name__)


class FaultAnalyzer:
    """基于规则的故障根因分析器"""

    # 根因规则映射：issue_type → 可能的根因
    ROOT_CAUSE_RULES: Dict[IssueType, List[str]] = {
        IssueType.MEMORY_HIGH: [
            "内存泄漏（进程持续占用不释放）",
            "系统内存不足，swap 使用率高",
            "大进程或缓存占用过多内存",
        ],
        IssueType.CPU_HIGH: [
            "CPU 密集型进程持续运行",
            "死循环或异常计算任务",
            "并发请求过多导致 CPU 打满",
        ],
        IssueType.DISK_HIGH: [
            "日志文件持续增长未轮转",
            "临时文件堆积未清理",
            "大文件或备份占用磁盘空间",
        ],
        IssueType.LOAD_HIGH: [
            "大量进程排队等待 CPU 时间片",
            "IO 等待导致负载升高",
            "磁盘性能瓶颈引发负载飙升",
        ],
        IssueType.SERVICE_DOWN: [
            "进程崩溃（OOM 或 segfault）",
            "配置错误导致启动失败",
            "依赖服务不可用引发级联故障",
        ],
        IssueType.LOG_ERROR: [
            "应用逻辑错误触发异常",
            "外部依赖不可达（网络/数据库）",
            "权限或配置问题",
        ],
        IssueType.PROCESS_CRASH: [
            "OOM Killer 终止进程",
            "段错误（内存访问越界）",
            "未捕获的异常导致进程退出",
        ],
    }

    # 关联规则：当多个 Issue 同时出现时的共同根因
    CORRELATION_RULES = [
        {
            "triggers": [IssueType.MEMORY_HIGH, IssueType.SERVICE_DOWN],
            "root_cause": "内存不足导致进程被 OOM Killer 终止",
            "category": "资源类",
        },
        {
            "triggers": [IssueType.DISK_HIGH, IssueType.LOG_ERROR],
            "root_cause": "磁盘空间不足导致日志写入失败，触发应用错误",
            "category": "资源类",
        },
        {
            "triggers": [IssueType.CPU_HIGH, IssueType.LOAD_HIGH],
            "root_cause": "CPU 密集型任务导致系统负载飙升",
            "category": "资源类",
        },
        {
            "triggers": [IssueType.MEMORY_HIGH, IssueType.CPU_HIGH],
            "root_cause": "内存不足引发频繁 swap，CPU 等待 IO 导致使用率升高",
            "category": "资源类",
        },
        {
            "triggers": [IssueType.SERVICE_DOWN, IssueType.LOG_ERROR],
            "root_cause": "服务崩溃产生的错误日志",
            "category": "服务类",
        },
    ]

    def analyze(self, issues: List[Issue], history: Optional[List[dict]] = None) -> dict:
        """分析故障根因

        Args:
            issues: 当前检测到的 Issue 列表
            history: 历史事件记录（可选，用于趋势分析）

        Returns:
            dict: 分析结果，包含 root_causes、category、suggestions
        """
        if not issues:
            return {
                "root_causes": [],
                "category": "正常",
                "suggestions": ["系统运行正常，无需处置"],
                "correlated": False,
                "issue_count": 0,
                "critical_count": 0,
            }

        # 1. 关联分析：检查是否有多个 Issue 存在共同根因
        correlated_causes = self._correlate_issues(issues)

        # 2. 单 Issue 根因推断
        individual_causes = []
        for issue in issues:
            causes = self.ROOT_CAUSE_RULES.get(issue.issue_type, ["未知原因"])
            individual_causes.append({
                "issue_id": issue.id,
                "issue_type": issue.issue_type.value,
                "title": issue.title,
                "possible_causes": causes,
                "severity": issue.severity.value,
            })

        # 3. 分类统计
        categories = self._classify_issues(issues)

        # 4. 生成建议
        suggestions = self._generate_suggestions(issues, correlated_causes)

        # 5. 趋势分析（如果有历史数据）
        trend = self._analyze_trend(issues, history) if history else None

        result = {
            "root_causes": correlated_causes if correlated_causes else individual_causes,
            "category": categories,
            "suggestions": suggestions,
            "correlated": len(correlated_causes) > 0,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i.severity == Severity.CRITICAL),
        }
        if trend:
            result["trend"] = trend

        logger.info(
            "故障分析完成: %d 个问题, 关联分析=%s, 分类=%s",
            len(issues), result["correlated"], categories,
        )
        return result

    def _correlate_issues(self, issues: List[Issue]) -> List[dict]:
        """关联分析：检查多个 Issue 是否有共同根因

        Args:
            issues: Issue 列表

        Returns:
            List[dict]: 关联根因列表
        """
        issue_types = set(i.issue_type for i in issues)
        correlated = []

        for rule in self.CORRELATION_RULES:
            triggers = set(rule["triggers"])
            if triggers.issubset(issue_types):
                matched_issues = [i for i in issues if i.issue_type in triggers]
                correlated.append({
                    "root_cause": rule["root_cause"],
                    "category": rule["category"],
                    "triggered_by": [i.title for i in matched_issues],
                    "severity": "critical",  # 关联问题默认 critical
                })

        return correlated

    @staticmethod
    def _classify_issues(issues: List[Issue]) -> str:
        """按类型分类统计，返回主要分类

        Args:
            issues: Issue 列表

        Returns:
            str: 主要分类名称
        """
        type_counts: Dict[str, int] = {}
        for issue in issues:
            cat = issue.issue_type.value
            type_counts[cat] = type_counts.get(cat, 0) + 1

        if not type_counts:
            return "正常"

        # 按数量排序，返回最多的分类
        sorted_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)
        primary = sorted_types[0][0]

        # 归类到大类
        resource_types = {"cpu_high", "memory_high", "disk_high", "load_high"}
        service_types = {"service_down", "process_crash"}
        log_types = {"log_error"}

        if primary in resource_types:
            return "资源类"
        elif primary in service_types:
            return "服务类"
        elif primary in log_types:
            return "日志类"
        return "其他"

    def _generate_suggestions(self, issues: List[Issue], correlated: List[dict]) -> List[str]:
        """根据问题类型生成处置建议

        Args:
            issues: Issue 列表
            correlated: 关联分析结果

        Returns:
            List[str]: 建议列表
        """
        suggestions: List[str] = []
        seen_types: set = set()

        for issue in issues:
            if issue.issue_type in seen_types:
                continue
            seen_types.add(issue.issue_type)

            if issue.issue_type == IssueType.CPU_HIGH:
                suggestions.append("排查 CPU 占用最高的进程（top/htop），必要时限制或重启")
            elif issue.issue_type == IssueType.MEMORY_HIGH:
                suggestions.append("检查内存占用进程，清理缓存（echo 3 > /proc/sys/vm/drop_caches），或增加 swap")
            elif issue.issue_type == IssueType.DISK_HIGH:
                suggestions.append("清理过期日志和临时文件，检查是否有大文件堆积")
            elif issue.issue_type == IssueType.LOAD_HIGH:
                suggestions.append("排查 IO 等待（iostat），检查是否有大量磁盘读写")
            elif issue.issue_type == IssueType.SERVICE_DOWN:
                suggestions.append(f"尝试重启服务: systemctl restart {issue.details.get('service_name', 'unknown')}")
            elif issue.issue_type == IssueType.LOG_ERROR:
                suggestions.append("检查错误日志详情，定位应用层问题")
            elif issue.issue_type == IssueType.PROCESS_CRASH:
                suggestions.append("检查 dmesg 是否有 OOM 记录，分析 coredump")

        if correlated:
            suggestions.append("检测到多指标关联异常，建议优先解决根因而非逐个处理症状")

        return suggestions if suggestions else ["无特殊建议"]

    @staticmethod
    def _analyze_trend(issues: List[Issue], history: List[dict]) -> Optional[dict]:
        """趋势分析：对比历史数据判断恶化/改善

        Args:
            issues: 当前 Issue 列表
            history: 历史记录

        Returns:
            Optional[dict]: 趋势信息
        """
        if len(history) < 2:
            return None

        recent_counts = [h.get("issue_count", 0) for h in history[-5:]]
        current_count = len(issues)
        avg_recent = sum(recent_counts) / len(recent_counts) if recent_counts else 0

        if current_count > avg_recent * 1.5:
            return {"direction": "恶化", "current": current_count, "average": round(avg_recent, 1)}
        elif current_count < avg_recent * 0.5:
            return {"direction": "改善", "current": current_count, "average": round(avg_recent, 1)}
        return {"direction": "稳定", "current": current_count, "average": round(avg_recent, 1)}
