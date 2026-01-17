from flask import Blueprint, request, jsonify
from power_db import get_db
from datetime import datetime, timedelta

api = Blueprint('api', __name__)

# ...existing code...

# 获取指定房间过去7天耗电数据
@api.route('/api/room_power_trend')
def room_power_trend():
    room = request.args.get('room')
    if not room:
        return jsonify({'error': 'room参数缺失'}), 400
    today = datetime.now().date()
    days = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
    conn = get_db()
    try:
        sql = '''
            SELECT date, consume_power FROM power_daily
            WHERE room=? AND date BETWEEN ? AND ?
            ORDER BY date
        '''
        rows = conn.execute(sql, (room, days[0], days[-1])).fetchall()
        data = {r['date']: r['consume_power'] for r in rows}
        result = [{'date': d, 'consume_power': float(data.get(d, 0))} for d in days]
        return jsonify({'room': room, 'trend': result})
    finally:
        conn.close()
"""
API路由模块 - 提供RESTful API接口 (已添加权限控制)
"""
import re
from flask import Blueprint, jsonify, request
from config import Config, logger, CONFIG_FILE
from monitor import system_status
from auth import manual_set_cookie

# 创建蓝图
api_bp = Blueprint('api', __name__, url_prefix='/api')

def check_auth():
    """验证管理员权限辅助函数"""
    token = request.headers.get('X-Admin-Token')
    if not token:
        return False
    return Config().verify_admin_token(token)


