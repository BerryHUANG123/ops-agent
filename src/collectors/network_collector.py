"""网络连接监控采集器"""
import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

import psutil

logger = logging.getLogger(__name__)


@dataclass
class ListeningPort:
    """监听端口信息"""
    port: int
    protocol: str
    process_name: str
    pid: int
    address: str


@dataclass
class NetworkConnection:
    """网络连接信息"""
    fd: int
    family: str
    type: str
    local_addr: str
    local_port: int
    remote_addr: str
    remote_port: int
    status: str
    pid: int
    process_name: str


class NetworkCollector:
    """网络连接监控采集器"""

    def collect_listening_ports(self) -> List[ListeningPort]:
        """采集所有监听端口"""
        results = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'LISTEN':
                    proc_name = ""
                    pid = conn.pid or 0
                    try:
                        if pid:
                            proc_name = psutil.Process(pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    results.append(ListeningPort(
                        port=conn.laddr.port,
                        protocol="tcp" if conn.type == 1 else "udp",
                        process_name=proc_name,
                        pid=pid,
                        address=conn.laddr.ip,
                    ))
        except (psutil.AccessDenied, PermissionError):
            logger.warning("无权限采集网络连接（需要 root 或 netstat 权限）")
        except Exception as e:
            logger.error("采集监听端口失败: %s", e)
        return sorted(results, key=lambda x: x.port)

    def collect_connections(self, max_connections: int = 100) -> List[NetworkConnection]:
        """采集活跃网络连接"""
        results = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'ESTABLISHED':
                    proc_name = ""
                    pid = conn.pid or 0
                    try:
                        if pid:
                            proc_name = psutil.Process(pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    results.append(NetworkConnection(
                        fd=conn.fd,
                        family="inet4" if conn.family.name == "AF_INET" else "inet6",
                        type="tcp" if conn.type == 1 else "udp",
                        local_addr=conn.laddr.ip,
                        local_port=conn.laddr.port,
                        remote_addr=conn.raddr.ip if conn.raddr else "",
                        remote_port=conn.raddr.port if conn.raddr else 0,
                        status=conn.status,
                        pid=pid,
                        process_name=proc_name,
                    ))
                    if len(results) >= max_connections:
                        break
        except (psutil.AccessDenied, PermissionError):
            logger.warning("无权限采集网络连接")
        except Exception as e:
            logger.error("采集网络连接失败: %s", e)
        return results

    def detect_suspicious(self, config: dict) -> list:
        """检测可疑网络连接"""
        issues = []
        allowed_ports = set(config.get("network", {}).get("allowed_ports", []))
        suspicious_processes = set(config.get("network", {}).get("suspicious_processes", []))

        # 检查非白名单端口的监听
        for port_info in self.collect_listening_ports():
            if allowed_ports and port_info.port not in allowed_ports and port_info.port > 1024:
                # 高端口非白名单监听，可能是后门
                if port_info.process_name not in ("python3", "node", "sshd"):
                    issues.append({
                        "type": "suspicious_port",
                        "severity": "warning",
                        "title": f"非白名单端口监听: :{port_info.port}",
                        "description": f"进程 {port_info.process_name} (PID {port_info.pid}) 监听端口 {port_info.port}",
                        "details": {
                            "port": port_info.port,
                            "process": port_info.process_name,
                            "pid": port_info.pid,
                            "address": port_info.address,
                        },
                    })

            # 检查可疑进程
            if suspicious_processes and port_info.process_name in suspicious_processes:
                issues.append({
                    "type": "suspicious_process",
                    "severity": "critical",
                    "title": f"可疑进程监听: {port_info.process_name}",
                    "description": f"可疑进程 {port_info.process_name} (PID {port_info.pid}) 监听端口 {port_info.port}",
                    "details": {
                        "port": port_info.port,
                        "process": port_info.process_name,
                        "pid": port_info.pid,
                    },
                })

        return issues
