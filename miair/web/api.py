"""Web 管理界面 API"""

import json
import logging
import os
import sys
import tarfile
import tempfile
import urllib.request
import urllib.error

from aiohttp import web

import asyncio

from miair.config import Config
from miair.const import VERSION
from miair.dlna.client import DiscoveredDLNATarget, LocalDLNAClient
from miair.targets import OutputTargetConfig, normalize_target_id
from miair.web.api_v1 import setup_api_v1_routes


log = logging.getLogger("miair")


# passToken 在返回给前端时使用的完整脱敏占位符（不是真实凭据）
MASKED_TOKEN = "********"


def _target_view(config: Config, discovered: dict[str, DiscoveredDLNATarget]) -> list[dict]:
    """Merge online discovery with persisted targets for the setup UI."""
    result = {}
    for target_id in list(config.targets):
        target = config.get_target(target_id)
        if target is None:
            continue
        result[target.id] = {
            "id": target.id,
            "kind": target.kind,
            "name": target.name,
            "location": target.location,
            "udn": target.udn,
            "selected": target.enabled,
            "default": target.id == config.default_target_id,
            "online": target.id in discovered,
        }
    for target_id, target in discovered.items():
        item = result.setdefault(
            target_id,
            {
                "id": target.id,
                "kind": "dlna",
                "name": target.name,
                "location": target.location,
                "udn": target.id,
                "selected": False,
                "default": False,
                "online": True,
            },
        )
        item.update(
            name=target.name,
            location=target.location,
            online=True,
        )
    return sorted(result.values(), key=lambda item: (not item["selected"], item["name"].lower()))


def _apply_target_selection(
    config: Config,
    selected_ids: list[str],
    discovered: dict[str, DiscoveredDLNATarget],
    default_target_id: str = "",
) -> None:
    """Persist only targets already configured or observed through SSDP."""
    normalized_ids = []
    for value in selected_ids:
        target_id = normalize_target_id(value)
        if target_id and target_id not in normalized_ids:
            normalized_ids.append(target_id)

    for target in config.get_enabled_targets():
        target.enabled = target.id in normalized_ids

    for target_id in normalized_ids:
        target = config.get_target(target_id)
        if target is None:
            observed = discovered.get(target_id)
            if observed is None:
                raise ValueError(f"target was not discovered: {target_id}")
            target = OutputTargetConfig(
                id=observed.id,
                kind="dlna",
                name=observed.name,
                location=observed.location,
                udn=observed.id,
                enabled=True,
            )
            config.targets[target.id] = target
        else:
            target.enabled = True

    requested_default = normalize_target_id(default_target_id)
    config.default_target_id = (
        requested_default if requested_default in normalized_ids
        else normalized_ids[0] if normalized_ids
        else ""
    )


def _mask_value(key: str, value: str) -> str:
    """按字段生成脱敏后的展示值。

    - passToken: 完整敏感凭据，全部替换为占位符；
    - userId: 仅为账号标识，保留最后 3 位明文，其余用 * 覆盖（如 *****238），
      便于用户确认当前账号又不暴露完整 ID。
    其它字段保持原样。
    """
    if not value:
        return value
    if key == "passToken":
        return MASKED_TOKEN
    if key == "userId":
        if len(value) <= 3:
            return MASKED_TOKEN
        return MASKED_TOKEN + value[-3:]
    return value


def _mask_cookie(cookie: str) -> str:
    """对通过 /api/setting 返回给前端的 cookie 进行脱敏，隐藏 passToken 与 userId 的敏感部分。"""
    if not cookie:
        return cookie
    parts = []
    for item in cookie.split(";"):
        stripped = item.strip()
        if not stripped:
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
            key = key.strip()
            parts.append(f"{key}={_mask_value(key, value.strip())}")
            continue
        parts.append(stripped)
    return "; ".join(parts)


