# 宿舍电费监控系统（dorm_v2.5）

## 现有目录结构（当前）

```
.
├─ main.py              # Flask 主入口：页面路由 + 启动监控线程 + 注册 API
├─ api.py               # /api 蓝图：状态接口、配置接口（管理员 token）等
├─ auth.py              # 微信扫码登录：Selenium 获取 JSESSIONID，并写入 config.ini
├─ monitor.py           # 监控核心：拉取电量页面、解析、合并多 source、低电量告警、退避
├─ config.py            # 配置/邮件/日志：读取 config.ini、收件人映射、管理员 token 等
├─ config.ini           # 运行时配置（包含 cookie/邮箱密码等敏感信息）
├─ requirements.txt     # Python 依赖
├─ static/
│  ├─ dashboard.html    # 管理面板（前端单页）
│  ├─ help.html         # 帮助页
│  └─ help_img/         # 帮助页图片
└─ templates/
   └─ login.html        # 扫码登录页（渲染模板）
```

## 模块职责（你现在的“分层”已经比较清晰）

- Web 层
  - main.py：
    - `/`：返回 static/dashboard.html
    - `/help`：返回 static/help.html
    - `/login`、`/login-restart`、`/login-status`：扫码登录流程
    - 启动后台线程 `monitor.monitor_task()`
  - api.py：统一挂在 `/api/*` 下（蓝图），提供状态、配置等 API

- 业务/服务层
  - monitor.py：
    - `fetch_data()`：带 Cookie 拉取电量页面
    - `parse_data()`：解析页面卡片数据
    - `monitor_task()`：循环抓取 + 多 source 合并 + 低电量告警 + 退避
    - `request_immediate_check()`：登录成功后唤醒下一轮抓取
  - auth.py：
    - Selenium 拉起微信登录、取 JSESSIONID
    - 写入 `config.ini` 的对应 `[auth.*]` 段
    - 登录成功后调用 `request_immediate_check()` 立刻刷新数据

- 配置/基础设施层
  - config.py：
    - 统一读取/写入 `config.ini`
    - 邮件发送（SMTP）
    - 收件人映射（按 room / source / group 回退）

## 配置文件说明（关键段落）

- `config.ini`：
  - `[system]`：抓取间隔、web 端口、低电量阈值、冷却时间、auth_sources
  - `[auth]` / `[auth.<source>]`：Cookie 与 UA（多宿舍/多账号）
  - `[notify]` / `[notify.rooms]` / `[notify.sources]` / `[notify.group_*]`：告警收件人
  - `[admin]`：`admin_token`（管理端 API 用）

> 建议：不要把包含 cookie、邮箱密码的 `config.ini` 提交到 Git；用 `config.example.ini` 做模板。

## 建议的“下一步整理”（可选，非必须）

如果你想进一步让项目更像一个标准 Python 应用（便于扩展/测试），可以考虑未来重构成：

```
.
├─ app/
│  ├─ __init__.py        # create_app 工厂
│  ├─ web.py             # 页面路由（dashboard/help/login）
│  ├─ api/
│  │  ├─ __init__.py
│  │  └─ routes.py        # 原 api.py
│  ├─ services/
│  │  ├─ monitor.py       # 原 monitor.py
│  │  └─ auth.py          # 原 auth.py
│  └─ core/
│     └─ config.py        # 原 config.py
├─ templates/
├─ static/
├─ config.ini
└─ requirements.txt
```

我可以在你确认后，帮你把上述重构真正落地（包含 import 路径调整、启动方式保持一致）。
