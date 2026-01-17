function dashboard() {
  return {
    showTab: "dashboard",
    showManualCookie: false,
    showAuthSourcesModal: false,
    showAdminLogin: false,
    showSetup: false,
    showTestEmailModal: false,
    isAdmin: false,
    adminInputToken: "",
    newAdminToken: "",
    currentTime: "",

    status: {
      is_monitoring: true,
      has_cookie: false,
      last_check_time: null,
      rooms: [],
      interval: 900,
      auth_sources: [],
      auth_configured: [],
    },
    loginState: { status: null, source: null },
    // 预填一些配置数据以便预览
    config: {
      auth_sources: [],
      interval: 1800,
      threshold: 20,
      cooldown_seconds: 21600,
      recipients: "user@example.com, admin@test.com",
      smtp_server: "",
      server_ip: "192.168.3.10",
    },
    // 房间映射：room -> recipients[]（多对多）
    roomRecipientMap: {},
    // source 默认收件人：source -> recipients[]
    sourceRecipientMap: {},
    // source 显示名称：source -> label
    authLabelsMap: {},
    // auth_sources 编辑
    authSourcesList: [],
    authSourceInput: "",
    // 收件人管理（前端增强）
    recipientsList: [],
    recipientInput: "",
    // 测试邮件
    selectedRecipients: [],
    customRecipientEmail: "",
    testEmailMode: "select", // 'select' | 'custom'
    manualCookie: { source: "ac_a", cookie: "", ua: "" },
    manualCookieSourceLocked: false,
    toast: { show: false, message: "", type: "success" },
    // 登录按钮展示优化（sources 很多时）
    showAllAuthSources: false,
    maxAuthSourcesCollapsed: 6,

    init() {
      this.updateTime();
      setInterval(() => this.updateTime(), 1000);

      // 1. 检查是否需要初始化
      this.checkSystemSetup();

      // 2. 尝试自动登录
      this.tryAutoLogin();

      // 3. 加载状态
      this.loadStatus();
      setInterval(() => this.loadStatus(), 5000);

      // 登录流程状态（用于“一次只能扫一个”）
      this.loadLoginState();
      setInterval(() => this.loadLoginState(), 3000);

      // 初始化收件人列表
      this.syncRecipientsFromString();
      if (this.recipientsList.length > 0) {
        this.selectedRecipients = [this.recipientsList[0]];
      }
    },

    getDisplayAuthSources() {
      const sources = Array.isArray(this.status.auth_sources)
        ? this.status.auth_sources
        : [];
      // legacy 单源模式：只显示一个总状态
      if (sources.includes("legacy")) return ["legacy"];

      // 正常情况：直接按后端给的 sources 展示（不强行补 ac_a/ac_b/k）
      const cleaned = sources.filter((s) => s && s !== "legacy");
      if (cleaned.length) return cleaned;

      // 兜底：如果后端没给 sources（旧版本），至少显示 3 个宿舍
      return ["ac_a", "ac_b", "k"];
    },

    getLoginButtonSources() {
      const list = this.getDisplayAuthSources();
      if (this.showAllAuthSources) return list;
      const maxN = parseInt(this.maxAuthSourcesCollapsed || 6, 10);
      if (!maxN || maxN <= 0) return list;
      return list.slice(0, maxN);
    },

    getAuthSourceLabel(src) {
      const key = (src || "").toString();
      const labelMap =
        this.status &&
        this.status.auth_labels &&
        typeof this.status.auth_labels === "object"
          ? this.status.auth_labels
          : {};
      if (labelMap && labelMap[key]) return labelMap[key];
      const map = {
        ac_a: "A宿舍(空调)",
        ac_b: "B宿舍(空调)",
        k: "K宿舍(照明)",
        lighting: "照明",
        legacy: "单源模式",
      };
      return map[key] || key;
    },

    isLoginBusy() {
      const st =
        this.loginState && this.loginState.status ? this.loginState.status : "";
      return ["processing", "qr_ready"].includes(st);
    },

    isLoginLockedForSource(src) {
      if (!this.isLoginBusy()) return false;
      const cur =
        this.loginState && this.loginState.source
          ? this.loginState.source
          : null;
      if (!cur) return false;
      return cur !== src;
    },

    getLoginHref(src) {
      const key = (src || "").toString();
      let href =
        key === "legacy"
          ? "/login"
          : `/login?source=${encodeURIComponent(key)}`;
      if (this.isAuthSourceConnected(key)) {
        href += href.includes("?") ? "&force=1" : "?force=1";
      }
      return href;
    },

    getLoginButtonTitle(src) {
      if (this.isLoginLockedForSource(src)) {
        const cur =
          this.loginState && this.loginState.source
            ? this.getAuthSourceLabel(this.loginState.source)
            : "其他账号";
        return `正在为 ${cur} 扫码登录（一次只能扫一个）`;
      }
      return this.isAuthSourceConnected(src)
        ? "已连接：点击可重新扫码(覆盖)"
        : "点击打开二维码登录";
    },

    getLoginButtonClass(src) {
      if (this.isLoginLockedForSource(src)) {
        return "bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed";
      }
      return this.isAuthSourceConnected(src)
        ? "bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
        : "bg-gradient-to-r from-blue-500 to-blue-600 hover:from-blue-600 hover:to-blue-700 text-white shadow-blue-200 shadow-lg";
    },

    handleLoginClick(e, src) {
      if (this.isLoginLockedForSource(src)) {
        e.preventDefault();
        const cur =
          this.loginState && this.loginState.source
            ? this.getAuthSourceLabel(this.loginState.source)
            : "其他账号";
        this.showToast(`当前正在为 ${cur} 扫码，请先完成/关闭该流程`, "error");
        return;
      }
      if (this.isAuthSourceConnected(src)) {
        if (
          !confirm(
            `${this.getAuthSourceLabel(
              src
            )} 当前显示已连接。确定要重新扫码覆盖登录吗？`
          )
        ) {
          e.preventDefault();
        }
      }
    },

    openManualCookieForSource(src) {
      const key = (src || "").toString();
      this.manualCookie.source = key;
      this.manualCookieSourceLocked = true;
      this.showManualCookie = true;
    },

    closeManualCookie() {
      this.showManualCookie = false;
      this.manualCookieSourceLocked = false;
    },

    isAuthSourceConnected(src) {
      const key = (src || "").toString();
      // 优先使用后端提供的 per-source 状态：只有“最近抓取成功且当前无错误”才算已连接
      const per =
        this.status &&
        this.status.source_status &&
        this.status.source_status[key]
          ? this.status.source_status[key]
          : null;
      if (per) {
        return !!per.has_cookie && !per.last_error && !!per.last_ok_time;
      }

      // 兼容旧后端：没有 source_status 时只能退回到“是否配置了 cookie”
      if (key === "legacy") return !!this.status.has_cookie;
      const configured = Array.isArray(this.status.auth_configured)
        ? this.status.auth_configured
        : [];
      return configured.includes(key);
    },

    getLoginConnectedCount() {
      const list = this.getDisplayAuthSources();
      return list.filter((s) => this.isAuthSourceConnected(s)).length;
    },

    getLoginSummaryText() {
      const list = this.getDisplayAuthSources();
      const total = list.length;
      const connected = this.getLoginConnectedCount();
      if (total <= 1 && list[0] === "legacy") {
        return connected ? "已连接" : "未连接";
      }
      return `已连接 ${connected}/${total}`;
    },

    getLoginTitleText() {
      const list = this.getDisplayAuthSources();
      const total = list.length;
      const connected = this.getLoginConnectedCount();
      if (total <= 1 && list[0] === "legacy") {
        return connected ? "已连接" : "未连接";
      }
      if (connected <= 0) return "未连接";
      if (connected >= total) return "全部已连接";
      return "部分已连接";
    },

    getLoginSummaryTextClass() {
      const list = this.getDisplayAuthSources();
      const total = list.length;
      const connected = this.getLoginConnectedCount();
      if (connected <= 0) return "text-rose-600";
      if (connected >= total) return "text-emerald-600";
      return "text-amber-600";
    },

    getLoginSummaryIconClass() {
      const list = this.getDisplayAuthSources();
      const total = list.length;
      const connected = this.getLoginConnectedCount();
      if (connected <= 0) return "bg-rose-100 text-rose-600";
      if (connected >= total) return "bg-emerald-100 text-emerald-600";
      return "bg-amber-100 text-amber-700";
    },

    async checkSystemSetup() {
      try {
        const res = await fetch("/api/admin/check");
        const data = await res.json();
        if (!data.has_token) {
          this.showSetup = true;
        }
      } catch (e) {
        console.error(e);
      }
    },

    async setupAdmin() {
      try {
        const res = await fetch("/api/admin/setup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: this.newAdminToken }),
        });
        const data = await res.json();
        if (data.success) {
          localStorage.setItem("dorm_admin_token", this.newAdminToken);
          this.isAdmin = true;
          this.showSetup = false;
          this.showToast("初始化成功!", "success");
        } else {
          this.showToast(data.message, "error");
        }
      } catch (e) {
        this.showToast("请求失败", "error");
      }
    },

    async loginAdmin() {
      try {
        const res = await fetch("/api/admin/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: this.adminInputToken }),
        });
        const data = await res.json();
        if (data.success) {
          localStorage.setItem("dorm_admin_token", this.adminInputToken);
          this.isAdmin = true;
          this.showAdminLogin = false;
          this.adminInputToken = "";
          this.showToast("登录成功", "success");
        } else {
          this.showToast(data.message, "error");
        }
      } catch (e) {
        this.showToast("登录失败", "error");
      }
    },

    logout() {
      localStorage.removeItem("dorm_admin_token");
      this.isAdmin = false;
      this.showTab = "dashboard";
      this.showToast("已退出管理员模式", "success");
    },

    async tryAutoLogin() {
      const token = localStorage.getItem("dorm_admin_token");
      if (token) {
        try {
          const res = await fetch("/api/admin/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: token }),
          });
          const data = await res.json();
          if (data.success) this.isAdmin = true;
        } catch (e) {
          localStorage.removeItem("dorm_admin_token");
        }
      }
    },

    getAuthHeaders() {
      const headers = { "Content-Type": "application/json" };
      const token = localStorage.getItem("dorm_admin_token");
      if (token) headers["X-Admin-Token"] = token;
      return headers;
    },

    updateTime() {
      const now = new Date();
      this.currentTime = now.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    },

    async loadStatus() {
      try {
        const resp = await fetch("/api/status");
        const data = await resp.json();
        if (data.success) {
          this.status = data;
          const list = this.getDisplayAuthSources();
          if (list.length && !list.includes(this.manualCookie.source)) {
            this.manualCookie.source = list[0];
          }
        }
      } catch (e) {
        console.error(e);
      }
    },

    async loadLoginState() {
      try {
        const resp = await fetch("/api/login-state");
        const data = await resp.json();
        if (data && data.success) this.loginState = data;
      } catch (e) {
        /* ignore */
      }
    },

    async loadConfig() {
      if (!this.isAdmin) return;
      try {
        const resp = await fetch("/api/config", {
          headers: this.getAuthHeaders(),
        });
        if (resp.status === 401) {
          this.logout();
          return;
        }
        const data = await resp.json();
        if (data.success) {
          this.config = data.config;
          this.syncRecipientsFromString();
          this.selectedRecipients = this.recipientsList.length
            ? [this.recipientsList[0]]
            : [];

          // room_recipients -> roomRecipientMap
          this.roomRecipientMap = {};
          const rm = this.config.room_recipients || {};
          if (rm && typeof rm === "object" && !Array.isArray(rm)) {
            for (const [room, rec] of Object.entries(rm)) {
              const roomName = (room || "").toString().trim();
              if (!roomName) continue;

              let arr = [];
              if (Array.isArray(rec)) {
                arr = rec
                  .map((x) => (x || "").toString().trim())
                  .filter(Boolean);
              } else {
                const s = (rec || "").toString().trim();
                arr = s
                  ? s
                      .split(/[;,\n]/)
                      .map((x) => x.trim())
                      .filter(Boolean)
                  : [];
              }
              this.roomRecipientMap[roomName] = arr;
            }
          }

          // source_recipients -> sourceRecipientMap
          this.sourceRecipientMap = {};
          const sm = this.config.source_recipients || {};
          if (sm && typeof sm === "object" && !Array.isArray(sm)) {
            for (const [srcKeyRaw, rec] of Object.entries(sm)) {
              const srcKey = (srcKeyRaw || "").toString().trim();
              if (!srcKey) continue;
              let arr = [];
              if (Array.isArray(rec)) {
                arr = rec
                  .map((x) => (x || "").toString().trim())
                  .filter(Boolean);
              } else {
                const s = (rec || "").toString().trim();
                arr = s
                  ? s
                      .split(/[;,\n]/)
                      .map((x) => x.trim())
                      .filter(Boolean)
                  : [];
              }
              this.sourceRecipientMap[srcKey] = arr;
            }
          }

          // auth_labels -> authLabelsMap
          this.authLabelsMap = {};
          const lm = this.config.auth_labels || {};
          if (lm && typeof lm === "object" && !Array.isArray(lm)) {
            for (const [srcKeyRaw, label] of Object.entries(lm)) {
              const srcKey = (srcKeyRaw || "").toString().trim();
              if (!srcKey) continue;
              const v = (label || "").toString().trim();
              if (v) this.authLabelsMap[srcKey] = v;
            }
          }

          // auth_sources -> authSourcesList
          const as = this.config.auth_sources;
          if (Array.isArray(as)) {
            this.authSourcesList = as
              .map((x) => (x || "").toString().trim())
              .filter(Boolean);
          } else if (typeof as === "string") {
            this.authSourcesList = as
              .split(/[;,\n]/)
              .map((x) => x.trim())
              .filter(Boolean);
          } else {
            this.authSourcesList = [];
          }
          // 不允许手动设置 legacy
          this.authSourcesList = this.authSourcesList.filter(
            (s) => s.toLowerCase() !== "legacy"
          );
        }
      } catch (e) {
        console.error(e);
      }
    },

    async saveConfig() {
      try {
        // 将前端维护的列表同步到字符串配置
        this.config.recipients = this.recipientsList.join(", ");

        // roomRecipientMap -> room_recipients（以本次提交为准）
        const roomMap = {};
        const src = this.roomRecipientMap || {};
        for (const [room, arr] of Object.entries(src)) {
          const roomName = (room || "").toString().trim();
          if (!roomName) continue;
          const list = Array.isArray(arr)
            ? arr.map((x) => (x || "").toString().trim()).filter(Boolean)
            : [];
          if (list.length > 0) roomMap[roomName] = list;
        }
        this.config.room_recipients = roomMap;

        // sourceRecipientMap -> source_recipients（以本次提交为准）
        const sourceMap = {};
        const src2 = this.sourceRecipientMap || {};
        for (const [source, arr] of Object.entries(src2)) {
          const key = (source || "").toString().trim();
          if (!key) continue;
          const list = Array.isArray(arr)
            ? arr.map((x) => (x || "").toString().trim()).filter(Boolean)
            : [];
          if (list.length > 0) sourceMap[key] = list;
        }
        this.config.source_recipients = sourceMap;

        // authLabelsMap -> auth_labels
        const labelsMap = {};
        const src3 = this.authLabelsMap || {};
        for (const [source, label] of Object.entries(src3)) {
          const key = (source || "").toString().trim();
          if (!key) continue;
          const v = (label || "").toString().trim();
          if (v) labelsMap[key] = v;
        }
        this.config.auth_labels = labelsMap;

        // authSourcesList -> auth_sources
        const srcList = Array.isArray(this.authSourcesList)
          ? this.authSourcesList
          : [];
        this.config.auth_sources = srcList
          .map((x) => (x || "").toString().trim())
          .filter(Boolean);

        const resp = await fetch("/api/config", {
          method: "POST",
          headers: this.getAuthHeaders(),
          body: JSON.stringify(this.config),
        });
        const data = await resp.json();
        this.showToast(data.message, data.success ? "success" : "error");
        if (data.success) {
          this.loadStatus();
        }
      } catch (e) {
        this.showToast("保存失败", "error");
      }
    },

    validateSourceName(s) {
      const v = (s || "").toString().trim();
      if (!v) return false;
      if (v.toLowerCase() === "legacy") return false;
      return /^[A-Za-z0-9_-]+$/.test(v);
    },

    addAuthSource() {
      const v = (this.authSourceInput || "").toString().trim();
      if (!this.validateSourceName(v)) {
        this.showToast("source 仅允许 A-Za-z0-9_-（且不能为 legacy）", "error");
        return;
      }
      const exists = (this.authSourcesList || []).some(
        (x) => (x || "").toString().trim().toLowerCase() === v.toLowerCase()
      );
      if (exists) {
        this.showToast("该 source 已存在", "error");
        return;
      }
      this.authSourcesList.push(v);
      this.authSourceInput = "";
    },

    removeAuthSource(idx) {
      if (!Array.isArray(this.authSourcesList)) return;
      if (idx < 0 || idx >= this.authSourcesList.length) return;
      this.authSourcesList.splice(idx, 1);
    },

    availableRooms() {
      const rooms =
        this.status && Array.isArray(this.status.rooms)
          ? this.status.rooms
          : [];
      const set = new Set();
      for (const r of rooms) {
        const name = (r && r.room ? r.room : "").toString().trim();
        if (name) set.add(name);
      }
      return Array.from(set).sort((a, b) => a.localeCompare(b, "zh-CN"));
    },
    unknownMappedRooms() {
      const known = new Set(this.availableRooms());
      const keys = Object.keys(this.roomRecipientMap || {});
      return keys
        .filter((k) => k && !known.has(k))
        .sort((a, b) => a.localeCompare(b, "zh-CN"));
    },

    ensureRoomArray(roomName) {
      const key = (roomName || "").toString().trim();
      if (!key) return [];
      const cur = this.roomRecipientMap[key];
      if (!Array.isArray(cur)) {
        this.roomRecipientMap[key] = [];
      }
      return this.roomRecipientMap[key];
    },
    isRecipientSelected(roomName, mail) {
      const list = this.ensureRoomArray(roomName);
      const m = (mail || "").toString().trim();
      return m ? list.includes(m) : false;
    },
    toggleRoomRecipient(roomName, mail, checked) {
      const list = this.ensureRoomArray(roomName);
      const m = (mail || "").toString().trim();
      if (!m) return;
      if (checked) {
        if (!list.includes(m)) list.push(m);
      } else {
        const idx = list.indexOf(m);
        if (idx >= 0) list.splice(idx, 1);
      }
    },
    getRoomRecipientCount(roomName) {
      const list = this.ensureRoomArray(roomName);
      return Array.isArray(list) ? list.length : 0;
    },

    availableSources() {
      return this.getDisplayAuthSources().filter((s) => s && s !== "legacy");
    },

    ensureSourceArray(source) {
      const key = (source || "").toString().trim();
      if (!key) return [];
      const cur = this.sourceRecipientMap[key];
      if (!Array.isArray(cur)) {
        this.sourceRecipientMap[key] = [];
      }
      return this.sourceRecipientMap[key];
    },

    isSourceRecipientSelected(source, mail) {
      const list = this.ensureSourceArray(source);
      const m = (mail || "").toString().trim();
      return m ? list.includes(m) : false;
    },

    toggleSourceRecipient(source, mail, checked) {
      const list = this.ensureSourceArray(source);
      const m = (mail || "").toString().trim();
      if (!m) return;
      if (checked) {
        if (!list.includes(m)) list.push(m);
      } else {
        const idx = list.indexOf(m);
        if (idx >= 0) list.splice(idx, 1);
      }
    },

    getSourceRecipientCount(source) {
      const list = this.ensureSourceArray(source);
      return Array.isArray(list) ? list.length : 0;
    },

    async toggleMonitoring() {
      try {
        const resp = await fetch("/api/toggle-monitoring", {
          method: "POST",
          headers: this.getAuthHeaders(),
          body: JSON.stringify({ enabled: !this.status.is_monitoring }),
        });
        const data = await resp.json();
        if (data.success) this.loadStatus();
        this.showToast(data.message, data.success ? "success" : "error");
      } catch (e) {
        this.showToast("操作失败", "error");
      }
    },

    openTestEmailModal() {
      if (this.recipientsList.length > 0) {
        this.selectedRecipients = [this.recipientsList[0]];
        this.testEmailMode = "select";
      } else {
        this.testEmailMode = "custom";
      }
      this.customRecipientEmail = "";
      this.showTestEmailModal = true;
    },

    async sendTestEmail() {
      let toList = [];
      if (this.testEmailMode === "select") {
        toList = Array.isArray(this.selectedRecipients)
          ? this.selectedRecipients.map((x) => (x || "").trim()).filter(Boolean)
          : [];
      } else {
        const single = (this.customRecipientEmail || "").trim();
        toList = single ? [single] : [];
      }

      if (toList.length === 0) {
        this.showToast("请选择或输入邮箱地址", "error");
        return;
      }
      for (const mail of toList) {
        if (!this.validateEmail(mail)) {
          this.showToast("请输入有效的邮箱地址", "error");
          return;
        }
      }
      try {
        this.showToast("发送中...", "success");
        const resp = await fetch("/api/test-email", {
          method: "POST",
          headers: this.getAuthHeaders(),
          body: JSON.stringify({ to: toList }),
        });
        const data = await resp.json();
        this.showToast(
          data.message || "已发送",
          data.success ? "success" : "error"
        );
        if (data.success) this.showTestEmailModal = false;
      } catch (e) {
        this.showToast("发送失败", "error");
      }
    },

    // 收件人相关
    syncRecipientsFromString() {
      const str = (this.config.recipients || "").trim();
      this.recipientsList = str
        ? str
            .split(/[;,\n]/)
            .map((s) => s.trim())
            .filter((s) => !!s)
        : [];
    },
    addRecipient() {
      const email = (this.recipientInput || "").trim();
      if (!email) return;
      if (!this.validateEmail(email)) {
        this.showToast("邮箱格式不正确", "error");
        return;
      }
      if (this.recipientsList.includes(email)) {
        this.showToast("该邮箱已在列表中", "error");
        this.recipientInput = "";
        return;
      }
      this.recipientsList.push(email);
      this.recipientInput = "";
    },
    removeRecipient(idx) {
      this.recipientsList.splice(idx, 1);
    },
    validateEmail(email) {
      // 简易校验即可
      const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      return re.test(email);
    },

    async submitManualCookie() {
      // Manual cookie logic... (同原代码，略)
      try {
        const resp = await fetch("/api/manual-cookie", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source: this.manualCookie.source,
            cookie: this.manualCookie.cookie,
            user_agent: this.manualCookie.ua,
          }),
        });
        const data = await resp.json();
        this.showToast(data.message, data.success ? "success" : "error");
        if (data.success) this.closeManualCookie();
      } catch (e) {
        this.showToast("Error", "error");
      }
    },

    showToast(message, type = "success") {
      this.toast = { show: true, message, type };
      setTimeout(() => {
        this.toast.show = false;
      }, 3000);
    },
  };
}
