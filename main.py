"""
宿舍电费监控系统 - 主入口
"""
import os
import sys
import threading
import urllib3
from flask import Flask, render_template, jsonify, send_from_directory, request, redirect

# 确保无论从哪个工作目录启动，都能导入本项目同目录下的模块（config/api/monitor/auth 等）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import Config, logger
from monitor import monitor_task
import auth
from api import api_bp

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ['WDM_SSL_VERIFY'] = '0'

# Flask应用
app = Flask(__name__)
# 避免浏览器缓存静态页面导致前端更新不生效
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.register_blueprint(api_bp)

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')


@app.route('/')
def dashboard():
    """管理仪表盘"""
    try:
        return send_from_directory(STATIC_DIR, 'dashboard.html', max_age=0)
    except:
        return "<h1>404</h1><p>dashboard.html not found in static/</p>", 404


@app.route('/help', strict_slashes=False)
def help_page():
    """帮助文档"""
    return redirect("https://dorm-electricity.pages.dev/")


@app.route('/login')
def login():
    """扫码登录页面"""
    source = (request.args.get('source') or '').strip() or None
    force = (request.args.get('force') or '').strip()

    if force in ("1", "true", "yes", "on"):
        # 强制重启扫码流程（二维码失效/卡住时使用）
        auth.restart_login(source=source)
        return render_template('login.html')

    if auth.login_status == "processing":
        pass
    elif not auth.driver_instance:
        threading.Thread(target=auth.selenium_login_task, args=(source,), daemon=True).start()

    return render_template('login.html')


@app.route('/login-restart')
def login_restart():
    """手动重启扫码登录流程（用于二维码失效）。"""
    source = (request.args.get('source') or '').strip() or None
    auth.restart_login(source=source)
    return render_template('login.html')


@app.route('/login-status')
def get_login_status():
    """获取登录状态"""
    img_b64 = auth.get_qrcode_image()
    return jsonify({"status": auth.login_status, "img": img_b64, "source": auth.login_source})


if __name__ == '__main__':
    # 启动监控线程
    monitor_thread = threading.Thread(target=monitor_task, daemon=True)
    monitor_thread.start()

    # 启动Web服务
    cfg = Config()
    port = cfg.get_int("system", "web_port", 5000)
    
    # 获取显示的IP地址（优先使用配置的server_ip，否则使用localhost）
    server_ip = cfg.get("system", "server_ip")
    display_host = server_ip if server_ip else "127.0.0.1"

    logger.info(f"🚀 Web服务启动: http://0.0.0.0:{port}")
    logger.info(f"📱 管理面板: http://{display_host}:{port}/")
    logger.info(f"📖 帮助文档: https://dorm-electricity.pages.dev/")
    
    app.run(host='0.0.0.0', port=port, debug=False)