import os
import ssl
import smtplib
import configparser
import logging
import secrets
from email.message import EmailMessage

# === 基础配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")

# 初始化日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("System")


class Config:
    def __init__(self):
        self.cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        # 保持 key 大小写（默认会 lower），否则房间号如 3-721A空调 的 A 会被变成 a，导致匹配失败
        self.cp.optionxform = str
        self.cp.read(CONFIG_FILE, encoding="utf-8")
        self.cp._defaults['config_file'] = CONFIG_FILE

    def _ensure_section(self, section):
        if not self.cp.has_section(section):
            self.cp.add_section(section)

    def get_auth_section(self, source=None):
        """返回指定 source 的 auth section 名称。

        - source is None: 兼容旧版本，使用 [auth]
        - source like "ac_a": 使用 [auth.ac_a]
        """
        if not source or source == "legacy":
            return "auth"
        return f"auth.{source}"

    def get_auth(self, source=None):
        """读取指定 source 的 Cookie/UA。

        返回: (cookie, ua)
        兼容策略：
        - 如果指定 source 的 section 不存在或 cookie 为空，回退到旧 [auth]
        """
        section = self.get_auth_section(source)
        cookie = self.get(section, "cookie", "")
        ua = self.get(section, "user_agent", "")

        return cookie, ua

    def get(self, section, key, fallback=""):
        if not self.cp.has_section(section): 
            return fallback
        return self.cp.get(section, key, fallback=fallback).strip()

    def get_float(self, section, key, fallback=0.0):
        try:
            return float(self.get(section, key, fallback))
        except:
            return fallback

    def get_int(self, section, key, fallback=0):
        try:
            return int(self.get(section, key, fallback))
        except:
            return fallback

    def update_auth(self, cookie, ua, source=None):
        """保存指定 source 的 Cookie 和 UA。

        - source=None: 写入旧 [auth]
        - source="ac_a": 写入 [auth.ac_a]
        """
        section = self.get_auth_section(source)
        self._ensure_section(section)
        self.cp.set(section, "cookie", cookie)
        self.cp.set(section, "user_agent", ua)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self.cp.write(f)

        suffix = f" ({source})" if source else ""
        logger.info(f"💾 配置文件已更新{suffix}")

    def get_auth_sources(self, fallback=("ac_a", "ac_b", "k")):
        """读取需要轮询的 auth sources。

        读取 [system].auth_sources（逗号/分号/换行分隔）。
        未配置则返回 fallback。
        """
        raw = self.get("system", "auth_sources", "")
        if not raw:
            # 自动检测：如果用户已经创建了 [auth.xxx] 段，则以实际存在的为准。
            detected = []
            for sec in self.cp.sections():
                if sec.startswith("auth.") and len(sec) > len("auth."):
                    detected.append(sec[len("auth."):])
            if detected:
                return sorted(set(detected))

            # 兼容旧版本：只有 [auth] 时，进入 legacy 单源模式，避免把同一条 Cookie 当三套重复轮询
            legacy_cookie = self.get("auth", "cookie", "")
            if legacy_cookie:
                return ["legacy"]

            return list(fallback)
        parts = [x.strip() for x in raw.replace(";", ",").replace("\n", ",").split(",")]
        return [x for x in parts if x]

    def get_auth_labels(self):
        """读取 source -> label 映射。

        配置约定：

        [auth.labels]
        X3-721B = 西三721B宿舍

        返回：dict[str, str]
        """
        section = "auth.labels"
        if not self.cp.has_section(section):
            return {}

        labels = {}
        defaults = set(self.cp.defaults().keys())
        for key, value in self.cp.items(section):
            k = str(key or "").strip()
            if not k:
                continue
            if k in defaults or k.casefold() == "config_file":
                continue
            v = str(value or "").strip()
            if v:
                labels[k] = v
        return labels

    def get_notify_group_recipients(self, group):
        """读取分组收件人。

        - group like "a"/"b"/"k": section 为 [notify.group_a] 等
        - 若未配置，返回空列表
        """
        section = f"notify.group_{group}"
        raw = self.get(section, "to", "")
        if not raw:
            return []
        parts = [x.strip() for x in raw.replace(";", ",").replace("\n", ",").split(",")]
        return [x for x in parts if x]

    def get_source_recipient_map(self):
        """读取 source 到收件人映射（默认告警按 source 分发）。

        [notify.sources]
        X3-721B = a@example.com,b@example.com

        返回：dict[str, list[str]]
        """
        section = "notify.sources"
        if not self.cp.has_section(section):
            return {}

        mapping = {}
        defaults = set(self.cp.defaults().keys())
        for key, value in self.cp.items(section):
            source_key = str(key or "").strip()
            if not source_key:
                continue
            if source_key in defaults or source_key.casefold() == "config_file":
                continue
            recipients = [x.strip() for x in str(value).replace(";", ",").replace("\n", ",").split(",") if x.strip()]
            if recipients:
                mapping[source_key] = recipients
        return mapping

    def get_source_recipients(self, source):
        """按 source 获取收件人列表（找不到返回空列表）。"""
        source_key = str(source or "").strip()
        if not source_key:
            return []

        mapping = self.get_source_recipient_map()
        if source_key in mapping:
            return mapping[source_key]
        sk = source_key.casefold()
        for k, v in mapping.items():
            if k.casefold() == sk:
                return v
        return []

    def set_source_recipients(self, source, recipients):
        """设置单个 source 的收件人（写入 config.ini）。"""
        section = "notify.sources"
        self._ensure_section(section)

        source_key = str(source or "").strip()
        if not source_key:
            raise ValueError("source 不能为空")
        if source_key in set(self.cp.defaults().keys()) or source_key.casefold() == "config_file":
            raise ValueError("source 名称不允许使用保留键: config_file")

        if isinstance(recipients, (list, tuple, set)):
            rec_list = [str(x).strip() for x in recipients if str(x).strip()]
        else:
            rec_list = [x.strip() for x in str(recipients or "").replace(";", ",").replace("\n", ",").split(",") if x.strip()]

        if not rec_list:
            if self.cp.has_option(section, source_key):
                self.cp.remove_option(section, source_key)
        else:
            self.cp.set(section, source_key, ",".join(rec_list))
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self.cp.write(f)

    def _normalize_room_key(self, room):
        return str(room or "").strip()

    def get_room_recipient_map(self):
        """读取房间到收件人映射。

        约定：在 config.ini 中配置

        [notify.rooms]
        3-721A空调 = a@example.com,b@example.com
        3-721B空调 = c@example.com

        返回：dict[str, list[str]]
        """
        section = "notify.rooms"
        if not self.cp.has_section(section):
            return {}

        mapping = {}
        defaults = set(self.cp.defaults().keys())
        for key, value in self.cp.items(section):
            room_key = self._normalize_room_key(key)
            if not room_key:
                continue
            # ConfigParser.items() 会把 [DEFAULT] 的键也带出来（例如 config_file），这里必须过滤掉
            if room_key in defaults or room_key.casefold() == "config_file":
                continue
            recipients = [x.strip() for x in str(value).replace(";", ",").replace("\n", ",").split(",") if x.strip()]
            if recipients:
                mapping[room_key] = recipients
        return mapping

    def get_room_recipients(self, room):
        """按房间名获取收件人列表（找不到返回空列表）。

        匹配策略：
        - 先精确匹配
        - 再做一次大小写不敏感匹配（兼容历史配置/复制粘贴差异）
        """
        room_key = self._normalize_room_key(room)
        if not room_key:
            return []

        mapping = self.get_room_recipient_map()
        if room_key in mapping:
            return mapping[room_key]

        rk = room_key.casefold()
        for k, v in mapping.items():
            if k.casefold() == rk:
                return v
        return []

    def set_room_recipients(self, room, recipients):
        """设置单个房间的收件人（写入 config.ini）。

        recipients 支持：str(逗号/分号/换行分隔) 或 list/tuple/set。
        """
        section = "notify.rooms"
        self._ensure_section(section)

        room_key = self._normalize_room_key(room)
        if not room_key:
            raise ValueError("room 不能为空")
        if room_key in set(self.cp.defaults().keys()) or room_key.casefold() == "config_file":
            raise ValueError("room 名称不允许使用保留键: config_file")

        if isinstance(recipients, (list, tuple, set)):
            rec_list = [str(x).strip() for x in recipients if str(x).strip()]
        else:
            rec_list = [x.strip() for x in str(recipients or "").replace(";", ",").replace("\n", ",").split(",") if x.strip()]

        # 允许清空：清空则删除该映射
        if not rec_list:
            if self.cp.has_option(section, room_key):
                self.cp.remove_option(section, room_key)
        else:
            self.cp.set(section, room_key, ",".join(rec_list))
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self.cp.write(f)

    def clear_room_recipient_map(self):
        """清空所有房间映射（删除 [notify.rooms] 段）。"""
        section = "notify.rooms"
        if self.cp.has_section(section):
            self.cp.remove_section(section)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                self.cp.write(f)

    def get_admin_token(self):
        """获取管理员Token"""
        if not self.cp.has_section("admin"):
            self.cp.add_section("admin")
        return self.get("admin", "admin_token", "")

    def set_admin_token(self, token):
        """设置管理员Token"""
        if not self.cp.has_section("admin"):
            self.cp.add_section("admin")
        self.cp.set("admin", "admin_token", token)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            self.cp.write(f)
        logger.info("🔐 管理员Token已更新")

    def generate_admin_token(self):
        """生成随机Token"""
        token = secrets.token_urlsafe(32)
        self.set_admin_token(token)
        return token

    def verify_admin_token(self, token):
        """验证管理员Token"""
        saved_token = self.get_admin_token()
        if not saved_token:
            return False
        return secrets.compare_digest(saved_token, token)

    def send_email(self, subject, content, to_override=None):
        """发送邮件通用函数

        Args:
            subject: 邮件主题
            content: 邮件正文(纯文本)
            to_override: 可选，覆盖收件人。
                - None: 使用 config.ini 中 [notify].to
                - str : 单个邮箱或逗号/分号/换行分隔的多个邮箱
                - list/tuple/set: 邮箱列表
        """
        # 每次发送重新读取，防止配置变动
        self.cp.read(CONFIG_FILE, encoding="utf-8")

        def normalize_recipients(value):
            if value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                parts = [str(x).strip() for x in value]
                return [x for x in parts if x]
            text = str(value).strip()
            if not text:
                return []
            return [x.strip() for x in text.replace(";", ",").replace("\n", ",").split(",") if x.strip()]

        recipients = normalize_recipients(to_override) if to_override is not None else normalize_recipients(self.get("notify", "to"))
        if not recipients:
            logger.warning("🚫 未配置收件人，跳过邮件")
            return

        cfg = {
            "server": self.get("notify", "smtp_server"),
            "port": self.get_int("notify", "smtp_port", 465),
            "tls": self.get("notify", "smtp_tls", "ssl").lower(),
            "user": self.get("notify", "smtp_username"),
            "pwd": self.get("notify", "smtp_password"),
            "from": self.get("notify", "from"),
            "to": recipients
        }

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = cfg["from"]
        msg["To"] = ", ".join(cfg["to"])
        msg.set_content(content)

        try:
            if cfg["tls"] == "ssl":
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(cfg["server"], cfg["port"], context=context, timeout=20)
            else:
                server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=20)
                server.starttls()
            server.login(cfg["user"], cfg["pwd"])
            server.send_message(msg)
            server.quit()
            logger.info(f"📧 邮件已发送: {subject}")
        except Exception as e:
            logger.error(f"❌ 邮件发送失败: {e}")