from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field

from miair.identity import (
    LEGACY_PRODUCT_NAMES,
    format_device_name,
    normalize_device_prefix,
)
from miair.targets import OutputTargetConfig, normalize_target_id


log = logging.getLogger("miair")


@dataclass
class Speaker:
    """单个小爱音箱的配置"""

    did: str = ""
    device_id: str = ""
    hardware: str = ""
    name: str = ""
    dlna_name: str = ""
    udn: str = ""
    use_music_api: bool = False
    compatibility_mode: bool | None = None
    local_dlna_location: str = ""
    enabled: bool = True

    # 不支持无损格式的音箱型号列表
    _NON_LOSSLESS_HARDWARE = {"L05B", "L05C", "LX06", "L16A"}

    def is_compatibility_mode(self) -> bool:
        if self.compatibility_mode is not None:
            return self.compatibility_mode
        # 默认：如果 hardware 在 NEED_USE_PLAY_MUSIC_API 中，则为 False，否则为 True
        from miair.const import NEED_USE_PLAY_MUSIC_API
        for model in NEED_USE_PLAY_MUSIC_API:
            if model in self.hardware:
                return False
        return True

    def get_dlna_name(self) -> str:
        return self.dlna_name or self.name or f"XiaoAI-{self.did}"

    def ensure_udn(self):
        if not self.udn:
            self.udn = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"miair-{self.did}"))

    def needs_audio_conversion(self, content_type: str = "") -> bool:
        """检查是否需要转换音频格式
        
        部分音箱不支持无损格式，需要转换为 WAV (PCM) 播放
        """
        if self.hardware not in self._NON_LOSSLESS_HARDWARE:
            return False
        
        # 已经是可直接播放的格式则不需要转换
        if content_type:
            ct = content_type.lower()
            if "mp3" in ct or "mpeg" in ct or "wav" in ct or "x-wav" in ct:
                return False
        
        return True


