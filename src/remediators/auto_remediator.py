"""自动处置器 — 安全执行白名单内的修复操作"""
import glob
import logging
import os
import subprocess
import time
from typing import List, Optional

from src.models import (
    ActionType,
    Issue,
    IssueType,
    RemediationAction,
    RemediationResult,
)

logger = logging.getLogger(__name__)


class AutoRemediator:
    """自动处置器，只执行白名单内的操作，支持 dry_run"""

    def __init__(self, dry_run: bool = False) -> None:
        """初始化处置器

        Args:
            dry_run: 是否为演练模式（不实际执行命令）
        """
        self.dry_run = dry_run

    def remediate(self, analysis: dict, config: dict) -> List[RemediationResult]:
        """根据分析结果执行自动处置

        Args:
            analysis: FaultAnalyzer 的分析结果
            config: 配置字典

        Returns:
            List[RemediationResult]: 处置结果列表
        """
        remediation_cfg = config.get("remediation", {})
        if not remediation_cfg.get("enabled", True):
            logger.info("自动处置已禁用，跳过")
            return []

        allowed_actions = set(remediation_cfg.get("allowed_actions", []))
        results: List[RemediationResult] = []

        # 从分析结果中提取需要处置的问题
        root_causes = analysis.get("root_causes", [])

        for cause in root_causes:
            actions = self._plan_actions(cause, config, allowed_actions)
            for action in actions:
                result = self._execute_action(action)
                results.append(result)

        logger.info("处置完成: %d 个动作, dry_run=%s", len(results), self.dry_run)
        return results

    def _plan_actions(
        self,
        cause: dict,
        config: dict,
        allowed_actions: set,
    ) -> List[RemediationAction]:
        """根据根因规划处置动作

        Args:
            cause: 根因分析条目
            config: 配置字典
            allowed_actions: 允许的动作类型集合

        Returns:
            List[RemediationAction]: 规划的处置动作列表
        """
        actions: List[RemediationAction] = []
        issue_type = cause.get("issue_type", "")
        issue_id = cause.get("issue_id", "unknown")

        # 服务宕机 → 重启服务
        if issue_type == IssueType.SERVICE_DOWN.value:
            if "restart_service" in allowed_actions:
                svc_name = cause.get("details", {}).get("service_name", "")
                if not svc_name:
                    # 尝试从 title 提取
                    title = cause.get("title", "")
                    if ":" in title:
                        svc_name = title.split(":")[-1].strip()
                if svc_name:
                    actions.append(RemediationAction(
                        action_type=ActionType.RESTART_SERVICE,
                        target=svc_name,
                        command=f"systemctl restart {svc_name}",
                        issue_id=issue_id,
                    ))

        # 磁盘满 → 清理日志
        if issue_type == IssueType.DISK_HIGH.value:
            if "clear_logs" in allowed_actions:
                max_log_size = config.get("remediation", {}).get("max_log_size_mb", 500)
                cleanup_paths = config.get("remediation", {}).get("log_cleanup_paths", [])
                for pattern in cleanup_paths:
                    actions.append(RemediationAction(
                        action_type=ActionType.CLEAR_LOGS,
                        target=pattern,
                        command=f"find {pattern} -size +{max_log_size}M -exec truncate -s 0 {{}} \\;",
                        issue_id=issue_id,
                    ))

        # 进程崩溃 → 杀僵尸进程
        if issue_type == IssueType.PROCESS_CRASH.value:
            if "kill_process" in allowed_actions:
                actions.append(RemediationAction(
                    action_type=ActionType.KILL_PROCESS,
                    target="zombie",
                    command="ps aux | awk '$8 ~ /Z/ {print $2}' | xargs -r kill -9",
                    issue_id=issue_id,
                ))

        return actions

    def _execute_action(self, action: RemediationAction) -> RemediationResult:
        """执行单个处置动作

        Args:
            action: 处置动作

        Returns:
            RemediationResult: 执行结果
        """
        logger.info(
            "[%s] 执行处置: %s -> %s",
            "DRY_RUN" if self.dry_run else "EXEC",
            action.action_type.value,
            action.command,
        )

        if self.dry_run:
            return RemediationResult(
                action=action,
                success=True,
                output=f"[DRY_RUN] 模拟执行: {action.command}",
                timestamp=time.time(),
            )

        try:
            result = subprocess.run(
                action.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            success = result.returncode == 0
            output = result.stdout if success else result.stderr

            if success:
                logger.info("处置成功: %s", action.target)
            else:
                logger.warning("处置失败: %s, 错误: %s", action.target, output[:200])

            return RemediationResult(
                action=action,
                success=success,
                output=output[:1000],  # 截断过长输出
                timestamp=time.time(),
            )
        except subprocess.TimeoutExpired:
            logger.error("处置超时: %s", action.command)
            return RemediationResult(
                action=action,
                success=False,
                output="命令执行超时（30秒）",
                timestamp=time.time(),
            )
        except Exception as e:
            logger.error("处置异常: %s", e)
            return RemediationResult(
                action=action,
                success=False,
                output=str(e),
                timestamp=time.time(),
            )
