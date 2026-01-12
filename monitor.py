"""
监控核心模块 - 负责电费数据获取和监控任务
"""
import time
import re
import threading
import requests
import unicodedata
from bs4 import BeautifulSoup
from datetime import datetime
from config import Config, logger

# 目标URL
TARGET_URL = "http://zhyd.sec.lit.edu.cn/zhyd/sydl/index"

# 全局状态
system_status = {
    "last_check_time": None,
    "last_check_data": None,
    "last_error": None,
    "consecutive_failures": 0,
    "is_monitoring": True,
    "sources": {}
}

# 用于“立即触发下一轮抓取”的唤醒事件（例如扫码刚更新 cookie 后）
_monitor_wakeup_event = threading.Event()


def request_immediate_check(reason: str = ""):
    """请求监控线程尽快执行下一轮抓取。

    monitor_task 可能正在 sleep；此函数会唤醒它并尽快进入下一轮循环。
    """
    try:
        # 让前端/状态接口显示“即将运行”
        system_status["next_check_in"] = 1
    except Exception:
        pass
    if reason:
        logger.info(f"⚡ 请求立即刷新数据: {reason}")
    _monitor_wakeup_event.set()


def classify_meter(room_text, cfg=None):
    """按绑定房间文字对表计分类。

    默认规则（可在 config.ini 的 [meters] 覆盖）：
    - lighting: 含“照明”
    - ac_a: 含“3-721A空调”
    - ac_b: 含“3-721B空调”
    """
    text = str(room_text or "")
    if cfg is None:
        cfg = Config()

    lighting_kw = cfg.get("meters", "lighting_keywords", "照明")
    ac_a_kw = cfg.get("meters", "ac_a_keywords", "3-721A空调")
    ac_b_kw = cfg.get("meters", "ac_b_keywords", "3-721B空调")

    if lighting_kw and lighting_kw in text:
        return "lighting"
    if ac_a_kw and ac_a_kw in text:
        return "ac_a"
    if ac_b_kw and ac_b_kw in text:
        return "ac_b"
    # 兜底：含“空调”但未匹配 A/B
    if "空调" in text:
        return "ac"
    return "unknown"


def merge_room_data(all_lists):
    """合并多个来源的数据，并对相同 room 去重。

    返回 list，每条包含：room/kwh/money/meter_type/sources
    """
    merged = {}
    for items in all_lists:
        for d in items or []:
            room = str(d.get("room") or "")
            if not room:
                continue
            if room not in merged:
                merged[room] = {
                    "room": room,
                    "kwh": d.get("kwh", "0"),
                    "money": d.get("money", "0"),
                    "meter_type": d.get("meter_type", "unknown"),
                    "sources": []
                }
            src = d.get("source")
            if src and src not in merged[room]["sources"]:
                merged[room]["sources"].append(src)

            # 优先保留非 unknown 的分类
            if merged[room]["meter_type"] in ("unknown", "ac") and d.get("meter_type") not in (None, "unknown"):
                merged[room]["meter_type"] = d.get("meter_type")

            # 如果数值不同，保留最新一次抓到的（通常不会出现）
            merged[room]["kwh"] = d.get("kwh", merged[room]["kwh"])
            merged[room]["money"] = d.get("money", merged[room]["money"])

    return list(merged.values())


def parse_data(html):
    """解析HTML页面，提取房间电量数据"""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.mui-card")
    if not cards:
        return None
    
    data = []
    for card in cards:
        room, kwh, money = "未知", "0", "0"
        for li in card.select("li"):
            txt = li.get_text()
            if "绑定房间" in txt:
                room = li.find("span").text.strip()
            if "剩余电量" in txt:
                kwh = li.find("span").text.strip()
            if "剩余金额" in txt:
                money = li.find("span").text.strip()
        data.append({"room": room, "kwh": kwh, "money": money})
    
    return data