@api_bp.route('/login-state')
def get_login_state():
    """获取扫码登录流程状态（轻量，不含二维码图片）。"""
    try:
        import auth as auth_mod
        return jsonify({
            "success": True,
            "status": getattr(auth_mod, 'login_status', None),
            "source": getattr(auth_mod, 'login_source', None)
        })
    except Exception as e:
        logger.error(f"获取登录状态失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@api_bp.route('/status')
def get_status():
    """获取系统状态 (公开)"""
    cfg = Config()
    sources = cfg.get_auth_sources()
    labels = cfg.get_auth_labels()
    source_recipient_map = cfg.get_source_recipient_map()
    cookies = {}
    for s in sources:
        c, _ua = cfg.get_auth(source=s)
        if c:
            cookies[s] = c

    # 兼容旧字段：has_cookie / cookie_preview
    cookie = next(iter(cookies.values()), cfg.get("auth", "cookie"))
    interval = cfg.get_int("system", "interval", 900)
    next_check_in = system_status.get("next_check_in", interval)
    
    return jsonify({
        "success": True,
        "has_cookie": bool(cookie),
        "cookie_preview": cookie[:20] + "..." if cookie else "",
        "is_monitoring": system_status["is_monitoring"],
        "last_check_time": system_status["last_check_time"],
        "last_error": system_status["last_error"],
        "consecutive_failures": system_status["consecutive_failures"],
        "interval": interval,
        "next_check_in": next_check_in,
        "rooms": system_status["last_check_data"] or [],
        "auth_sources": sources,
        "auth_labels": labels,
        "auth_configured": list(cookies.keys()),
        # 公开接口不返回收件人列表，只返回哪些 source 配置了默认收件人
        "notify_sources_configured": list(source_recipient_map.keys()),
        "source_status": system_status.get("sources", {})
    })

@api_bp.route('/config', methods=['GET', 'POST'])
def manage_config():
    """读取/更新配置 (需要管理员权限)"""
    # === 权限验证 ===
    if not check_auth():
        return jsonify({"success": False, "message": "权限不足: 需要管理员Token"}), 401
    
    cfg = Config()
    
    if request.method == 'POST':
        try:
            data = request.json

            # === auth_sources（多宿舍 sources 列表）===
            # 允许：
            # - {"auth_sources": "a,b,c"}
            # - {"auth_sources": ["a", "b", "c"]}
            if 'auth_sources' in data:
                raw = data.get('auth_sources')
                if isinstance(raw, list):
                    sources = [str(x).strip() for x in raw if str(x).strip()]
                elif isinstance(raw, str):
                    sources = [x.strip() for x in raw.replace(';', ',').replace('\n', ',').split(',') if x.strip()]
                elif raw is None:
                    sources = []
                else:
                    return jsonify({"success": False, "message": "auth_sources 类型错误"}), 400

                # 过滤 legacy（legacy 由后端自动推断，不应手动配置）
                sources = [s for s in sources if s.casefold() != 'legacy']

                # 校验 source 名称
                for s in sources:
                    if not re.match(r'^[A-Za-z0-9_-]+$', s):
                        return jsonify({"success": False, "message": f"source 名称不合法: {s}（仅允许 A-Za-z0-9_-）"}), 400

                # 去重（大小写不敏感）但保留第一个出现的大小写
                seen = set()
                normalized = []
                for s in sources:
                    k = s.casefold()
                    if k in seen:
                        continue
                    seen.add(k)
                    normalized.append(s)
                cfg._ensure_section('system')
                cfg.cp.set('system', 'auth_sources', ','.join(normalized))

            # 房间收件人映射（notify.rooms）
            # 允许两种格式：
            # - {"room_recipients": {"3-721A空调": "a@x.com,b@y.com", "3-721B空调": ["c@z.com"]}}
            # - {"room_recipients": [{"room": "...", "recipients": "..."}, ...]}  (前端可选)
            if 'room_recipients' in data:
                room_payload = data.get('room_recipients')
                room_map = {}
                if isinstance(room_payload, dict):
                    room_map = room_payload
                elif isinstance(room_payload, list):
                    for item in room_payload:
                        if not isinstance(item, dict):
                            continue
                        room_key = str(item.get('room') or '').strip()
                        if not room_key:
                            continue
                        room_map[room_key] = item.get('recipients')
                elif room_payload is None:
                    room_map = {}
                else:
                    return jsonify({"success": False, "message": "room_recipients 类型错误"}), 400

                def is_reserved_room_key(k: str) -> bool:
                    kk = (k or "").strip()
                    return (not kk) or (kk.casefold() == "config_file")

                # 过滤保留键
                room_map = {str(k).strip(): v for k, v in room_map.items() if not is_reserved_room_key(str(k))}

                # 以本次提交为准：移除未提交的旧映射
                existing = set(cfg.get_room_recipient_map().keys())
                incoming = set([str(k).strip() for k in room_map.keys() if str(k).strip() and str(k).strip().casefold() != "config_file"])
                for old_room in existing - incoming:
                    cfg.set_room_recipients(old_room, [])

                # 写入新映射（允许清空某个房间）
                for room_key, recipients in room_map.items():
                    if str(room_key).strip().casefold() == "config_file":
                        continue
                    cfg.set_room_recipients(room_key, recipients)

            # source 默认收件人映射（notify.sources）
            # 允许两种格式：
            # - {"source_recipients": {"X3-721B": "a@x.com,b@y.com"}}
            # - {"source_recipients": [{"source": "X3-721B", "recipients": ["a@x.com"]}, ...]}
            if 'source_recipients' in data:
                payload = data.get('source_recipients')
                src_map = {}
                if isinstance(payload, dict):
                    src_map = payload
                elif isinstance(payload, list):
                    for item in payload:
                        if not isinstance(item, dict):
                            continue
                        src = str(item.get('source') or '').strip()
                        if not src:
                            continue
                        src_map[src] = item.get('recipients')
                elif payload is None:
                    src_map = {}
                else:
                    return jsonify({"success": False, "message": "source_recipients 类型错误"}), 400

                def is_reserved_source_key(k: str) -> bool:
                    kk = (k or "").strip()
                    return (not kk) or (kk.casefold() == "config_file")

                src_map = {str(k).strip(): v for k, v in src_map.items() if not is_reserved_source_key(str(k))}

                existing = set(cfg.get_source_recipient_map().keys())
                incoming = set([str(k).strip() for k in src_map.keys() if str(k).strip() and str(k).strip().casefold() != "config_file"])
                for old_src in existing - incoming:
                    cfg.set_source_recipients(old_src, [])

                for src, recipients in src_map.items():
                    if str(src).strip().casefold() == "config_file":
                        continue
                    cfg.set_source_recipients(src, recipients)

            # source 显示名称（auth.labels）
            # - {"auth_labels": {"X3-721B": "西三721B"}}
            # - {"auth_labels": [{"source": "X3-721B", "label": "西三721B"}, ...]}
            if 'auth_labels' in data:
                payload = data.get('auth_labels')
                labels_map = {}
                if isinstance(payload, dict):
                    labels_map = payload
                elif isinstance(payload, list):
                    for item in payload:
                        if not isinstance(item, dict):
                            continue
                        src = str(item.get('source') or '').strip()
                        if not src:
                            continue
                        labels_map[src] = item.get('label')
                elif payload is None:
                    labels_map = {}
                else:
                    return jsonify({"success": False, "message": "auth_labels 类型错误"}), 400

                section = 'auth.labels'
                cfg._ensure_section(section)
                defaults = set(cfg.cp.defaults().keys())
                # 先清理旧值（以本次提交为准）
                if cfg.cp.has_section(section):
                    for key, _v in list(cfg.cp.items(section)):
                        k = str(key or '').strip()
                        if not k:
                            continue
                        if k in defaults or k.casefold() == 'config_file':
                            continue
                        if k not in labels_map:
                            cfg.cp.remove_option(section, k)

                for src, label in labels_map.items():
                    s = str(src or '').strip()
                    if not s or s in defaults or s.casefold() == 'config_file':
                        continue
                    v = str(label or '').strip()
                    if v:
                        cfg.cp.set(section, s, v)
                    else:
                        if cfg.cp.has_option(section, s):
                            cfg.cp.remove_option(section, s)
            
            # 更新配置
            if 'interval' in data:
                cfg.cp.set("system", "interval", str(data['interval']))
            if 'threshold' in data:
                cfg.cp.set("system", "low_power_threshold", str(data['threshold']))
            if 'cooldown_seconds' in data:
                cfg.cp.set("system", "low_power_alert_cooldown_seconds", str(data['cooldown_seconds']))
            if 'recipients' in data:
                cfg.cp.set("notify", "to", data['recipients'])
            if 'server_ip' in data:
                cfg.cp.set("system", "server_ip", data['server_ip'])
            
            # 保存到文件
            # 始终写入当前项目的 config.ini，避免被 [DEFAULT].config_file 指向旧路径
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                cfg.cp.write(f)
            
            logger.info("💾 配置已更新")
            return jsonify({"success": True, "message": "配置已保存"})
        except Exception as e:
            logger.error(f"配置更新失败: {e}")
            return jsonify({"success": False, "message": str(e)}), 500
    else:
        # 返回当前配置 (包含敏感信息，所以必须鉴权)
        return jsonify({
            "success": True,
            "config": {
                "auth_sources": cfg.get_auth_sources(),
                "interval": cfg.get_int("system", "interval", 900),
                "threshold": cfg.get_float("system", "low_power_threshold", 15.0),
                "cooldown_seconds": cfg.get_int("system", "low_power_alert_cooldown_seconds", 21600),
                "recipients": cfg.get("notify", "to"),
                "smtp_server": cfg.get("notify", "smtp_server"),
                "smtp_username": cfg.get("notify", "smtp_username"),
                "server_ip": cfg.get("system", "server_ip"),
                "web_port": cfg.get_int("system", "web_port", 5000),
                "room_recipients": cfg.get_room_recipient_map(),
                "source_recipients": cfg.get_source_recipient_map(),
                "auth_labels": cfg.get_auth_labels()
            }
        })

@api_bp.route('/test-email', methods=['POST'])
def test_email():
    """发送测试邮件 (建议添加权限，防止被恶意利用)"""
    if not check_auth():
        return jsonify({"success": False, "message": "权限不足"}), 401

    try:
        data = request.get_json(silent=True) or {}
        to_raw = data.get('to')

        # 兼容：
        # - {"to": "a@x.com"}
        # - {"to": ["a@x.com", "b@y.com"]}
        recipients = []
        if isinstance(to_raw, list):
            recipients = [str(x).strip() for x in to_raw if str(x).strip()]
        elif isinstance(to_raw, str):
            to_str = to_raw.strip()
            if to_str:
                # 允许逗号/分号/换行分隔
                recipients = [x.strip() for x in to_str.replace(';', ',').replace('\n', ',').split(',') if x.strip()]
        elif to_raw is None:
            recipients = []
        else:
            return jsonify({"success": False, "message": "参数 to 类型错误"}), 400

        # 如果前端指定了收件人，则校验格式
        if recipients:
            for mail in recipients:
                if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', mail):
                    return jsonify({"success": False, "message": f"邮箱格式不正确: {mail}"}), 400

        cfg = Config()
        cfg.send_email(
            "🧪 测试邮件",
            "这是一封来自宿舍电费监控系统的测试邮件。\n如果您收到此邮件,说明邮件配置正常。",
            to_override=recipients if recipients else None
        )
        suffix = f"至 {', '.join(recipients)}" if recipients else ""
        return jsonify({"success": True, "message": f"测试邮件已发送{suffix}"})
    except Exception as e:
        logger.error(f"测试邮件发送失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@api_bp.route('/toggle-monitoring', methods=['POST'])
def toggle_monitoring():
    """暂停/恢复监控 (需要管理员权限)"""
    if not check_auth():
        return jsonify({"success": False, "message": "权限不足"}), 401

    from monitor import system_status
    data = request.json
    system_status["is_monitoring"] = data.get("enabled", True)
    status = "已恢复" if system_status["is_monitoring"] else "已暂停"
    logger.info(f"📊 监控状态: {status}")
    return jsonify({"success": True, "message": f"监控{status}"})

@api_bp.route('/manual-cookie', methods=['POST'])
def set_manual_cookie():
    """手动设置Cookie (普通用户可用，或根据需求加锁)"""
    # 这里为了方便暂时不加锁，如果希望只有管理员能设置Cookie，请取消下面注释
    # if not check_auth(): return jsonify({"success": False, "message": "权限不足"}), 401

    try:
        data = request.json
        source = (data.get('source') or '').strip() or None
        cookie = data.get('cookie', '').strip()
        ua = data.get('user_agent', '')
        
        if not cookie:
            return jsonify({"success": False, "message": "Cookie不能为空"}), 400
        
        # 验证Cookie格式
        if not cookie.startswith('JSESSIONID='):
            cookie = f"JSESSIONID={cookie}"
        
        success = manual_set_cookie(cookie, ua, source=source)
        
        if success:
            suffix = f" (source={source})" if source else ""
            return jsonify({"success": True, "message": f"Cookie已保存{suffix},请等待下次检测验证"})
        else:
            return jsonify({"success": False, "message": "Cookie保存失败"}), 500
            
    except Exception as e:
        logger.error(f"手动设置Cookie失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ===========================
# 管理员认证相关接口
# ===========================

@api_bp.route('/admin/check')
def check_admin():
    """检查是否已设置管理员Token"""
    cfg = Config()
    has_token = bool(cfg.get_admin_token())
    return jsonify({
        "success": True,
        "has_token": has_token
    })

@api_bp.route('/admin/setup', methods=['POST'])
def setup_admin():
    """首次设置管理员Token"""
    try:
        cfg = Config()
        
        # 检查是否已经设置过
        if cfg.get_admin_token():
            return jsonify({"success": False, "message": "管理员Token已设置,请使用登录功能"}), 400
        
        data = request.json
        new_token = data.get('token', '').strip()
        
        if not new_token or len(new_token) < 6:
            return jsonify({"success": False, "message": "Token长度至少6位"}), 400
        
        cfg.set_admin_token(new_token)
        logger.info("🔐 首次设置管理员Token成功")
        
        return jsonify({
            "success": True,
            "message": "管理员Token设置成功",
            "token": new_token
        })
        
    except Exception as e:
        logger.error(f"设置管理员Token失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@api_bp.route('/admin/login', methods=['POST'])
def admin_login():
    """管理员登录验证"""
    try:
        data = request.json
        token = data.get('token', '').strip()
        
        if not token:
            return jsonify({"success": False, "message": "请输入Token"}), 400
        
        cfg = Config()
        
        if cfg.verify_admin_token(token):
            logger.info("✅ 管理员登录成功")
            return jsonify({
                "success": True,
                "message": "登录成功",
                "token": token
            })
        else:
            logger.warning("❌ 管理员登录失败:Token错误")
            return jsonify({"success": False, "message": "Token错误"}), 401
            
    except Exception as e:
        logger.error(f"管理员登录失败: {e}")
        return jsonify({"success": False, "message": str(e)}), 500