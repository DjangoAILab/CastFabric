"""小米账号认证管理"""

import asyncio
import copy
import json
import logging
import os
import re
import secrets
import tempfile
import time

import aiohttp
from miservice import MiAccount, MiIOService, MiNAService

from miair.config import Config

log = logging.getLogger("miair")


class AtomicTokenStore:
    """原子持久化完整小米 token，失败刷新不删除最后可用状态。"""

    def __init__(self, token_path: str):
        self.token_path = token_path

    def load_token(self) -> dict | None:
        if not os.path.isfile(self.token_path):
            return None
        try:
            with open(self.token_path, encoding="utf-8") as handle:
                token = json.load(handle)
            # 兼容旧版本创建的宽松权限文件。
            os.chmod(self.token_path, 0o600)
            return token if isinstance(token, dict) else None
        except Exception as exc:
            log.warning(f"读取小米 token store 失败: {type(exc).__name__}")
            return None

    def save_token(self, token: dict | None = None):
        # miservice 在刷新失败时调用 save_token(None) 删除文件。保留最后
        # 一份状态，才能继续使用其中的 passToken 做后续受控恢复。
        if not token:
            return

        directory = os.path.dirname(self.token_path) or "."
        os.makedirs(directory, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix=".mi.token.",
                delete=False,
            ) as handle:
                temp_path = handle.name
                json.dump(token, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.token_path)
        except Exception as exc:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            log.error(f"保存小米 token store 失败: {type(exc).__name__}")


class PersistentMiAccount(MiAccount):
    """保留 passToken 并允许 miservice 在 401 后安全刷新服务 token。"""

    def __init__(
        self,
        session,
        username,
        password,
        token_store: AtomicTokenStore,
        bootstrap_tokens: list[dict] | None = None,
        expected_user_id: str = "",
    ):
        super().__init__(session, username, password, token_store=token_store)
        self._bootstrap_tokens = self._deduplicate_tokens(bootstrap_tokens or [])

        if (
            expected_user_id
            and isinstance(self.token, dict)
            and str(self.token.get("userId", "")) != str(expected_user_id)
        ):
            # 配置切换到另一个账号时，旧账号 token 不能参与本次登录。
            self.token = None

        self._last_known_token = copy.deepcopy(self.token)
        self.last_login_response: dict = {}

    async def _serviceLogin(self, uri, data=None):
        """记录不含凭据的登录结果，供 Web 状态页准确展示失败原因。"""
        response = await super()._serviceLogin(uri, data)
        self.last_login_response = {
            "code": response.get("code"),
            "description": response.get("description") or response.get("desc") or "",
            "securityStatus": response.get("securityStatus"),
            "has_notification": bool(response.get("notificationUrl")),
        }
        return response

    @staticmethod
    def _deduplicate_tokens(tokens: list[dict]) -> list[dict]:
        result = []
        seen = set()
        for token in tokens:
            if not isinstance(token, dict):
                continue
            user_id = str(token.get("userId", ""))
            pass_token = str(token.get("passToken", ""))
            if not user_id or not pass_token or (user_id, pass_token) in seen:
                continue
            seen.add((user_id, pass_token))
            result.append(copy.deepcopy(token))
        return result

    @staticmethod
    def _refresh_seed(token: dict | None, device_id: str) -> dict | None:
        if not isinstance(token, dict):
            return None
        user_id = token.get("userId")
        pass_token = token.get("passToken")
        if not user_id or not pass_token:
            return None
        return {
            "userId": user_id,
            "passToken": pass_token,
            "deviceId": token.get("deviceId") or device_id,
        }

    def _login_candidates(self) -> list[dict]:
        device_id = ""
        for source in (self.token, self._last_known_token, *self._bootstrap_tokens):
            if isinstance(source, dict) and source.get("deviceId"):
                device_id = str(source["deviceId"])
                break
        if not device_id:
            device_id = secrets.token_hex(8).upper()

        candidates = []
        current = self._refresh_seed(self.token, device_id)
        previous = self._refresh_seed(self._last_known_token, device_id)
        for candidate in (current, previous, *self._bootstrap_tokens):
            seed = self._refresh_seed(candidate, device_id)
            if seed and seed not in candidates:
                candidates.append(seed)
        return candidates

    async def login(self, sid):
        previous = copy.deepcopy(self.token or self._last_known_token)
        candidates = self._login_candidates()

        # 账号密码模式仍交给 miservice；Cookie 模式逐个尝试最近持久化
        # token 和 Web 提供的 fallback token。
        if not candidates:
            if self.token is None:
                self.token = {"deviceId": secrets.token_hex(8).upper()}
            success = bool(await super().login(sid))
            if success and isinstance(self.token, dict) and sid in self.token:
                self._remember_successful_token()
                return True
            self.token = previous or self.token
            return False

        for candidate in candidates:
            self.token = copy.deepcopy(candidate)
            success = bool(await super().login(sid))
            if success and isinstance(self.token, dict) and sid in self.token:
                self._remember_successful_token()
                return True

        # miservice 会在失败时清空 self.token；恢复刷新材料和最后状态。
        self.token = previous or copy.deepcopy(candidates[0])
        self.token_store.save_token(self.token)
        return False

    def _remember_successful_token(self):
        self._last_known_token = copy.deepcopy(self.token)
        seed = self._refresh_seed(self.token, self.token.get("deviceId", ""))
        if seed:
            self._bootstrap_tokens = self._deduplicate_tokens(
                [seed, *self._bootstrap_tokens]
            )
        self.token_store.save_token(self.token)

    async def mi_request(self, sid, url, data, headers, relogin=True):
        # MiAccount.mi_request 在 401 后会把 token 设为 None，再递归调用。
        # 恢复不含过期 serviceToken 的 seed，使递归请求触发 login(sid)。
        if self.token is None:
            candidates = self._login_candidates()
            if candidates:
                self.token = copy.deepcopy(candidates[0])
        return await super().mi_request(sid, url, data, headers, relogin)


