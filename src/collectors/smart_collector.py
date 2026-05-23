"""SMART 磁盘健康监控采集器"""
import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SmartInfo:
    """磁盘 SMART 信息"""
    device: str
    model: str
    health: str           # PASSED / FAILED / UNKNOWN
    temperature: int      # 摄氏度
    power_on_hours: int
    reallocated_sectors: int
    pending_sectors: int   # 待重映射扇区
    uncorrectable: int     # 不可纠正错误
    raw_read_error_rate: int
    seek_error_rate: int


class SmartCollector:
    """SMART 磁盘健康采集器"""

    SMARTCTL = "/usr/sbin/smartctl"

    def __init__(self):
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """检测 smartctl 是否可用"""
        if self._available is not None:
            return self._available
        try:
            result = subprocess.run(
                ["sudo", self.SMARTCTL, "--version"],
                capture_output=True, timeout=5
            )
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        if not self._available:
            logger.warning("smartctl 不可用，跳过 SMART 监控")
        return self._available

    def collect_all(self) -> List[SmartInfo]:
        """采集所有磁盘的 SMART 信息"""
        if not self.is_available():
            return []

        devices = self._get_devices()
        results = []
        for dev in devices:
            info = self._collect_device(dev)
            if info:
                results.append(info)
        return results

    def _get_devices(self) -> List[str]:
        """获取所有磁盘设备列表"""
        try:
            result = subprocess.run(
                ["sudo", self.SMARTCTL, "--scan"],
                capture_output=True, text=True, timeout=10
            )
            devices = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    # 格式: /dev/sda -d sat [SAT] (device type)
                    dev = line.split()[0]
                    if dev.startswith("/dev/"):
                        devices.append(dev)
            return devices
        except Exception as e:
            logger.error("扫描磁盘设备失败: %s", e)
            return []

    def _collect_device(self, device: str) -> Optional[SmartInfo]:
        """采集单个设备的 SMART 信息"""
        try:
            result = subprocess.run(
                ["sudo", self.SMARTCTL, "-a", device],
                capture_output=True, text=True, timeout=15
            )
            output = result.stdout

            model = self._extract_field(output, "Device Model") or self._extract_field(output, "Model Family") or "unknown"
            health = "UNKNOWN"
            if "SMART overall-health self-assessment test result" in output:
                for line in output.split("\n"):
                    if "SMART overall-health" in line or "PASSED" in line or "FAILED" in line:
                        if "PASSED" in line:
                            health = "PASSED"
                        elif "FAILED" in line:
                            health = "FAILED"
                        break

            temperature = self._extract_smart_value(output, "Temperature_Celsius") or 0
            power_on = self._extract_smart_value(output, "Power_On_Hours") or 0
            reallocated = self._extract_smart_value(output, "Reallocated_Sector_Ct") or 0
            pending = self._extract_smart_value(output, "Current_Pending_Sector") or 0
            uncorrectable = self._extract_smart_value(output, "Offline_Uncorrectable") or 0
            raw_read = self._extract_smart_value(output, "Raw_Read_Error_Rate") or 0
            seek_err = self._extract_smart_value(output, "Seek_Error_Rate") or 0

            return SmartInfo(
                device=device,
                model=model.strip(),
                health=health,
                temperature=temperature,
                power_on_hours=power_on,
                reallocated_sectors=reallocated,
                pending_sectors=pending,
                uncorrectable=uncorrectable,
                raw_read_error_rate=raw_read,
                seek_error_rate=seek_err,
            )
        except Exception as e:
            logger.error("采集 SMART 信息失败 %s: %s", device, e)
            return None

    @staticmethod
    def _extract_field(output: str, field: str) -> Optional[str]:
        """从 smartctl 输出中提取字段值"""
        for line in output.split("\n"):
            if field in line and ":" in line:
                return line.split(":", 1)[1].strip()
        return None

    @staticmethod
    def _extract_smart_value(output: str, attr_name: str) -> Optional[int]:
        """从 SMART attributes 表中提取 RAW_VALUE"""
        for line in output.split("\n"):
            if attr_name in line:
                parts = line.split()
                if len(parts) >= 10:
                    # RAW_VALUE 在最后一列
                    try:
                        raw = parts[9].split("_")[0]  # 去掉后缀如 "_0"
                        return int(raw)
                    except (ValueError, IndexError):
                        pass
        return None