def _unmask_cookie(new_cookie: str, current_cookie: str) -> str:
    """将前端回写的 cookie 还原为真实值。

    脱敏值中一定含有 `*`（passToken/userId 的真实值不含 `*`）。若某字段回写值仍带
    `*`（用户未修改），则用当前已存储的真实值替换，避免脱敏值被写坏凭据；用户填入
    的新值不含 `*`，按原样保存。
    """
    if not new_cookie or MASKED_TOKEN not in new_cookie:
        return new_cookie

    # 解析当前存储的真实值
    current = {}
    for item in (current_cookie or "").split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            current[k.strip()] = v.strip()

    parts = []
    for item in new_cookie.split(";"):
        stripped = item.strip()
        if not stripped:
            continue
        if "=" in stripped:
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if MASKED_TOKEN in value and current.get(key):
                parts.append(f"{key}={current[key]}")
                continue
            parts.append(f"{key}={value}")
            continue
        parts.append(stripped)
    return "; ".join(parts)


def _mask_devices(device_list, required_fields=['miotDID','hardware','name']):
    """按白名单裁剪设备信息，仅保留 required_fields 指定的字段。

    Args:
        device_list: 单个设备 dict，或设备 dict 组成的列表。
        required_fields: 需要保留的字段名列表，支持用点号表示嵌套路径
            （如 "capabilities.multiroom_music"）。

    Returns:
        仅含指定字段、并保持原嵌套结构的设备。设备中不存在的字段会被跳过。
        输入为列表时返回列表，输入为单个 dict 时返回单个 dict。
    """
    single = not isinstance(device_list, list)
    devices = [device_list] if single else device_list

    _MISSING = object()
    result = []
    for device in devices:
        masked = {}
        for field in required_fields:
            keys = field.split(".")

            # 沿路径逐级取值，任一级缺失或非 dict 则跳过该字段
            value = device
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    value = _MISSING
                    break
            if value is _MISSING:
                continue

            # 沿路径逐级写入，重建嵌套结构
            target = masked
            for k in keys[:-1]:
                nested = target.get(k)
                if not isinstance(nested, dict):
                    nested = {}
                    target[k] = nested
                target = nested
            target[keys[-1]] = value

        result.append(masked)

    return result[0] if single else result


def _is_docker():
    """检测是否在 Docker 容器中运行"""
    # 1. 环境变量显式指定（最可靠）
    if os.environ.get("CASTFABRIC_DOCKER") or os.environ.get("MIAIR_DOCKER"):
        return True
    # 2. Docker 会在容器根目录创建 .dockerenv 文件
    if os.path.exists("/.dockerenv"):
        return True
    # 3. 检查 cgroup（兼容 cgroup v1 和 v2）
    try:
        with open('/proc/1/cgroup', 'r') as f:
            content = f.read()
            return any(k in content for k in ('docker', 'containerd', 'kubepods'))
    except Exception:
        pass
    # 4. 检查 /proc/self/mountinfo 中的 overlay/docker 挂载
    try:
        with open('/proc/self/mountinfo', 'r') as f:
            content = f.read()
            return 'docker' in content or '/docker/' in content
    except Exception:
        pass
    return False