def parse_cookie_string(cookie_str: str) -> dict:
    """解析 Cookie 登录所需的 userId、passToken 和可选 deviceId。"""
    result = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in ("userId", "passToken", "deviceId"):
                result[key] = value
    return result


class AuthManager:
    """管理小米账号认证和设备服务"""

    LOGIN_RETRY_DELAYS = (30, 120, 300, 900)

    def __init__(self, config: Config):
        self.config = config
        self.session: aiohttp.ClientSession | None = None
        self.account: MiAccount | None = None
        self.mina_service: MiNAService | None = None
        self.miio_service: MiIOService | None = None
        self._logged_in = False
        self._login_lock = asyncio.Lock()
        self._login_failures = 0
        self._next_login_attempt = 0.0
        self.last_error_code = ""
        self.last_error_message = ""

    async def login(self):
        """单飞登录并在失败后限流，防止 Web 轮询触发请求风暴。"""
        if self._logged_in:
            return True
        if time.monotonic() < self._next_login_attempt:
            return False

        async with self._login_lock:
            if self._logged_in:
                return True
            if time.monotonic() < self._next_login_attempt:
                return False

            success = bool(await self._login_once())
            if success:
                self._login_failures = 0
                self._next_login_attempt = 0.0
                self.last_error_code = ""
                self.last_error_message = ""
                return True

            delay = self.LOGIN_RETRY_DELAYS[
                min(self._login_failures, len(self.LOGIN_RETRY_DELAYS) - 1)
            ]
            self._login_failures += 1
            self._next_login_attempt = time.monotonic() + delay
            log.warning(f"小米认证失败，{delay} 秒内不再发起登录请求")
            return False

    async def _login_once(self):
        """登录小米账号并初始化服务"""
        os.makedirs(self.config.conf_path, exist_ok=True)

        # 创建 aiohttp session（必须设置超时，否则 miservice HTTP 调用可能无限挂起导致卡死）
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
            )

        token_store = AtomicTokenStore(self.config.mi_token_home)

        # 如果有 cookie，使用 cookie 中的信息创建 MiAccount
        token_data = {}
        if self.config.cookie:
            token_data = parse_cookie_string(self.config.cookie)
        
        bootstrap_tokens = []
        expected_user_id = ""
        if token_data.get("userId") and token_data.get("passToken"):
            expected_user_id = token_data["userId"]
            bootstrap_token = {
                "userId": token_data["userId"],
                "passToken": token_data["passToken"],
            }
            if token_data.get("deviceId"):
                bootstrap_token["deviceId"] = token_data["deviceId"]
            bootstrap_tokens.append(bootstrap_token)
            username = ""
            password = ""
            log.info("使用 cookie 登录")
        else:
            username = self.config.account
            password = self.config.password

        self.account = PersistentMiAccount(
            self.session,
            username,
            password,
            token_store=token_store,
            bootstrap_tokens=bootstrap_tokens,
            expected_user_id=expected_user_id,
        )

        # 完整且账号匹配的持久 token 可直接复用；否则必须真实换取
        # micoapi serviceToken，不能只凭表单字段就宣称登录成功。
        if self._has_service_token(self.account.token, "micoapi"):
            self._logged_in = True
            log.info("已加载持久化的小米服务凭据")
        else:
            try:
                success = await self.account.login("micoapi")
                self._logged_in = bool(
                    success and self._has_service_token(self.account.token, "micoapi")
                )
                if self._logged_in:
                    log.info("小米服务凭据换取成功")
                else:
                    self._remember_login_failure()
                    log.warning("小米服务凭据换取失败")
            except Exception as e:
                self._logged_in = False
                err_msg = str(e)
                err_code = self._extract_error_code(err_msg)
                self.last_error_code = err_code
                self.last_error_message = self._friendly_error_message(err_code)
                if err_code == "87001" or "captcha" in err_msg.lower():
                    log.error(
                        "登录需要验证码! 请在浏览器访问 https://account.xiaomi.com 完成验证后重试，"
                        "或使用 cookie 方式登录"
                    )
                elif err_code == "70016":
                    log.error(
                        "登录验证失败! 可能原因：密码错误、需要关闭二次验证、"
                        "或需要在 https://www.mi.com 完成人机验证。"
                        "建议使用 cookie 方式登录。"
                    )
                elif "userId" in err_msg:
                    log.error(
                        "登录失败(缺少userId)! 小米账号可能需要额外验证。"
                        "请尝试以下方法：\n"
                        "  1. 在浏览器登录 https://account.xiaomi.com 完成验证\n"
                        "  2. 使用 cookie 方式登录（在设置中填入 cookie）\n"
                        "  3. 确保关闭了代理/VPN"
                    )
                else:
                    log.error(f"登录失败: {type(e).__name__}")

        # 无论是否登录成功，都设置 service (方便后续重试)
        self.mina_service = MiNAService(self.account)
        self.miio_service = MiIOService(self.account)
        return self._logged_in

    def _remember_login_failure(self):
        response = getattr(self.account, "last_login_response", {}) or {}
        code = response.get("code")
        self.last_error_code = str(code) if code is not None else ""
        self.last_error_message = self._friendly_error_message(self.last_error_code)

    @staticmethod
    def _friendly_error_message(error_code: str) -> str:
        if error_code == "70016":
            return "网页登录凭据不能用于小爱音箱服务，请重新完成 micoapi 授权"
        if error_code == "70022":
            return "小米登录请求过于频繁，请稍后重试"
        if error_code == "87001":
            return "小米账号需要验证码验证"
        return "小米账号认证失败"

    def get_auth_status(self) -> dict:
        if self._logged_in:
            state = "authenticated"
        elif self.last_error_code:
            state = "cooldown" if time.monotonic() < self._next_login_attempt else "failed"
        else:
            state = "pending"
        retry_after = max(0, int(self._next_login_attempt - time.monotonic()))
        return {
            "auth_state": state,
            "auth_error_code": self.last_error_code,
            "auth_error_message": self.last_error_message,
            "auth_retry_after": retry_after,
        }

    async def ensure_login(self):
        """确保已登录，未登录则尝试登录"""
        if self.mina_service is None or not self._logged_in:
            return await self.login()
        return True

    @staticmethod
    def _has_service_token(token: dict | None, sid: str) -> bool:
        if not isinstance(token, dict):
            return False
        service = token.get(sid)
        return (
            isinstance(service, (list, tuple))
            and len(service) == 2
            and bool(service[0])
            and bool(service[1])
            and bool(token.get("userId"))
            and bool(token.get("passToken"))
        )

    @staticmethod
    def _extract_error_code(err_msg: str) -> str:
        """从异常消息中提取数字错误码"""
        m = re.search(r'\b(\d{4,6})\b', err_msg)
        return m.group(1) if m else ""

    async def get_device_list(self) -> list[dict]:
        """获取账号下所有设备列表"""
        await self.ensure_login()
        if not self._logged_in:
            log.warning("未成功登录，无法获取设备列表")
            return []
        try:
            devices = await self.mina_service.device_list()
            return devices or []
        except Exception as e:
            self._logged_in = self._has_service_token(
                getattr(self.account, "token", None), "micoapi"
            )
            log.warning(f"获取设备列表失败: {type(e).__name__}")
            return []

    async def update_speakers_info(self):
        """从云端获取设备信息，更新 speakers 配置"""
        devices = await self.get_device_list()
        did_list = self.config.get_did_list()

        for device in devices:
            miot_did = device.get("miotDID", "")
            if miot_did in did_list:
                speaker = self.config.get_speaker(miot_did)
                speaker.device_id = device.get("deviceID", "")
                speaker.hardware = device.get("hardware", "")
                if not speaker.name:
                    speaker.name = device.get("name", "")
                speaker.ensure_udn()
                log.info(
                    f"已更新设备信息: {speaker.name} "
                    f"(did={miot_did}, device_id={speaker.device_id}, "
                    f"hardware={speaker.hardware})"
                )

    def is_logged_in(self) -> bool:
        """是否已成功登录"""
        return self._logged_in

    async def close(self):
        """关闭 session"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None
        self.account = None
        self.mina_service = None
        self.miio_service = None
        self._logged_in = False
