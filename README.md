# 宿舍电费监控系统（dorm_v2.5）

一个面向校园宿舍场景的电费/余额监控工具：定时抓取电量页面，支持微信扫码自动更新 Cookie，多账号（多 source）轮询合并展示，并在低电量或 Cookie 失效时发送邮件告警。

## 目录

- [宿舍电费监控系统（dorm\_v2.5）](#宿舍电费监控系统dorm_v25)
  - [目录](#目录)
  - [项目亮点](#项目亮点)
  - [给部署者：Docker 部署教程](#给部署者docker-部署教程)
    - [部署前准备](#部署前准备)
    - [首次部署（推荐 docker compose）](#首次部署推荐-docker-compose)
    - [升级/重建](#升级重建)
    - [查看日志与常用运维命令](#查看日志与常用运维命令)
  - [给用户：使用教程](#给用户使用教程)
    - [打开页面](#打开页面)
    - [扫码登录（推荐）](#扫码登录推荐)
    - [手动输入 Cookie](#手动输入-cookie)
    - [理解仪表盘与告警](#理解仪表盘与告警)
  - [配置说明（config.ini）](#配置说明configini)
    - [\[system\]](#system)
    - [\[auth\] / \[auth.\]](#auth--auth)
    - [\[notify\]（SMTP）](#notifysmtp)
    - [\[notify.rooms\] / \[notify.sources\] / \[notify.group\_\*\]](#notifyrooms--notifysources--notifygroup_)
    - [\[admin\]](#admin)
  - [API 接口速查](#api-接口速查)
  - [常见问题/排障](#常见问题排障)
    - [1) 容器启动正常，但仪表盘一直没数据](#1-容器启动正常但仪表盘一直没数据)
    - [2) 收不到邮件](#2-收不到邮件)
    - [3) 修复邮件里的扫码链接打不开](#3-修复邮件里的扫码链接打不开)
  - [开发者参考：目录结构与模块职责](#开发者参考目录结构与模块职责)
    - [现有目录结构（当前）](#现有目录结构当前)
    - [模块职责](#模块职责)

---

## 项目亮点

- 多账号（多 source）轮询：每个 source 独立保存 Cookie/UA，监控线程按列表轮询并合并展示。
- 两类核心告警：
  - 低电量告警：低于阈值自动发邮件（带冷却时间，防止轰炸）。
  - Cookie 失效修复提醒：连续失败且判定需要重新登录时，自动发“修复邮件”，邮件中包含可点击扫码链接。
- 管理员鉴权：配置/测试邮件/暂停监控等接口需要管理员 Token。
- Docker 友好：镜像内安装 Chromium + chromedriver + 中文字体，适配 headless 扫码登录。

---

## 给部署者：Docker 部署教程

本项目已提供 [Dockerfile](Dockerfile) 与 [docker-compose.yml](docker-compose.yml)。推荐使用 docker compose 部署，可将本地 `config.ini` 挂载到容器内，保证 Cookie 和邮件配置持久化。

### 部署前准备

1) 服务器/电脑要求

- CPU/内存：一般 1C2G 足够（Chrome headless 启动时会瞬间占用一些资源）。
- 网络：需能访问学校电量页面与统一认证页面；SMTP 需要能访问邮箱服务器。

2) 安装 Docker 与 Compose

- Windows：安装 Docker Desktop（自带 compose）。
- Linux：安装 Docker Engine + docker compose 插件。

3) 准备配置文件

首次部署建议：复制示例配置文件并按需修改。

```bash
cp config.example.ini config.ini
```

重要：`config.ini` 包含 Cookie、SMTP 密码等敏感信息，请不要提交到 Git。

### 首次部署（推荐 docker compose）

在项目根目录执行：

```bash
docker compose up -d --build
```

启动后访问（默认 5000 端口）：

- 管理面板：`http://<服务器IP>:5000/`
- 帮助页：`http://<服务器IP>:5000/help`
- 扫码登录：`http://<服务器IP>:5000/login`

说明：compose 中已挂载 `./config.ini:/app/config.ini`，所以容器重启不会丢配置。

### 升级/重建

更新代码后（例如 `git pull`），执行：

```bash
docker compose up -d --build
```

如果需要清理旧镜像：

```bash
docker image prune -f
```

### 查看日志与常用运维命令

```bash
# 查看日志
docker logs -f dorm_monitor

# 重启服务
docker restart dorm_monitor

# 停止并删除容器
docker compose down
```

---

## 给用户：使用教程

用户视角只需要做三件事：打开仪表盘 → 配置 Cookie → 设置告警邮件（如果需要）。

### 打开页面

在浏览器访问：

- 仪表盘：首页 `http://<服务器IP>:5000/`
- 帮助页：`http://<服务器IP>:5000/help`

### 扫码登录（推荐）

1) 打开扫码页：`http://<服务器IP>:5000/login`
2) 用微信扫码完成登录
3) 登录成功后系统会自动保存 `JSESSIONID` 并触发一次“立即刷新”，通常几十秒内仪表盘会出现数据。

多账号（多 source）时：

- 打开 `http://<服务器IP>:5000/login?source=<source>` 给指定账号写入 Cookie

二维码卡住/过期：

- `http://<服务器IP>:5000/login?force=1` 或 `http://<服务器IP>:5000/login-restart`

### 手动输入 Cookie

如果你不方便扫码（或需要快速修复），可以从浏览器开发者工具中提取 Cookie（只需要 `JSESSIONID=...`），在仪表盘里走“手动输入 Cookie”。

系统也提供 API：`POST /api/manual-cookie`（详见下方 API 速查）。

### 理解仪表盘与告警

- “登录状态”：展示当前已配置/可用的 source 数量、登录状态等。
- “监控服务”：可由管理员暂停/恢复。
- 房间卡片：显示每个表计/房间的剩余电量（度）与余额（元）。

告警行为：

- 低电量：当剩余电量 < `low_power_threshold`，按“房间收件人 → source 收件人 → 默认收件人/分组回退”的优先级发送邮件。
- Cookie 失效：某个 source 连续失败且判定需要重新登录后，会给对应联系人发“修复邮件”，邮件里包含扫码链接。

---

## 配置说明（config.ini）

配置文件路径：容器内为 `/app/config.ini`，通过 compose 挂载到宿主机项目根目录的 `config.ini`。

建议从示例开始： [config.example.ini](config.example.ini)

### [system]

- `interval`：抓取间隔（秒）。
- `web_port`：Web 服务端口（compose 映射也要同步）。
- `server_ip`：用于生成邮件中的扫码链接（必须是收件人能访问的地址）。
- `low_power_threshold`：低电量阈值（度）。
- `low_power_alert_cooldown_seconds`：低电量告警冷却时间（秒）。
- `auth_sources`：要轮询的 source 列表（逗号/分号/换行分隔）。

### [auth] / [auth.<source>]

- `cookie`：形如 `JSESSIONID=...`
- `user_agent`：浏览器 UA（扫码登录自动写入；手动输入时可不填，系统会用默认）。

### [notify]（SMTP）

- `smtp_server` / `smtp_port` / `smtp_tls`
- `smtp_username` / `smtp_password`：很多邮箱需要“SMTP 授权码”，不是登录密码
- `from`：发件人
- `to`：默认收件人（逗号分隔）

### [notify.rooms] / [notify.sources] / [notify.group_*]

收件人优先级：

1) `notify.rooms`：按房间文本精准匹配（“绑定房间”字段）
2) `notify.sources`：按 source 默认收件人
3) `notify.group_a/b/k`：兼容旧模式的分组回退
4) `notify.to`：最后兜底

### [admin]

- `admin_token`：管理员 Token（用于配置/测试邮件/暂停监控等）

---

## API 接口速查

Base：`/api/*`，返回 JSON。

公开接口：

- `GET /api/status`：系统状态（监控开关、上次数据、sources 状态等）
- `GET /api/login-state`：扫码登录状态（不含二维码图片）

需要管理员 Token（请求头 `X-Admin-Token: <token>`）：

- `GET /api/config`：读取配置（包含敏感信息）
- `POST /api/config`：保存配置（interval/threshold/cooldown/auth_sources/auth_labels/收件人映射等）
- `POST /api/test-email`：发送测试邮件
- `POST /api/toggle-monitoring`：暂停/恢复监控
- `GET /api/admin/check` / `POST /api/admin/setup` / `POST /api/admin/login`

Cookie 相关：

- `POST /api/manual-cookie`：手动写入 Cookie（可指定 source）

---

## 常见问题/排障

### 1) 容器启动正常，但仪表盘一直没数据

- 先看日志：`docker logs -f dorm_monitor`
- 常见原因：
  - Cookie 未配置或已失效：去 `/login` 扫码更新。
  - 学校系统 502/超时：稍后重试（系统会自动退避）。

### 2) 收不到邮件

- `notify.to` 是否配置
- SMTP 是否可用（QQ 邮箱通常要开 SMTP 并使用授权码）
- 垃圾箱/拦截
- 如果配置了 `notify.rooms`/`notify.sources`，收件人可能被更高优先级覆盖

### 3) 修复邮件里的扫码链接打不开

- 检查 `system.server_ip`：要填“收件人能访问到的 IP/域名”，不要填 127.0.0.1（除非收件人就在服务器本机）
- 检查端口映射与防火墙

---

## 开发者参考：目录结构与模块职责

### 现有目录结构（当前）

```
.
├─ main.py              # Flask 主入口：页面路由 + 启动监控线程 + 注册 API
├─ api.py               # /api 蓝图：状态接口、配置接口（管理员 token）等
├─ auth.py              # 微信扫码登录：Selenium 获取 JSESSIONID，并写入 config.ini
├─ monitor.py           # 监控核心：拉取电量页面、解析、合并多 source、低电量告警、退避
├─ config.py            # 配置/邮件/日志：读取 config.ini、收件人映射、管理员 token 等
├─ config.ini           # 运行时配置（包含 cookie/邮箱密码等敏感信息）
├─ config.example.ini   # 示例配置（推荐复制为 config.ini）
├─ requirements.txt     # Python 依赖
├─ Dockerfile           # Docker 镜像构建（含 Chromium + driver）
├─ docker-compose.yml   # compose 编排（挂载 config.ini）
├─ static/
│  ├─ dashboard.html    # 管理面板（前端单页）
│  ├─ help.html         # 帮助页
│  └─ help_img/         # 帮助页图片
└─ templates/
   └─ login.html        # 扫码登录页（渲染模板）
```

### 模块职责

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
    - `request_immediate_check()`：登录成功/手动写 Cookie 后唤醒下一轮抓取
  - auth.py：
    - Selenium 拉起微信登录、取 JSESSIONID
    - 写入 `config.ini` 的对应 `[auth.*]` 段

- 配置/基础设施层
  - config.py：
    - 统一读取/写入 `config.ini`
    - 邮件发送（SMTP）
    - 收件人映射（按 room / source / group 回退）
