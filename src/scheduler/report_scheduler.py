"""定时报表调度器"""
import logging
import signal
import threading
import time
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ReportScheduler:
    """定时报表调度器

    在独立线程中按配置的时间间隔自动生成报表。
    支持每日定时生成和按间隔生成两种模式。
    """

    def __init__(
        self,
        interval_minutes: int = 1440,  # 默认每天一次
        daily_at: Optional[str] = None,  # 格式 "HH:MM"，如 "08:00"
        on_report: Optional[Callable] = None,  # 回调：生成报表时调用
    ):
        """
        Args:
            interval_minutes: 生成间隔（分钟），daily_at 优先
            daily_at: 每日定时时间（HH:MM），设置后忽略 interval_minutes
            on_report: 回调函数，生成报表时调用，无参数
        """
        self.interval_minutes = interval_minutes
        self.daily_at = daily_at
        self.on_report = on_report
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run: Optional[datetime] = None
        self._run_count = 0

    def start(self) -> None:
        """启动调度器（非阻塞，在后台线程运行）"""
        if self._running:
            logger.warning("调度器已在运行")
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="report-scheduler")
        self._thread.start()
        logger.info(
            "定时报表调度器已启动 (模式=%s, 间隔=%d分钟)",
            "每日定时" if self.daily_at else "间隔触发",
            self.interval_minutes,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """停止调度器"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        logger.info("定时报表调度器已停止 (累计生成 %d 次)", self._run_count)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "running": self._running,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "run_count": self._run_count,
            "mode": "daily" if self.daily_at else "interval",
            "interval_minutes": self.interval_minutes,
        }

    def _run_loop(self) -> None:
        """调度主循环"""
        # 如果设置了每日定时，先等到指定时间
        if self.daily_at:
            self._wait_until_daily()

        while self._running and not self._stop_event.is_set():
            try:
                self._execute_report()
            except Exception as e:
                logger.error("定时报表生成异常: %s", e)

            # 等待下次执行
            if self.daily_at:
                # 等到明天同一时间
                self._wait_until_daily()
            else:
                self._stop_event.wait(timeout=self.interval_minutes * 60)

    def _execute_report(self) -> None:
        """执行一次报表生成"""
        logger.info("触发定时报表生成")
        self._last_run = datetime.now()
        self._run_count += 1

        if self.on_report:
            try:
                self.on_report()
            except Exception as e:
                logger.error("报表回调执行失败: %s", e)
        else:
            logger.warning("未设置报表回调函数")

    def _wait_until_daily(self) -> None:
        """等待到每日指定时间"""
        if not self.daily_at:
            return

        try:
            parts = self.daily_at.split(":")
            target_hour = int(parts[0])
            target_min = int(parts[1])
        except (ValueError, IndexError):
            logger.error("daily_at 格式错误: %s，应为 HH:MM", self.daily_at)
            return

        while self._running and not self._stop_event.is_set():
            now = datetime.now()
            target = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
            if target <= now:
                target += __import__("datetime").timedelta(days=1)

            wait_seconds = (target - now).total_seconds()
            logger.info("下次报表生成时间: %s (等待 %.0f 秒)", target.strftime("%Y-%m-%d %H:%M"), wait_seconds)
            if self._stop_event.wait(timeout=wait_seconds):
                break  # 收到停止信号
            # 到达目标时间，退出等待
            break