def _get_app_dir():
    """获取应用根目录（miair 包的上级目录）"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _restart_process():
    """重启当前 Python 进程"""
    log.info(f"重启进程: {sys.executable} {sys.argv}")
    
    # 检测是否在 Docker 容器中
    if _is_docker():
        # Docker 环境下，直接退出进程
        # Docker 容器已设置 restart=unless-stopped，会自动重启
        log.info("在 Docker 环境中，退出进程，Docker 会自动重启容器")
        # 使用 exit code 0，unless-stopped 策略下任何退出都会重启
        os._exit(0)
    elif sys.platform == "win32":
        # Windows 上 os.execv 行为不同，使用 subprocess 重启
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv)
        os._exit(0)
    else:
        os.execv(sys.executable, [sys.executable] + sys.argv)


def _extension_auth_status(config: Config, auth) -> dict:
    """Report Xiaomi authentication only when the optional extension is enabled."""
    if not config.enable_xiaomi_extension:
        return {
            "auth_state": "disabled",
            "auth_error_code": "",
            "auth_error_message": "",
            "auth_retry_after": 0,
        }
    return auth.get_auth_status()


def create_web_app(config: Config, app_instance) -> web.Application:
    """创建 Web 管理应用"""
    web_app = web.Application()

    async def handle_index(request):
        """主页"""
        import os
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return web.FileResponse(index_path)
        return web.Response(text="CastFabric Web UI", content_type="text/html")

    async def handle_get_setting(request):
        """获取当前设置和设备列表 (类似 xiaomusic /getsetting)"""
        need_device_list = request.query.get("need_device_list", "false") == "true"
        auth_status = _extension_auth_status(config, app_instance.auth)

        data = {
            "version": VERSION,
            "hostname": config.hostname,
            "dlna_port": config.dlna_port,
            "web_port": config.web_port,
            "proxy_enabled": config.proxy_enabled,
            "auto_play_on_set_uri": config.auto_play_on_set_uri,
            "mi_did": config.mi_did,
            "default_target_id": config.default_target_id,
            "targets_count": len(config.get_enabled_targets()),
            "has_account": bool(config.account or config.cookie),
            "xiaomi_extension_enabled": config.enable_xiaomi_extension,
            "cookie": _mask_cookie(config.cookie),
            "dlna_running": app_instance.dlna_running,
            "renderers_count": len(app_instance.renderers),
            "cloud_control_available": app_instance.auth.is_logged_in(),
            "local_control_available": app_instance.has_local_speaker_control(),
            "control_mode": (
                "local" if app_instance.has_local_speaker_control()
                else "cloud" if app_instance.auth.is_logged_in()
                else "unavailable"
            ),
            "discovery_mode": (
                "cloud" if app_instance.auth.is_logged_in()
                else "cached" if app_instance.dlna_running
                else "stopped"
            ),
            **auth_status,
            # 实验性功能
            "auto_resume_on_interrupt": config.auto_resume_on_interrupt,
            "resume_delay_seconds": config.resume_delay_seconds,
            "default_volume": config.default_volume,
            "follow_device_volume": config.follow_device_volume,
            "auto_restart": config.auto_restart,
            "enable_miplay": config.enable_miplay,
            "miplay_port": config.miplay_port,
            "device_name_prefix": config.device_name_prefix,
            "miplay_name": config.miplay_name,
            "miplay_play_type": config.miplay_play_type,
            "miplay_http_mode": config.miplay_http_mode,
            "miplay_content_type": config.miplay_content_type,
            "miplay_stream_format": config.miplay_stream_format,
            "miplay": app_instance.miplay_receiver.diagnostics()
            if app_instance.miplay_receiver
            else {"running": False},
        }

        # 返回已配置的 speakers 信息
        speakers_info = {}
        for did in config.get_did_list():
            speaker = config.get_speaker(did)
            speakers_info[did] = {
                "did": did,
                "name": speaker.name,
                "dlna_name": speaker.get_dlna_name(),
                "hardware": speaker.hardware,
                "enabled": speaker.enabled,
                "compatibility_mode": speaker.is_compatibility_mode(),
            }
        data["speakers"] = speakers_info

        from miair.const import NEED_USE_PLAY_MUSIC_API
        data["need_use_play_music_api"] = NEED_USE_PLAY_MUSIC_API

        if need_device_list:
            try:
                observed = await LocalDLNAClient.discover(config.hostname)
                app_instance.discovered_targets = {
                    target.id: target for target in observed
                    if target.id not in {
                        f"uuid:{renderer.udn}" for renderer in app_instance.renderers.values()
                    }
                }
            except Exception as exc:
                log.warning("扫描 DLNA 输出目标失败: %s", type(exc).__name__)
            data["target_list"] = _target_view(
                config, app_instance.discovered_targets
            )
            if config.enable_xiaomi_extension and (config.account or config.cookie):
                device_list = await app_instance.get_all_devices()
                data["device_list"] = _mask_devices(device_list)

        return web.json_response(data)

    async def handle_save_setting(request):
        """保存设置 (账号、密码、cookie、选中的设备)"""
        data = await request.json()

        # 更新账号信息
        if "account" in data:
            config.account = data["account"]
        if "password" in data:
            config.password = data["password"]
        if "cookie" in data:
            # 若前端回写的是脱敏占位符（未修改 passToken等），还原为已存储的真实值
            config.cookie = _unmask_cookie(data["cookie"], config.cookie)
        if "enable_xiaomi_extension" in data:
            config.enable_xiaomi_extension = bool(data["enable_xiaomi_extension"])

        # 更新设备选择
        if "mi_did" in data:
            config.mi_did = data["mi_did"]

        if "target_ids" in data:
            try:
                _apply_target_selection(
                    config,
                    list(data.get("target_ids") or []),
                    app_instance.discovered_targets,
                    str(data.get("default_target_id") or ""),
                )
            except ValueError as exc:
                return web.json_response({"error": str(exc)}, status=400)

        # 更新其他配置
        if "auto_play_on_set_uri" in data:
            config.auto_play_on_set_uri = data["auto_play_on_set_uri"]

        # 更新端口配置
        if "dlna_port" in data:
            config.dlna_port = data["dlna_port"]
        if "web_port" in data:
            config.web_port = data["web_port"]

        # 更新实验性功能配置
        if "auto_resume_on_interrupt" in data:
            config.auto_resume_on_interrupt = data["auto_resume_on_interrupt"]
        if "resume_delay_seconds" in data:
            config.resume_delay_seconds = max(1, min(15, int(data["resume_delay_seconds"])))
        if "default_volume" in data:
            config.default_volume = max(1, min(100, int(data["default_volume"])))
        if "follow_device_volume" in data:
            config.follow_device_volume = data["follow_device_volume"]
        if "auto_restart" in data:
            config.auto_restart = data["auto_restart"]
        if "enable_miplay" in data:
            config.enable_miplay = bool(data["enable_miplay"])
        if "miplay_port" in data:
            config.miplay_port = max(0, min(65535, int(data["miplay_port"])))
        requested_prefix = data.get("device_name_prefix", data.get("miplay_name"))
        if requested_prefix is not None:
            from miair.identity import normalize_device_prefix

            config.device_name_prefix = normalize_device_prefix(requested_prefix)
            config.miplay_name = config.device_name_prefix
        if "miplay_play_type" in data:
            requested_type = int(data["miplay_play_type"])
            config.miplay_play_type = (
                requested_type if requested_type in (0, 1, 2) else 2
            )
        if "miplay_http_mode" in data:
            requested_mode = str(data["miplay_http_mode"]).lower()
            config.miplay_http_mode = (
                requested_mode
                if requested_mode in ("close", "content-length", "range")
                else "close"
            )
        if "miplay_content_type" in data:
            requested_content_type = str(data["miplay_content_type"]).lower()
            config.miplay_content_type = (
                requested_content_type
                if requested_content_type in ("audio/wav", "audio/x-wav")
                else "audio/wav"
            )
        if "miplay_stream_format" in data:
            requested_stream_format = str(data["miplay_stream_format"]).lower()
            config.miplay_stream_format = (
                requested_stream_format
                if requested_stream_format in ("wav", "l16")
                else "wav"
            )

        # 更新 speaker 名称和兼容模式
        if "speakers" in data:
            for did, speaker_data in data["speakers"].items():
                speaker = config.get_speaker(did)
                if "dlna_name" in speaker_data:
                    speaker.dlna_name = speaker_data["dlna_name"]
                if "compatibility_mode" in speaker_data:
                    speaker.compatibility_mode = speaker_data["compatibility_mode"]

        config.save()

        # 先返回响应，然后重启进程
        resp = web.json_response({"ok": True, "message": "配置已保存，正在重启..."})
        await resp.prepare(request)
        await resp.write_eof()

        # 安排进程重启
        log.info("配置已保存，正在重启进程...")
        asyncio.get_running_loop().call_soon(_restart_process)
        return resp

    async def handle_get_devices(request):
        """获取小米账号下所有设备列表"""
        if not config.enable_xiaomi_extension:
            return web.json_response(
                {"error": "小米云扩展未启用"}, status=400
            )
        if not config.cookie:
            return web.json_response(
                {"error": "请先配置 Cookie"}, status=400
            )

        try:
            devices = await app_instance.get_all_devices()
            if not devices and not app_instance.auth.is_logged_in():
                auth_status = app_instance.auth.get_auth_status()
                return web.json_response({
                    "devices": [],
                    "error": auth_status["auth_error_message"] or "小米账号认证失败",
                    "error_code": auth_status["auth_error_code"],
                    "retry_after": auth_status["auth_retry_after"],
                })
            return web.json_response({"devices": _mask_devices(devices)})
        except Exception as e:
            return web.json_response(
                {"error": f"获取设备列表失败: {e}"}, status=500
            )

    async def handle_get_speakers(request):
        """获取当前运行中的渲染器状态"""
        speakers_info = []
        for did, controller in app_instance.speaker_manager.controllers.items():
            speaker = controller.speaker
            renderer = app_instance.get_renderer_by_did(did)
            # 获取 DLNA 状态
            transport_state = renderer.transport_state if renderer else "UNKNOWN"
            current_uri = renderer.current_uri if renderer else ""
            
            # 获取 AirPlay 状态
            airplay_active = False
            airplay_client = ""
            if app_instance.airplay_manager:
                sap = app_instance.airplay_manager.speaker_airplays.get(did)
                if sap and sap.airplay_server:
                    if sap.airplay_server.is_playing:
                        airplay_active = True
                        airplay_client = sap.airplay_server.client_name

            speakers_info.append({
                "did": did,
                "name": speaker.name,
                "dlna_name": speaker.get_dlna_name(),
                "hardware": speaker.hardware,
                "enabled": speaker.enabled,
                "udn": speaker.udn,
                "transport_state": transport_state,
                "current_uri": current_uri,
                "airplay_active": airplay_active,
                "airplay_client": airplay_client,
            })
        return web.json_response(speakers_info)

    async def handle_rename_speaker(request):
        """重命名音箱的 DLNA 名称"""
        did = request.match_info["did"]
        data = await request.json()
        new_name = data.get("dlna_name", "")
        if not new_name:
            return web.json_response({"error": "名称不能为空"}, status=400)

        speaker = config.get_speaker(did)
        speaker.dlna_name = new_name
        config.save()
        
        # 更新对应的DLNA渲染器名称
        for udn, renderer in app_instance.renderers.items():
            if renderer.did == did:
                renderer.friendly_name = new_name
                log.info(f"已更新渲染器名称: {new_name} (did={did})")
                break
        
        return web.json_response({"ok": True, "dlna_name": new_name})

    async def handle_status(request):
        """系统状态"""
        return web.json_response({
            "version": VERSION,
            "dlna_running": app_instance.dlna_running,
            "renderers_count": len(app_instance.renderers),
            "has_account": bool(config.account or config.cookie),
            "xiaomi_extension_enabled": config.enable_xiaomi_extension,
            "mi_did": config.mi_did,
            "default_target_id": config.default_target_id,
            "targets_count": len(config.get_enabled_targets()),
            "cloud_control_available": app_instance.auth.is_logged_in(),
            "local_control_available": app_instance.has_local_speaker_control(),
            "control_mode": (
                "local" if app_instance.has_local_speaker_control()
                else "cloud" if app_instance.auth.is_logged_in()
                else "unavailable"
            ),
            "discovery_mode": (
                "cloud" if app_instance.auth.is_logged_in()
                else "cached" if app_instance.dlna_running
                else "stopped"
            ),
            "hostname": config.hostname,
            "dlna_port": config.dlna_port,
            "web_port": config.web_port,
            "miplay": app_instance.miplay_receiver.diagnostics()
            if app_instance.miplay_receiver
            else {"running": False},
            **_extension_auth_status(config, app_instance.auth),
        })

    async def handle_miplay_status(request):
        receiver = app_instance.miplay_receiver
        return web.json_response(
            receiver.diagnostics() if receiver else {"running": False}
        )

    async def handle_execute_update(request):
        """执行一键更新：从 GitHub 下载最新代码覆盖后重启"""
        app_dir = _get_app_dir()
        in_docker = _is_docker()
        if in_docker:
            return web.json_response(
                {
                    "ok": False,
                    "error": "Docker 部署请运行 docker compose pull && docker compose up -d",
                },
                status=409,
            )
        url = "https://github.com/DjangoAILab/CastFabric/archive/refs/heads/main.tar.gz"

        log.info(f"开始一键更新 (目录: {app_dir}, Docker: {in_docker})")

        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
        try:
            # 下载最新代码压缩包
            log.info(f"正在下载更新: {url}")
            urllib.request.urlretrieve(url, tmp_file.name)
            tmp_file.close()

            # 解压并覆盖当前代码
            log.info("正在解压更新...")
            import shutil
            with tarfile.open(tmp_file.name, "r:gz") as tar:
                members = tar.getmembers()
                prefix = members[0].name.split("/")[0] + "/"

                for member in members:
                    if not member.name.startswith(prefix):
                        continue
                    member.name = member.name[len(prefix):]
                    if not member.name:
                        continue

                    target = os.path.join(app_dir, member.name)
                    if member.isdir():
                        os.makedirs(target, exist_ok=True)
                    elif member.isfile():
                        parent = os.path.dirname(target)
                        if parent:
                            os.makedirs(parent, exist_ok=True)
                        src = tar.extractfile(member)
                        if src:
                            with open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)

            # Docker 环境下重新安装依赖（可能有新增依赖）
            if in_docker:
                import subprocess
                try:
                    pyproject = os.path.join(app_dir, "pyproject.toml")
                    if os.path.exists(pyproject):
                        subprocess.run(
                            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "."],
                            cwd=app_dir,
                            capture_output=True,
                            timeout=120,
                        )
                except Exception as e:
                    log.warning(f"更新后重新安装依赖失败: {e}")

            log.info("更新下载并解压完成")

        except Exception as e:
            log.error(f"更新失败: {e}")
            return web.json_response(
                {"ok": False, "error": f"更新失败: {e}"},
                status=500,
            )
        finally:
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass

        # 更新完成后重启
        resp = web.json_response({"ok": True, "message": "更新完成，正在重启..."})
        await resp.prepare(request)
        await resp.write_eof()

        log.info("一键更新完成，正在重启进程...")
        asyncio.get_running_loop().call_soon(_restart_process)
        return resp

    # 注册路由
    web_app.router.add_get("/", handle_index)
    web_app.router.add_get("/api/setting", handle_get_setting)
    web_app.router.add_post("/api/setting", handle_save_setting)
    web_app.router.add_get("/api/devices", handle_get_devices)
    web_app.router.add_get("/api/speakers", handle_get_speakers)
    web_app.router.add_post("/api/speakers/{did}/rename", handle_rename_speaker)
    web_app.router.add_get("/api/status", handle_status)
    web_app.router.add_get("/api/miplay/status", handle_miplay_status)
    web_app.router.add_post("/api/update", handle_execute_update)
    setup_api_v1_routes(web_app, config, app_instance)
    from miair.mcp import EmbeddedMcpEndpoint

    mcp_endpoint = EmbeddedMcpEndpoint(app_instance, config)
    app_instance.mcp_endpoint = mcp_endpoint
    web_app.cleanup_ctx.append(mcp_endpoint.lifecycle)
    web_app.router.add_route("*", "/mcp", mcp_endpoint.handle)

    # 静态文件
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        web_app.router.add_static("/static", static_dir)

    return web_app
