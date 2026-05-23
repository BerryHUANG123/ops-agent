"""DockerCollector 单元测试"""
import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from src.collectors.docker_collector import ContainerInfo, DockerCollector


class TestDockerCollector(unittest.TestCase):
    """DockerCollector 测试"""

    def setUp(self) -> None:
        self.collector = DockerCollector()

    # --- is_available ---

    @patch("src.collectors.docker_collector.subprocess.run")
    def test_is_available_no_docker(self, mock_run: MagicMock) -> None:
        """docker 不可用时返回 False"""
        mock_run.side_effect = FileNotFoundError("docker not found")
        self.collector._available = None
        result = self.collector.is_available()
        self.assertFalse(result)

    @patch("src.collectors.docker_collector.subprocess.run")
    def test_is_available_docker_present(self, mock_run: MagicMock) -> None:
        """docker 可用时返回 True"""
        mock_run.return_value = MagicMock(returncode=0)
        self.collector._available = None
        result = self.collector.is_available()
        self.assertTrue(result)

    # --- _parse_percent ---

    def test_parse_percent(self) -> None:
        """百分比解析"""
        self.assertEqual(DockerCollector._parse_percent("45.2%"), 45.2)
        self.assertEqual(DockerCollector._parse_percent("0%"), 0.0)
        self.assertEqual(DockerCollector._parse_percent("100%"), 100.0)
        self.assertEqual(DockerCollector._parse_percent("abc"), 0.0)

    # --- _parse_mb ---

    def test_parse_mb(self) -> None:
        """内存解析"""
        self.assertAlmostEqual(DockerCollector._parse_mb("128.5MiB"), 128.5, places=1)
        self.assertAlmostEqual(DockerCollector._parse_mb("1.5GiB"), 1536.0, places=0)
        self.assertAlmostEqual(DockerCollector._parse_mb("512KiB"), 0.5, places=1)
        self.assertAlmostEqual(DockerCollector._parse_mb("1048576B"), 1.0, places=1)
        self.assertEqual(DockerCollector._parse_mb("abc"), 0.0)

    # --- _parse_bytes ---

    def test_parse_bytes(self) -> None:
        """字节数解析"""
        self.assertEqual(DockerCollector._parse_bytes("1.5GB"), int(1.5 * 1024 * 1024 * 1024))
        self.assertEqual(DockerCollector._parse_bytes("100MB"), 100 * 1024 * 1024)
        self.assertEqual(DockerCollector._parse_bytes("500KB"), 500 * 1024)
        self.assertEqual(DockerCollector._parse_bytes("1024B"), 1024)
        self.assertEqual(DockerCollector._parse_bytes("abc"), 0)

    # --- _parse_container ---

    def test_parse_container(self) -> None:
        """容器信息解析"""
        data = {
            "ID": "abc123def456",
            "Names": "nginx-proxy",
            "Image": "nginx:latest",
            "State": "running",
            "Status": "Up 2 hours (healthy)",
            "RunningFor": "2 hours ago",
            "Ports": "0.0.0.0:80->80/tcp",
        }
        info = self.collector._parse_container(data)
        self.assertEqual(info.id, "abc123def456")
        self.assertEqual(info.name, "nginx-proxy")
        self.assertEqual(info.image, "nginx:latest")
        self.assertEqual(info.status, "running")
        self.assertEqual(info.health, "healthy")
        self.assertEqual(info.ports, "0.0.0.0:80->80/tcp")

    def test_parse_container_unhealthy(self) -> None:
        """容器 unhealthy 状态解析"""
        data = {
            "ID": "xyz789",
            "Names": "app",
            "Image": "app:v1",
            "State": "running",
            "Status": "Up 5 minutes (unhealthy)",
            "RunningFor": "5 minutes ago",
            "Ports": "",
        }
        info = self.collector._parse_container(data)
        self.assertEqual(info.health, "unhealthy")

    def test_parse_container_no_health(self) -> None:
        """容器无健康检查时 health 为 none"""
        data = {
            "ID": "def456",
            "Names": "redis",
            "Image": "redis:7",
            "State": "running",
            "Status": "Up 1 hour",
            "RunningFor": "1 hour ago",
            "Ports": "",
        }
        info = self.collector._parse_container(data)
        self.assertEqual(info.health, "none")

    # --- collect_containers ---

    @patch("src.collectors.docker_collector.subprocess.run")
    def test_collect_containers_success(self, mock_run: MagicMock) -> None:
        """成功采集容器"""
        # 第一次调用: docker info
        info_result = MagicMock(returncode=0)
        # 第二次调用: docker ps -a
        ps_data = json.dumps({
            "ID": "abc123def456",
            "Names": "nginx",
            "Image": "nginx:latest",
            "State": "running",
            "Status": "Up 2 hours",
            "RunningFor": "2 hours ago",
            "Ports": "80/tcp",
        })
        ps_result = MagicMock(returncode=0, stdout=ps_data, stderr="")
        # 第三次调用: docker stats
        stats_data = json.dumps({
            "Name": "nginx",
            "CPUPerc": "5.50%",
            "MemUsage": "128.5MiB / 512MiB",
            "MemPerc": "25.10%",
            "NetIO": "1.5MB / 800KB",
            "BlockIO": "100MB / 50MB",
        })
        stats_result = MagicMock(returncode=0, stdout=stats_data, stderr="")

        mock_run.side_effect = [info_result, ps_result, stats_result]
        self.collector._available = None

        containers = self.collector.collect_containers()
        self.assertEqual(len(containers), 1)
        self.assertEqual(containers[0].name, "nginx")
        self.assertEqual(containers[0].cpu_percent, 5.5)
        self.assertAlmostEqual(containers[0].memory_usage_mb, 128.5, places=1)

    @patch("src.collectors.docker_collector.subprocess.run")
    def test_collect_containers_docker_unavailable(self, mock_run: MagicMock) -> None:
        """docker 不可用返回空列表"""
        mock_run.side_effect = FileNotFoundError("docker not found")
        self.collector._available = None

        containers = self.collector.collect_containers()
        self.assertEqual(containers, [])

    # --- collect_container_logs ---

    @patch("src.collectors.docker_collector.subprocess.run")
    def test_collect_container_logs(self, mock_run: MagicMock) -> None:
        """日志采集"""
        # 第一次调用: docker info
        info_result = MagicMock(returncode=0)
        # 第二次调用: docker logs
        logs_result = MagicMock(
            returncode=0,
            stdout="2026-05-23T00:00:00Z Starting server\n2026-05-23T00:01:00Z Ready\n",
            stderr="",
        )
        mock_run.side_effect = [info_result, logs_result]
        self.collector._available = None

        logs = self.collector.collect_container_logs("nginx", lines=100)
        self.assertEqual(len(logs), 2)
        self.assertIn("Starting server", logs[0])


if __name__ == "__main__":
    unittest.main()
