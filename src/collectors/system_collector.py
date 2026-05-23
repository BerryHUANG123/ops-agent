"""系统指标采集器 — 采集 CPU、内存、磁盘、负载、网络、uptime"""
import logging
import time
from typing import List

import psutil

from src.models import SystemMetrics, ServiceStatus

logger = logging.getLogger(__name__)


class SystemCollector:
    """系统指标采集器，基于 psutil 实现"""

    def collect_metrics(self) -> SystemMetrics:
        """采集当前系统指标快照

        Returns:
            SystemMetrics: 包含 CPU、内存、磁盘、负载、网络、uptime 的完整指标
        """
        try:
            # CPU 使用率，采样 1 秒
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count(logical=True)

            # 内存信息
            mem = psutil.virtual_memory()
            memory_percent = mem.percent
            memory_used_mb = mem.used / (1024 * 1024)
            memory_total_mb = mem.total / (1024 * 1024)

            # 磁盘信息（根分区）
            disk = psutil.disk_usage("/")
            disk_percent = disk.percent
            disk_used_gb = disk.used / (1024 ** 3)
            disk_total_gb = disk.total / (1024 ** 3)

            # 负载（Linux/macOS）
            try:
                load_1m, load_5m, load_15m = psutil.getloadavg()
            except (OSError, AttributeError):
                # Windows 等不支持 getloadavg 的平台，用 CPU 数模拟
                load_1m = load_5m = load_15m = cpu_percent / 100.0 * cpu_count

            # 系统启动时间
            uptime_seconds = time.time() - psutil.boot_time()

            # 网络 IO
            net = psutil.net_io_counters()
            network_bytes_sent = net.bytes_sent
            network_bytes_recv = net.bytes_recv

            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=round(memory_used_mb, 2),
                memory_total_mb=round(memory_total_mb, 2),
                disk_percent=disk_percent,
                disk_used_gb=round(disk_used_gb, 2),
                disk_total_gb=round(disk_total_gb, 2),
                load_1m=round(load_1m, 2),
                load_5m=round(load_5m, 2),
                load_15m=round(load_15m, 2),
                cpu_count=cpu_count,
                uptime_seconds=round(uptime_seconds, 0),
                network_bytes_sent=network_bytes_sent,
                network_bytes_recv=network_bytes_recv,
            )
        except Exception as e:
            logger.error("采集系统指标失败: %s", e)
            raise

    def collect_services(self, config: dict) -> List[ServiceStatus]:
        """检查配置中指定的服务进程状态

        Args:
            config: 配置字典，需包含 services.watch 列表

        Returns:
            List[ServiceStatus]: 各服务的运行状态
        """
        services_config = config.get("services", {}).get("watch", [])
        results: List[ServiceStatus] = []

        for svc in services_config:
            name = svc.get("name", "unknown")
            process_name = svc.get("process", name)
            try:
                status = self._check_process(process_name)
                status.name = name
                results.append(status)
            except Exception as e:
                logger.warning("检查服务 %s 失败: %s", name, e)
                results.append(ServiceStatus(name=name, running=False))

        return results

    def _check_process(self, process_name: str) -> ServiceStatus:
        """遍历进程列表，查找匹配的进程名

        Args:
            process_name: 进程名称

        Returns:
            ServiceStatus: 进程运行状态
        """
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                pinfo = proc.info
                if pinfo["name"] and process_name in pinfo["name"]:
                    mem_mb = 0.0
                    if pinfo["memory_info"]:
                        mem_mb = pinfo["memory_info"].rss / (1024 * 1024)
                    return ServiceStatus(
                        name=process_name,
                        running=True,
                        pid=pinfo["pid"],
                        cpu_percent=pinfo.get("cpu_percent", 0.0),
                        memory_mb=round(mem_mb, 2),
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return ServiceStatus(name=process_name, running=False)