@dataclass
class Config:
    """CastFabric 全局配置（兼容旧 MiAir/OpenXiaoCast 字段）。"""

    account: str = ""
    password: str = ""
    mi_did: str = ""
    cookie: str = ""
    hostname: str = ""
    dlna_port: int = 8200
    web_port: int = 8300
    conf_path: str = "conf"
    verbose: bool = False
    # log_file 不存储，动态计算相对于 conf_path
    proxy_enabled: bool = False
    auto_play_on_set_uri: bool = False
    # 实验性功能：打断后续播
    auto_resume_on_interrupt: bool = False
    resume_delay_seconds: int = 5
    # 默认音量 (1-100)
    default_volume: int = 38
    # 实验性功能：跟随设备当前音量
    follow_device_volume: bool = True
    # 语音控制
    enable_voice_control: bool = False
    # 自动重启（当登录失败或服务异常时）
    auto_restart: bool = False
    voice_poll_interval: int = 1
    # MiPlay 原生接收入口
    enable_miplay: bool = True
    miplay_port: int = 8899
    # 所有局域网投放入口共享的设备名称前缀。
    device_name_prefix: str = ""
    # 旧字段，迁移期继续读写并始终镜像 device_name_prefix。
    miplay_name: str = ""
    # player_play_url 的播放类型。仅用于 MiPlay 实时流实验；DLNA/AirPlay 保持默认值 2。
    miplay_play_type: int = 2
    # MiPlay 实时 WAV 的 HTTP 方式：close、content-length 或 range。
    miplay_http_mode: str = "close"
    # WAV MIME 对照实验；不改变 WAV/PCM 内容。
    miplay_content_type: str = "audio/wav"
    # MiPlay 到音箱的实时音频封装：wav 或标准 raw L16。
    miplay_stream_format: str = "wav"
    # Vendor-neutral playback targets. Legacy speakers remain during migration.
    default_target_id: str = ""
    targets: dict = field(default_factory=dict)
    speakers: dict = field(default_factory=dict)

    # 保存配置的线程锁（类级别共享）
    _save_lock = threading.Lock()

    @property
    def log_file(self) -> str:
        """日志文件路径，动态计算"""
        return os.path.join(self.conf_path, "miair.log")

    def __post_init__(self):
        self.resume_delay_seconds = max(1, min(15, self.resume_delay_seconds))
        self.miplay_port = max(0, min(65535, int(self.miplay_port)))
        requested_prefix = str(self.device_name_prefix or "").strip()
        legacy_miplay_name = str(self.miplay_name or "").strip()
        if not requested_prefix and legacy_miplay_name not in LEGACY_PRODUCT_NAMES:
            requested_prefix = legacy_miplay_name
        self.device_name_prefix = normalize_device_prefix(requested_prefix)
        self.miplay_name = self.device_name_prefix
        try:
            self.miplay_play_type = int(self.miplay_play_type)
        except (TypeError, ValueError):
            self.miplay_play_type = 2
        if self.miplay_play_type not in (0, 1, 2):
            self.miplay_play_type = 2
        self.miplay_http_mode = str(self.miplay_http_mode or "close").lower()
        if self.miplay_http_mode not in ("close", "content-length", "range"):
            self.miplay_http_mode = "close"
        self.miplay_content_type = str(
            self.miplay_content_type or "audio/wav"
        ).lower()
        if self.miplay_content_type not in ("audio/wav", "audio/x-wav"):
            self.miplay_content_type = "audio/wav"
        self.miplay_stream_format = str(
            self.miplay_stream_format or "wav"
        ).lower()
        if self.miplay_stream_format not in ("wav", "l16"):
            self.miplay_stream_format = "wav"
        if not self.account:
            self.account = os.getenv("MI_USER", "")
        if not self.password:
            self.password = os.getenv("MI_PASS", "")
        if not self.mi_did:
            self.mi_did = os.getenv("MI_DID", "")
        env_hostname = os.getenv("MIAIR_HOSTNAME", "").strip()
        if env_hostname:
            self.hostname = env_hostname
        if not self.hostname:
            self.hostname = self._detect_local_ip()
        self._normalize_targets()
        self._migrate_legacy_targets()

    def get_device_name(self, target_name: str = "") -> str:
        """返回各输入协议统一使用的可发现设备名称。"""
        return format_device_name(self.device_name_prefix, target_name)

    def _normalize_targets(self) -> None:
        normalized = {}
        for key, value in self.targets.items():
            if isinstance(value, OutputTargetConfig):
                target = value
            else:
                payload = dict(value)
                payload.setdefault("id", key)
                target = OutputTargetConfig(**payload)
            normalized[target.id] = target
        self.targets = normalized
        self.default_target_id = normalize_target_id(self.default_target_id)

    def _migrate_legacy_targets(self) -> None:
        """Create compatibility targets without deleting legacy speaker data."""
        if not self.targets:
            for did in self.get_did_list():
                speaker = self.get_speaker(did)
                if not speaker.device_id:
                    continue
                target_id = normalize_target_id(speaker.device_id)
                self.targets[target_id] = OutputTargetConfig(
                    id=target_id,
                    kind="dlna",
                    name=speaker.get_dlna_name(),
                    location=speaker.local_dlna_location,
                    udn=target_id,
                    enabled=speaker.enabled,
                    virtual_udn=speaker.udn,
                    legacy_did=did,
                )
        if not self.default_target_id:
            enabled = self.get_enabled_targets()
            if enabled:
                self.default_target_id = enabled[0].id

    def get_target(self, target_id: str) -> OutputTargetConfig | None:
        normalized_id = normalize_target_id(target_id)
        target = self.targets.get(normalized_id)
        if isinstance(target, dict):
            target = OutputTargetConfig(id=normalized_id, **target)
            self.targets[normalized_id] = target
        return target

    def get_enabled_targets(self) -> list[OutputTargetConfig]:
        result = []
        for target_id in list(self.targets):
            target = self.get_target(target_id)
            if target and target.enabled:
                result.append(target)
        return result

    def get_default_target(self) -> OutputTargetConfig | None:
        target = self.get_target(self.default_target_id)
        if target and target.enabled:
            return target
        enabled = self.get_enabled_targets()
        return enabled[0] if enabled else None

    @staticmethod
    def _detect_local_ip() -> str:
        """自动检测本机局域网 IP，避免多网卡时误选默认 WAN 出口。"""
        candidates = Config._collect_local_ipv4_candidates()
        usable = []
        seen = set()
        for ip, source in candidates:
            if ip in seen or not Config._is_usable_local_ipv4(ip):
                continue
            seen.add(ip)
            usable.append((ip, source, Config._score_local_ipv4(ip, source)))

        if usable:
            usable.sort(key=lambda item: item[2], reverse=True)
            selected = usable[0][0]
            summary = ", ".join(f"{ip}({source})" for ip, source, _ in usable[:6])
            log.info(f"自动检测局域网 IP: {selected}; 候选: {summary}")
            return selected

        ip = Config._detect_default_route_ip()
        if Config._is_usable_local_ipv4(ip):
            log.info(f"自动检测局域网 IP fallback: {ip}")
            return ip
        return "127.0.0.1"

    @staticmethod
    def _collect_local_ipv4_candidates() -> list[tuple[str, str]]:
        """枚举本机 IPv4 候选地址，返回 (ip, 来源/接口名)。"""
        candidates: list[tuple[str, str]] = []

        # Linux/OpenWrt: 最可靠，可拿到接口名用于降低 Docker/VPN 等虚拟网卡优先级。
        candidates.extend(Config._collect_from_ip_addr())

        # Windows/macOS fallback: 解析系统网络配置输出。
        candidates.extend(Config._collect_from_ipconfig())
        candidates.extend(Config._collect_from_ifconfig())

        # 标准库 fallback: 不依赖外部命令，但通常拿不到接口名。
        for host in {socket.gethostname(), socket.getfqdn()}:
            if not host:
                continue
            try:
                infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
            except OSError:
                continue
            for info in infos:
                candidates.append((info[4][0], f"hostname:{host}"))

        # 最后保留旧逻辑作为 fallback 候选，不能作为唯一的首选依据。
        candidates.append((Config._detect_default_route_ip(), "default-route"))
        return candidates

    @staticmethod
    def _collect_from_ip_addr() -> list[tuple[str, str]]:
        try:
            proc = subprocess.run(
                ["ip", "-o", "-4", "addr", "show", "scope", "global"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        result = []
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4:
                result.append((parts[3].split("/", 1)[0], parts[1]))
        return result

    @staticmethod
    def _collect_from_ipconfig() -> list[tuple[str, str]]:
        try:
            proc = subprocess.run(
                ["ipconfig"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        result = []
        adapter = "ipconfig"
        for raw_line in proc.stdout.splitlines():
            line = raw_line.strip()
            if line.endswith(":") and not re.search(r"\d+\.\d+\.\d+\.\d+", line):
                adapter = line[:-1]
            if "ipv4" not in line.lower():
                continue
            match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            if match:
                result.append((match.group(1), adapter))
        return result

    @staticmethod
    def _collect_from_ifconfig() -> list[tuple[str, str]]:
        try:
            proc = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        result = []
        iface = "ifconfig"
        for raw_line in proc.stdout.splitlines():
            if raw_line and not raw_line[0].isspace():
                iface = raw_line.split(":", 1)[0].strip()
            match = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})", raw_line)
            if match:
                result.append((match.group(1), iface))
        return result

    @staticmethod
    def _detect_default_route_ip() -> str:
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            if s:
                s.close()

    @staticmethod
    def _is_usable_local_ipv4(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return not (
            addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
            or addr.is_reserved
        )

    @staticmethod
    def _score_local_ipv4(ip: str, source: str = "") -> int:
        addr = ipaddress.ip_address(ip)
        source_lower = source.lower()
        score = 0
        if addr.is_private:
            score += 100
        if ip.startswith("192.168."):
            score += 50
        elif ip.startswith("10."):
            score += 40
        elif ipaddress.ip_address("172.16.0.0") <= addr <= ipaddress.ip_address("172.31.255.255"):
            score += 30

        virtual_markers = (
            "docker", "veth", "br-", "vmware", "virtualbox", "vbox", "hyper-v",
            "wsl", "tailscale", "zerotier", "vpn", "tun", "tap", "wg", "ppp",
            "utun", "awdl", "llw", "anpi",
        )
        if any(marker in source_lower for marker in virtual_markers):
            score -= 120
        if ip.startswith("172.17.") or ip.startswith("172.18."):
            score -= 30
        if source_lower == "default-route":
            score -= 20
        return score

    @property
    def mi_token_home(self) -> str:
        return os.path.join(self.conf_path, ".mi.token")

    @property
    def config_file(self) -> str:
        return os.path.join(self.conf_path, "config.json")

    def get_did_list(self) -> list[str]:
        """获取配置的设备 DID 列表"""
        if not self.mi_did:
            return []
        return [d.strip() for d in self.mi_did.split(",") if d.strip()]

    def get_speaker(self, did: str) -> Speaker:
        """获取或创建指定 DID 的 Speaker 配置"""
        if did not in self.speakers:
            self.speakers[did] = Speaker(did=did)
        speaker = self.speakers[did]
        if isinstance(speaker, dict):
            speaker = Speaker(**speaker)
            self.speakers[did] = speaker
        speaker.ensure_udn()
        return speaker

    def get_enabled_speakers(self) -> list[Speaker]:
        """获取所有已启用的 Speaker"""
        result = []
        for did in self.get_did_list():
            speaker = self.get_speaker(did)
            if speaker.enabled:
                result.append(speaker)
        return result

    def save(self):
        """保存配置到文件（线程安全）"""
        with self._save_lock:
            os.makedirs(self.conf_path, exist_ok=True)
            data = asdict(self)
            # speakers 中的 Speaker 对象转为 dict
            speakers_data = {}
            for did, speaker in data.get("speakers", {}).items():
                if isinstance(speaker, Speaker):
                    speakers_data[did] = asdict(speaker)
                else:
                    speakers_data[did] = speaker
            data["speakers"] = speakers_data

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, conf_path: str = "conf") -> "Config":
        """从文件加载配置"""
        # 标准化路径为绝对路径，确保无论从哪里运行都能正确定位
        if not os.path.isabs(conf_path):
            conf_path = os.path.abspath(conf_path)
        config_file = os.path.join(conf_path, "config.json")
        if os.path.exists(config_file):
            with open(config_file, encoding="utf-8") as f:
                data = json.load(f)
            data["conf_path"] = conf_path
            # 过滤掉不存在的字段，避免TypeError
            import inspect
            sig = inspect.signature(cls.__init__)
            valid_params = list(sig.parameters.keys())
            filtered_data = {k: v for k, v in data.items() if k in valid_params}
            return cls(**filtered_data)
        return cls(conf_path=conf_path)
