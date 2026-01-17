"""
登录认证模块 - 负责微信扫码登录
"""
import os
import time
import threading
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from config import Config, logger
from monitor import parse_data, TARGET_URL, request_immediate_check

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_URL = "https://ids.lit.edu.cn/authserver/login?service=http%3A%2F%2Fzhyd.sec.lit.edu.cn%2Fzhyd%2Fsydl%2Findex"

# 登录状态
driver_instance = None
login_status = "waiting"
qr_image_b64 = ""
qr_image_ts = 0.0
driver_lock = threading.RLock()
login_source = None
login_run_id = 0


def restart_login(source=None):
    """强制重启扫码登录流程（用于二维码失效/卡住）。

    会尝试关闭当前 driver，并重置状态后重新启动 selenium_login_task。
    """
    global driver_instance, login_status, qr_image_b64, qr_image_ts, login_source, login_run_id

    # 新的一次登录尝试：让旧线程识别为过期并尽快退出
    login_run_id += 1
    run_id = login_run_id

    login_source = source
    qr_image_b64 = ""
    qr_image_ts = 0.0
    login_status = "processing"

    with driver_lock:
        if driver_instance:
            try:
                driver_instance.quit()
            except Exception:
                pass
            driver_instance = None

    threading.Thread(target=selenium_login_task, args=(source, run_id), daemon=True).start()


def get_chrome_options():
    """获取Chrome浏览器配置"""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument('--ignore-certificate-errors')
    opts.add_argument('--allow-running-insecure-content')
    opts.add_argument('--disable-web-security')
    opts.add_argument('--disable-features=HttpsUpgrades,HttpsFirstModeV2ForEngagedSites')
    return opts


def get_chrome_service():
    """获取Chrome驱动服务"""
    local_driver_path = os.path.join(BASE_DIR, "chromedriver.exe")
    
    if os.path.exists("/usr/bin/chromium"):
        logger.info("💻 检测到Linux环境,使用系统Chromium")
        return Service("/usr/bin/chromedriver")
    elif os.path.exists(local_driver_path):
        return Service(executable_path=local_driver_path)
    else:
        logger.info("⬇️ 尝试自动下载驱动...")
        return Service(ChromeDriverManager().install())


def handle_login_success(driver, source=None):
    """
    处理登录成功后的操作
    
    Args:
        driver: Selenium WebDriver实例
    """
    global login_status
    time.sleep(2)
    
    # 确保在目标页面
    if "index" not in driver.current_url:
        driver.get(TARGET_URL)
        time.sleep(2)

    # 提取JSESSIONID
    cookies = driver.get_cookies()
    jsessionid = None
    for c in cookies:
        if c['name'] == 'JSESSIONID':
            jsessionid = c['value']
            break
    
    if not jsessionid:
        logger.error("❌ 未找到JSESSIONID,登录可能失败")
        login_status = "failed"
        return
    
    cookie_str = f"JSESSIONID={jsessionid}"
    ua = driver.execute_script("return navigator.userAgent;")
    
    logger.info(f"🔐 保存Cookie: {cookie_str[:50]}...")

    # 保存到配置
    Config().update_auth(cookie_str, ua, source=source)

    # 立刻触发下一轮抓取，避免等待 interval
    request_immediate_check(reason=f"login_success source={source or 'default'}")

    # 解析数据并发送邮件
    data = parse_data(driver.page_source)
    msg_content = "监控已恢复。"
    if data:
        lines = [f"🏠 {d['room']} | ⚡ {d['kwh']}度 | 💰 {d['money']}元" for d in data]
        msg_content += "\n\n" + "\n".join(lines)

    Config().send_email("✅ 监控恢复成功", msg_content)
    logger.info("🎉 修复成功并已更新配置")
    login_status = "success"