def _extract_first_float(value):
    """从字符串中提取第一个可解析的浮点数。

    兼容类似：
    - '27.04度'
    - '15.14元'
    - '  0 '
    返回 float 或 None。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _normalize_room_key_for_cooldown(room):
    """生成用于告警冷却的稳定 key（不影响房间映射匹配）。"""
    text = str(room or "").strip()
    if not text:
        return ""
    # 统一 Unicode 表示，清理常见不可见字符
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return text.strip()


def fetch_data(cookie, ua):
    """
    使用Cookie获取电费数据
    
    Args:
        cookie: JSESSIONID Cookie
        ua: User-Agent字符串
        
    Returns:
        (list|None, str): (房间数据列表或None, reason_code)
    """
    if not cookie:
        logger.warning("❌ Cookie为空")
        return None, "no_cookie"
    
    logger.info(f"🔍 正在使用 Cookie: {cookie[:50]}...")
    
    headers = {
        "User-Agent": ua,
        "Cookie": cookie,
        "Host": "zhyd.sec.lit.edu.cn",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive"
    }
    
    try:
        resp = requests.get(
            TARGET_URL,
            headers=headers,
            timeout=20,
            verify=False,
            allow_redirects=False
        )
        resp.encoding = "utf-8"
        
        logger.info(f"🔍 响应状态码: {resp.status_code} | 内容长度: {len(resp.text)}")
        
        # 检查重定向(Cookie失效)
        if resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = resp.headers.get('Location', '')
            logger.warning(f"❌ Cookie已失效,重定向到: {redirect_url[:60]}...")
            return None, "redirect"
        
        # 检查服务器错误
        if resp.status_code == 502:
            logger.warning("⚠️ 服务器502错误(学校系统故障),稍后重试")
            return None, "server_502"
        
        if resp.status_code >= 500:
            logger.error(f"❌ 服务器错误: {resp.status_code}")
            return None, "server_5xx"
        
        if resp.status_code != 200:
            logger.error(f"❌ 异常状态码: {resp.status_code}")
            return None, f"http_{resp.status_code}"
        
        # 检查页面内容
        if "统一身份认证" in resp.text or "authserver" in resp.text:
            logger.warning("❌ 页面显示需要重新登录")
            return None, "auth_required"
        
        # 解析数据
        data = parse_data(resp.text)
        if data:
            logger.info(f"✅ 成功解析到 {len(data)} 条房间数据")
        else:
            logger.warning("⚠️ 页面未找到房间数据")

        if not data:
            return None, "no_data"
        return data, "ok"
        
    except requests.exceptions.Timeout:
        logger.error("❌ 请求超时")
        return None, "timeout"
    except requests.exceptions.ConnectionError:
        logger.error("❌ 网络连接失败")
        return None, "connection_error"
    except Exception as e:
        logger.error(f"❌ 请求失败: {e}")
        return None, "exception"


def monitor_task():
    """后台监控循环任务"""
    global system_status
    logger.info("⏱️ 监控线程已启动")

    # 记录每个 source 的告警/修复邮件时间，防止轰炸
    last_repair_email_time = {}

    # 记录每个房间的低电量告警时间，防止轰炸（进程内）
    last_low_power_email_time = {}

    while True:
        # 检查是否暂停
        if not system_status["is_monitoring"]:
            time.sleep(10)
            continue
        
        # 重新读取配置
        cfg = Config()
        interval = cfg.get_int("system", "interval", 900)
        sources = cfg.get_auth_sources()

        # 初始化 source 状态结构
        if not isinstance(system_status.get("sources"), dict):
            system_status["sources"] = {}
        for s in sources:
            system_status["sources"].setdefault(s, {
                "last_error": None,
                "consecutive_failures": 0,
                "has_cookie": False,
                "last_ok_time": None,
                "last_rooms": []
            })

        ok_lists = []
        per_source_errors = []

        # 如果出现网络/服务器类失败，则启用逐步退避，缩短下次重试等待。
        # 退避节奏：60 -> 120 -> 300 -> 900（秒），并且不会超过 interval。
        transient_failure_backoffs = []

        def is_transient_failure(reason: str) -> bool:
            return reason in {"timeout", "connection_error", "server_502", "server_5xx"}

        def is_auth_failure(reason: str) -> bool:
            # 明确表示需要重新登录/发生重定向的一类失败
            return reason in {"redirect", "auth_required"}

        def backoff_seconds_for_failures(fails: int, cap: int) -> int:
            schedule = [60, 120, 300, 900]
            if fails <= 0:
                return cap
            idx = min(fails - 1, len(schedule) - 1)
            return min(schedule[idx], cap)

        for s in sources:
            cookie, ua = cfg.get_auth(source=s)
            system_status["sources"][s]["has_cookie"] = bool(cookie)
            if not cookie:
                system_status["sources"][s]["last_error"] = "Cookie未配置"
                per_source_errors.append(f"{s}:Cookie未配置")
                continue

            logger.info(f"🔍 source={s} Cookie长度: {len(cookie)}")
            data, reason = fetch_data(cookie, ua)
            if data:
                # 成功：标记分类/来源
                enriched = []
                for d in data:
                    room_text = d.get("room")
                    d2 = dict(d)
                    d2["source"] = s
                    d2["meter_type"] = classify_meter(room_text, cfg=cfg)
                    enriched.append(d2)
                ok_lists.append(enriched)

                # 记录该 source 最近一次成功抓到的房间，用于后续 cookie 失效时定向通知
                try:
                    system_status["sources"][s]["last_rooms"] = [str(x.get("room") or "").strip() for x in data if str(x.get("room") or "").strip()]
                except Exception:
                    system_status["sources"][s]["last_rooms"] = []

                system_status["sources"][s]["last_error"] = None
                system_status["sources"][s]["consecutive_failures"] = 0
                system_status["sources"][s]["last_ok_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                # 失败：累计
                system_status["sources"][s]["consecutive_failures"] += 1
                fails = system_status["sources"][s]["consecutive_failures"]
                system_status["sources"][s]["last_error"] = f"获取失败 (连续 {fails} 次){' - ' + reason if reason else ''}"
                per_source_errors.append(f"{s}:连续失败{fails}次")

                # 网络/服务器类失败：记录退避时间，用于缩短下次重试
                if is_transient_failure(reason):
                    transient_failure_backoffs.append(backoff_seconds_for_failures(fails, cap=interval))

                # 连续失败3次：判定该 source 需要修复
                if fails >= 3 and is_auth_failure(reason):
                    # 防止邮件轰炸：每12小时只发一次/每source
                    last_t = last_repair_email_time.get(s, 0)
                    if time.time() - last_t > 43200:
                        ip = cfg.get("system", "server_ip", "127.0.0.1")
                        port = cfg.get("system", "web_port", "5000")
                        if s == "legacy":
                            link = f"http://{ip}:{port}/login"
                        else:
                            link = f"http://{ip}:{port}/login?source={s}"

                        # 优先发给该 source 对应房间的联系人（来自最近一次成功抓到的 room 列表）
                        target_rooms = system_status.get("sources", {}).get(s, {}).get("last_rooms", []) or []
                        recipients = []
                        for room in target_rooms:
                            for mail in cfg.get_room_recipients(room):
                                if mail not in recipients:
                                    recipients.append(mail)

                        # 若没有房间映射，回退到 source 默认收件人
                        if not recipients:
                            recipients = cfg.get_source_recipients(s)

                        # 若没有房间映射，按 source 分组回退
                        if not recipients:
                            if s == "ac_a":
                                recipients = cfg.get_notify_group_recipients("a")
                            elif s == "ac_b":
                                recipients = cfg.get_notify_group_recipients("b")
                            elif s == "k":
                                recipients = cfg.get_notify_group_recipients("k")

                        rooms_text = "\n".join([f"- {r}" for r in target_rooms]) if target_rooms else "(未知：该账号近期无成功数据)"
                        cfg.send_email(
                            f"🚨 Cookie失效需修复 ({s})",
                            f"该宿舍账号凭证可能已失效（source={s}），导致连续获取失败（{fails}次）。\n\n"
                            f"影响房间：\n{rooms_text}\n\n"
                            f"请点击链接重新扫码登录：\n{link}\n",
                            to_override=recipients if recipients else None
                        )
                        last_repair_email_time[s] = time.time()

        merged = merge_room_data(ok_lists)

        # 更新全局状态
        system_status["last_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_status["last_check_data"] = merged

        # 全局错误展示：有任何 source 异常则提示，但只要有数据就不算全局失败
        system_status["last_error"] = "; ".join(per_source_errors) if per_source_errors else None

        # 计算一个全局 consecutive_failures：当所有 source 都拿不到数据时才累计
        if not merged:
            system_status["consecutive_failures"] = system_status.get("consecutive_failures", 0) + 1
        else:
            system_status["consecutive_failures"] = 0

        if merged:
            info_str = " | ".join([f"{d['room']}: ⚡{d['kwh']}度 💰{d['money']}元" for d in merged])
            logger.info(f"✅ 合并后数据: {info_str}")

            # 低电量检测（优先按房间分发；无映射则按组回退）
            thresh = cfg.get_float("system", "low_power_threshold", 15.0)
            cooldown = cfg.get_int("system", "low_power_alert_cooldown_seconds", 21600)
            recipients_a = cfg.get_notify_group_recipients("a")
            recipients_b = cfg.get_notify_group_recipients("b")
            recipients_k = cfg.get_notify_group_recipients("k")

            def send_alert(to_list, subject, content):
                if to_list:
                    cfg.send_email(subject, content, to_override=to_list)
                else:
                    # 回退到默认 notify.to
                    cfg.send_email(subject, content)

            def send_room_alert(room, meter_type, subject, content, source=None):
                # 1) 优先按房间映射发送
                room_recipients = cfg.get_room_recipients(room)
                if room_recipients:
                    cfg.send_email(subject, content, to_override=room_recipients)
                    return

                # 2) 回退到 source 默认收件人（新模式：默认按 source 告警）
                if source:
                    source_recipients = cfg.get_source_recipients(source)
                    if source_recipients:
                        cfg.send_email(subject, content, to_override=source_recipients)
                        return

                # 3) 无映射：按原有分组回退（兼容旧模式）
                if meter_type == "lighting":
                    send_alert(recipients_a, subject, content)
                    send_alert(recipients_b, subject, content)
                    send_alert(recipients_k, subject, content)
                elif meter_type == "ac_a":
                    send_alert(recipients_a, subject, content)
                elif meter_type == "ac_b":
                    send_alert(recipients_b, subject, content)
                else:
                    cfg.send_email(subject, content)

            for d in merged:
                try:
                    kwh_num = _extract_first_float(d.get('kwh', '0'))
                    if kwh_num is None:
                        continue
                    if kwh_num < thresh:
                        room_key = _normalize_room_key_for_cooldown(d.get('room'))
                        if room_key:
                            last_t = last_low_power_email_time.get(room_key, 0)
                            if cooldown > 0 and (time.time() - last_t) < cooldown:
                                continue

                        meter_type = d.get("meter_type")
                        logger.warning(f"⚠️ 低电量({meter_type}): {d.get('room')} {d.get('kwh')}")
                        subject = f"⚠️ 缺电警告: {d.get('kwh')}度"
                        content = f"房间/表计: {d.get('room')}\n剩余: {d.get('kwh')}度 / {d.get('money')}元\n请尽快充值!"

                        send_room_alert(d.get('room'), meter_type, subject, content, source=d.get('source'))

                        if room_key:
                            last_low_power_email_time[room_key] = time.time()
                except Exception:
                    pass

            sleep_seconds = interval
            if transient_failure_backoffs:
                sleep_seconds = max(5, min(sleep_seconds, min(transient_failure_backoffs)))
            system_status["next_check_in"] = sleep_seconds
            _monitor_wakeup_event.wait(timeout=sleep_seconds)
            _monitor_wakeup_event.clear()
        else:
            logger.warning("⚠️ 所有 source 均未获取到数据")
            sleep_seconds = 60
            # 即使全失败，也遵循退避（通常=60，后续会逐步变长）
            if transient_failure_backoffs:
                sleep_seconds = max(5, min(sleep_seconds, min(transient_failure_backoffs)))
            system_status["next_check_in"] = sleep_seconds
            _monitor_wakeup_event.wait(timeout=sleep_seconds)
            _monitor_wakeup_event.clear()


            