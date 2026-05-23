"""Docker 容器状态与资源采集器"""
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContainerInfo:
    """容器信息"""
    id: str
    name: str
    image: str
    status: str          # running, exited, restarting, paused, dead
    health: str          # healthy, unhealthy, starting, none
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    memory_percent: float
    net_rx_bytes: int
    net_tx_bytes: int
    block_read_bytes: int
    block_write_bytes: int
    restart_count: int
    uptime: str
    ports: str


class DockerCollector:
    """Docker 容器采集器（通过 CLI）"""

    def __init__(self, docker_bin: str = "docker"):
        self.docker_bin = docker_bin
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """检测 docker 是否可用"""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                [self.docker_bin, "info"],
                capture_output=True, timeout=5
            )
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        if not self._available:
            logger.warning("Docker 不可用，跳过容器监控")
        return self._available

    def collect_containers(self) -> List[ContainerInfo]:
        """采集所有容器的运行状态和资源占用"""
        if not self.is_available():
            return []

        try:
            # docker ps -a --format '{{json .}}' 获取所有容器
            result = subprocess.run(
                [self.docker_bin, "ps", "-a", "--format", "{{json .}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.error("docker ps 失败: %s", result.stderr)
                return []

            containers = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    info = self._parse_container(data)
                    containers.append(info)
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("解析容器信息失败: %s", e)
                    continue

            # 获取运行中容器的资源使用
            running = [c for c in containers if c.status == "running"]
            if running:
                self._fill_stats(running)

            return containers

        except subprocess.TimeoutExpired:
            logger.error("docker ps 超时")
            return []
        except Exception as e:
            logger.error("采集容器列表异常: %s", e)
            return []

    def collect_container_logs(self, container_name: str, lines: int = 100) -> List[str]:
        """采集指定容器的最近日志"""
        if not self.is_available():
            return []
        try:
            result = subprocess.run(
                [self.docker_bin, "logs", "--tail", str(lines), "--timestamps", container_name],
                capture_output=True, text=True, timeout=10
            )
            log_lines = (result.stdout + result.stderr).strip().split("\n")
            return [l for l in log_lines if l.strip()]
        except Exception as e:
            logger.error("采集容器日志失败 %s: %s", container_name, e)
            return []

    @staticmethod
    def _parse_health(status: str) -> str:
        """从 Status 字段解析健康状态"""
        status_lower = status.lower()
        if "unhealthy" in status_lower:
            return "unhealthy"
        elif "healthy" in status_lower:
            return "healthy"
        elif "starting" in status_lower:
            return "starting"
        return "none"

    def _parse_container(self, data: dict) -> ContainerInfo:
        """解析 docker ps JSON 输出"""
        return ContainerInfo(
            id=data.get("ID", "")[:12],
            name=data.get("Names", ""),
            image=data.get("Image", ""),
            status=data.get("State", "").lower(),
            health=self._parse_health(data.get("Status", "")),
            cpu_percent=0.0,
            memory_usage_mb=0.0,
            memory_limit_mb=0.0,
            memory_percent=0.0,
            net_rx_bytes=0,
            net_tx_bytes=0,
            block_read_bytes=0,
            block_write_bytes=0,
            restart_count=int(data.get("RunningFor", "0").split()[0]) if data.get("RunningFor") else 0,
            uptime=data.get("Status", ""),
            ports=data.get("Ports", ""),
        )

    def _fill_stats(self, containers: List[ContainerInfo]) -> None:
        """通过 docker stats --no-stream 获取资源使用"""
        try:
            names = [c.name for c in containers]
            result = subprocess.run(
                [self.docker_bin, "stats", "--no-stream", "--format", "{{json .}}"] + names,
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                logger.warning("docker stats 失败: %s", result.stderr)
                return

            stats_map: Dict[str, dict] = {}
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    s = json.loads(line)
                    stats_map[s.get("Name", "")] = s
                except json.JSONDecodeError:
                    continue

            for c in containers:
                s = stats_map.get(c.name)
                if not s:
                    continue
                c.cpu_percent = self._parse_percent(s.get("CPUPerc", "0%"))
                c.memory_usage_mb = self._parse_mb(s.get("MemUsage", "0B / 0B").split("/")[0])
                c.memory_limit_mb = self._parse_mb(s.get("MemUsage", "0B / 0B").split("/")[1] if "/" in s.get("MemUsage", "") else "0B")
                c.memory_percent = self._parse_percent(s.get("MemPerc", "0%"))
                c.net_rx_bytes = self._parse_bytes(s.get("NetIO", "0B / 0B").split("/")[0])
                c.net_tx_bytes = self._parse_bytes(s.get("NetIO", "0B / 0B").split("/")[1] if "/" in s.get("NetIO", "") else "0B")
                c.block_read_bytes = self._parse_bytes(s.get("BlockIO", "0B / 0B").split("/")[0])
                c.block_write_bytes = self._parse_bytes(s.get("BlockIO", "0B / 0B").split("/")[1] if "/" in s.get("BlockIO", "") else "0B")

        except subprocess.TimeoutExpired:
            logger.warning("docker stats 超时")
        except Exception as e:
            logger.error("获取容器资源占用异常: %s", e)

    @staticmethod
    def _parse_percent(s: str) -> float:
        """解析百分比字符串 '45.2%' -> 45.2"""
        try:
            return float(s.strip().rstrip("%"))
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_mb(s: str) -> float:
        """解析内存字符串 '128.5MiB' -> 128.5"""
        s = s.strip()
        try:
            if s.endswith("GiB"):
                return float(s[:-3]) * 1024
            elif s.endswith("MiB"):
                return float(s[:-3])
            elif s.endswith("KiB"):
                return float(s[:-3]) / 1024
            elif s.endswith("B"):
                return float(s[:-1]) / (1024 * 1024)
            return float(s)
        except ValueError:
            return 0.0

    @staticmethod
    def _parse_bytes(s: str) -> int:
        """解析字节数字符串 '1.5GB' -> bytes"""
        s = s.strip()
        try:
            if s.endswith("GB"):
                return int(float(s[:-2]) * 1024 * 1024 * 1024)
            elif s.endswith("MB"):
                return int(float(s[:-2]) * 1024 * 1024)
            elif s.endswith("KB"):
                return int(float(s[:-2]) * 1024)
            elif s.endswith("B"):
                return int(s[:-1])
            return int(float(s))
        except ValueError:
            return 0