def selenium_login_task(source=None, run_id=None):
    """扫码登录任务"""
    global driver_instance, login_status, qr_image_b64, qr_image_ts, login_source, login_run_id

    # 为本次任务分配 run_id；若传入则表示由 restart_login 强制启动
    with driver_lock:
        if run_id is None:
            login_run_id += 1
            run_id = login_run_id
        else:
            login_run_id = int(run_id)
    # 记录本次登录要写入的 source
    login_source = source
    login_status = "processing"
    qr_image_b64 = ""

    logger.info(f"🚀 准备启动浏览器驱动... (run_id={run_id})")

    try:
        opts = get_chrome_options()
        service = get_chrome_service()
        driver = webdriver.Chrome(service=service, options=opts)
        my_driver = driver
        with driver_lock:
            driver_instance = my_driver

        logger.info("✅ 浏览器启动成功!正在清理Cookie...")
        
        driver.delete_all_cookies()
        driver.get(LOGIN_URL)

        # 自动点击微信登录
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//li[contains(text(), '微信登录')]"))
            ).click()
        except:
            pass

        # 等待二维码加载
        WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.ID, "wechatQrcode"))
        )
        login_status = "qr_ready"
        logger.info("📸 二维码已就绪")

        # 缓存二维码，避免前端轮询频繁触发 webdriver 调用
        try:
            with driver_lock:
                ele = driver.find_element(By.ID, "wechatQrcode")
                qr_image_b64 = ele.screenshot_as_base64 or ""
                qr_image_ts = time.time()
        except Exception:
            qr_image_b64 = ""
            qr_image_ts = 0.0

        start = time.time()
        last_url = ""

        # 监控登录过程(最多3分钟)
        while time.time() - start < 180:
            # 如果用户触发了刷新/重启登录，让旧线程立刻退出，避免访问已关闭的 driver
            if run_id != login_run_id:
                logger.info(f"🛑 旧登录任务退出 (stale run_id={run_id}, current={login_run_id})")
                return

            # 检测二维码是否失效（页面通常会提示）
            try:
                page = driver.page_source or ""
                if "二维码" in page and ("失效" in page or "已过期" in page):
                    logger.warning("⚠️ 检测到二维码可能已失效，尝试刷新二维码")
                    try:
                        driver.delete_all_cookies()
                    except Exception:
                        pass
                    driver.get(LOGIN_URL)
                    try:
                        WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, "//li[contains(text(), '微信登录')]"))
                        ).click()
                    except Exception:
                        pass
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.visibility_of_element_located((By.ID, "wechatQrcode"))
                        )
                        with driver_lock:
                            ele = driver.find_element(By.ID, "wechatQrcode")
                            qr_image_b64 = ele.screenshot_as_base64 or ""
                            qr_image_ts = time.time()
                        login_status = "qr_ready"
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                curr = driver.current_url
            except Exception as e:
                # 常见于 chromedriver 已退出/会话断开：WinError 10061
                if run_id != login_run_id:
                    return
                if login_status == "success":
                    logger.warning(f"⚠️ 登录已成功但驱动会话已断开: {e}")
                    return
                raise

            if curr != last_url:
                logger.info(f"🔗 URL变动: {curr[:80]}...")
                last_url = curr

            # 方法1: 检测ticket参数(后台验证)
            if "ticket=" in curr:
                logger.info("🕵️‍♂️ 检测到Ticket,启动后台验证...")

                try:
                    ua = driver.execute_script("return navigator.userAgent;")
                    sess = requests.Session()
                    sess.headers.update({"User-Agent": ua})

                    # 1) 访问带 ticket 的回调地址（内部会跟随到业务系统）
                    req_resp = sess.get(curr, verify=False, timeout=15, allow_redirects=True)

                    # 2) 再显式访问一次目标页，确保业务域种下 JSESSIONID
                    try:
                        sess.get(TARGET_URL, verify=False, timeout=15, allow_redirects=True)
                    except Exception:
                        pass

                    # 3) 从会话 cookie jar 里取业务域的 JSESSIONID
                    cookie_dict = {}
                    try:
                        cookie_dict.update(sess.cookies.get_dict(domain="zhyd.sec.lit.edu.cn"))
                    except Exception:
                        pass
                    try:
                        # 兜底：不带 domain 取一次
                        cookie_dict.update(sess.cookies.get_dict())
                    except Exception:
                        pass

                    if "JSESSIONID" in cookie_dict:
                        cookie_str = f"JSESSIONID={cookie_dict['JSESSIONID']}"
                        logger.info("🎉 后台验证成功!获取到Cookie")
                        Config().update_auth(cookie_str, ua, source=source)
                        request_immediate_check(reason=f"ticket_success source={source or 'default'}")
                        Config().send_email(
                            "✅ 监控恢复",
                            f"通过后台截获Ticket成功恢复登录。\nCookie: {cookie_str}"
                        )
                        login_status = "success"
                        return

                    logger.warning(
                        "⚠️ 后台请求未获取到JSESSIONID,等待浏览器重试..."
                        f"(final_url={getattr(req_resp, 'url', '')[:80]})"
                    )
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"❌ 后台验证出错: {e}")

            # 如果浏览器已经跳转到业务域，优先尝试从浏览器直接拿 cookie
            if "zhyd.sec.lit.edu.cn" in curr and "authserver" not in curr:
                try:
                    maybe = driver.get_cookie("JSESSIONID")
                    if maybe and maybe.get("value"):
                        logger.info("🎉 检测到已进入业务页，尝试读取浏览器 Cookie")
                        handle_login_success(driver, source=source)
                        return
                except Exception:
                    pass

            # 方法2: 常规Cookie检查
            cookies = driver.get_cookies()
            for c in cookies:
                if c['name'] == "JSESSIONID" and c['value'] and "authserver" not in curr:
                    logger.info("🎉 浏览器自身登录成功")
                    handle_login_success(driver, source=source)
                    return

            time.sleep(0.5)

        login_status = "timeout"

    except Exception as e:
        # 避免在已成功或任务已过期时覆盖状态
        if run_id != login_run_id:
            return
        if login_status == "success":
            logger.warning(f"⚠️ 登录已成功但后续出现 Selenium 异常: {e}")
            return
        logger.error(f"Selenium错误: {e}")
        login_status = "failed"
    finally:
        # 仅关闭本次任务自己创建的 driver；并且只在全局仍指向它时才清空
        try:
            my = locals().get("my_driver")
            if my:
                try:
                    my.quit()
                except Exception:
                    pass
                with driver_lock:
                    if driver_instance is my:
                        driver_instance = None
        finally:
            if login_status != "success":
                logger.info("🛑 浏览器已关闭")


def get_qrcode_image():
    """
    获取二维码图片(Base64)
    
    Returns:
        str: Base64编码的图片,失败返回空字符串
    """
    global driver_instance, login_status, qr_image_b64, qr_image_ts

    if login_status != "qr_ready":
        return ""

    # 不自动刷新：如果已有缓存二维码，直接返回。
    # 需要换码时由前端“手动刷新”按钮触发重启登录流程。
    if qr_image_b64:
        return qr_image_b64

    if driver_instance:
        try:
            with driver_lock:
                ele = driver_instance.find_element(By.ID, "wechatQrcode")
                qr_image_b64 = ele.screenshot_as_base64 or ""
                qr_image_ts = time.time()
                return qr_image_b64
        except Exception:
            return ""

    return ""


def manual_set_cookie(cookie, ua=None, source=None):
    """
    手动设置Cookie
    
    Args:
        cookie: Cookie字符串
        ua: User-Agent(可选)
        
    Returns:
        bool: 是否成功
    """
    try:
        if not ua:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        
        Config().update_auth(cookie, ua, source=source)
        request_immediate_check(reason=f"manual_cookie source={source or 'default'}")
        logger.info("✅ 手动Cookie设置成功")
        return True
    except Exception as e:
        logger.error(f"❌ 手动Cookie设置失败: {e}")
        return False