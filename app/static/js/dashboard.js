// 【关键修改1】将图表实例定义在 dashboard 函数外部
// 这样 Alpine.js 就不会去“监听”它的内部变化，避免了鼠标移动时的冲突
let trendChartInstance = null;

function dashboard() {
  return {
    showPowerTrend: false,
    powerTrendRoom: "",
    powerTrendRoomLabel: "",
    powerTrendData: [],

    openPowerTrend(roomName, evt) {
      this.powerTrendRoom = roomName;
      this.powerTrendRoomLabel = this.getRoomLabel(roomName);
      this.powerTrendData = [];
      this.showPowerTrend = true;

      // 使用 setTimeout 确保 DOM 完全渲染后再初始化图表
      setTimeout(() => {
        const el = document.getElementById("power-trend-chart");
        if (!el) return;

        // 【关键修改2】使用外部变量 trendChartInstance
        if (!trendChartInstance || trendChartInstance.isDisposed()) {
          trendChartInstance = echarts.init(el);
        }
        
        // 响应窗口大小变化
        window.addEventListener('resize', () => {
            if(trendChartInstance) trendChartInstance.resize();
        });

        this.fetchPowerTrend(roomName);
      }, 100);
    },

    closePowerTrend() {
      this.showPowerTrend = false;
      this.powerTrendRoom = "";
      this.powerTrendData = [];
      // 关闭时不销毁实例，只隐藏模态框，下次打开更快
      if (trendChartInstance) {
          trendChartInstance.clear(); // 清空当前数据，避免下个房间显示旧数据瞬间
      }
    },

    getRoomLabel(roomName) {
      if (!roomName) return "";
      const room = (this.status.rooms || []).find((r) => r.room === roomName);
      return room && room.room_label ? room.room_label : roomName;
    },

    async fetchPowerTrend(roomName) {
      try {
        // 显示加载动画
        if (trendChartInstance) trendChartInstance.showLoading();
        
        const resp = await fetch(
          `/api/room_power_trend?room=${encodeURIComponent(roomName)}`
        );
        const data = await resp.json();
        
        if (trendChartInstance) trendChartInstance.hideLoading();

        if (data && data.trend) {
          this.powerTrendData = data.trend;
          this.renderPowerTrendChart();
        }
      } catch (e) {
        if (trendChartInstance) trendChartInstance.hideLoading();
        this.powerTrendData = [];
      }
    },

    renderPowerTrendChart() {
      // 【关键修改3】使用外部变量
      if (!trendChartInstance) return;
      
      const days = this.powerTrendData.map((d) => d.date);
      const values = this.powerTrendData.map((d) => d.consume_power);
      
      trendChartInstance.setOption({
        tooltip: { 
            trigger: "axis",
            // 确保 tooltip 不会被遮挡
            confine: true 
        },
        xAxis: { type: "category", data: days },
        yAxis: { type: "value", name: "耗电(度)" },
        series: [
          {
            data: values,
            type: "line",
            smooth: true,
            areaStyle: { color: "#93c5fd", opacity: 0.2 },
            lineStyle: { color: "#2563eb", width: 3 },
            symbol: "circle",
            symbolSize: 8,
          },
        ],
        grid: { left: 40, right: 20, top: 40, bottom: 40 },
      });
      trendChartInstance.resize();
    },

    // --- 以下代码保持原样 ---
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
    config: {
      auth_sources: [],
      interval: 1800,
      threshold: 20,
      cooldown_seconds: 21600,
      recipients: "user@example.com, admin@test.com",
      smtp_server: "",
      server_ip: "192.168.3.10",
    },
    roomRecipientMap: {},
    sourceRecipientMap: {},
    authLabelsMap: {},
    authSourcesList: [],
    authSourceInput: "",
    recipientsList: [],
    recipientInput: "",
    selectedRecipients: [],
    customRecipientEmail: "",
    testEmailMode: "select",
    manualCookie: { source: "ac_a", cookie: "", ua: "" },
    manualCookieSourceLocked: false,
    toast: { show: false, message: "", type: "success" },
    showAllAuthSources: false,
    maxAuthSourcesCollapsed: 6,

    init() {
      this.updateTime();
      setInterval(() => this.updateTime(), 1000);
      this.checkSystemSetup();
      this.tryAutoLogin();
      this.loadStatus();
      // 5秒轮询一次状态
      setInterval(() => this.loadStatus(), 5000);
      this.loadLoginState();
      setInterval(() => this.loadLoginState(), 3000);
      this.syncRecipientsFromString();
      if (this.recipientsList.length > 0) {
        this.selectedRecipients = [this.recipientsList[0]];
      }
    },

    getDisplayAuthSources() {
      const sources = Array.isArray(this.status.auth_sources)
        ? this.status.auth_sources
        : [];
      if (sources.includes("legacy")) return ["legacy"];
      const cleaned = sources.filter((s) => s && s !== "legacy");
      if (cleaned.length) return cleaned;
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
      const per =
        this.status &&
        this.status.source_status &&
        this.status.source_status[key]
          ? this.status.source_status[key]
          : null;
      if (per) {
        return !!per.has_cookie && !per.last_error && !!per.last_ok_time;
      }
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
            // 优化：不要整个替换 status，而是只更新需要的字段
            // 这可以减少房间列表（卡片）的 DOM 抖动
            this.status.is_monitoring = data.is_monitoring;
            this.status.has_cookie = data.has_cookie;
            this.status.last_check_time = data.last_check_time;
            this.status.next_check_in = data.next_check_in;
            this.status.last_error = data.last_error;
            
            // 房间数据深度比较/替换（如果需要更细致的防抖动，可以在这里做）
            this.status.rooms = data.rooms;
            
            // 其他配置
            this.status.auth_sources = data.auth_sources;
            this.status.auth_labels = data.auth_labels;
            this.status.auth_configured = data.auth_configured;
            this.status.source_status = data.source_status;
            this.status.interval = data.interval;

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
          
          // 重新处理 config 映射，保持原逻辑
          this.roomRecipientMap = {};
          const rm = this.config.room_recipients || {};
          if (rm && typeof rm === "object" && !Array.isArray(rm)) {
            for (const [room, rec] of Object.entries(rm)) {
                const roomName = (room || "").toString().trim();
                if (!roomName) continue;
                let arr = Array.isArray(rec) ? rec : (rec || "").toString().split(/[;,\n]/);
                this.roomRecipientMap[roomName] = arr.map(x=>x.trim()).filter(Boolean);
            }
          }

          this.sourceRecipientMap = {};
          const sm = this.config.source_recipients || {};
          if (sm && typeof sm === "object" && !Array.isArray(sm)) {
            for (const [srcKeyRaw, rec] of Object.entries(sm)) {
              const srcKey = (srcKeyRaw || "").toString().trim();
              if (!srcKey) continue;
              let arr = Array.isArray(rec) ? rec : (rec || "").toString().split(/[;,\n]/);
              this.sourceRecipientMap[srcKey] = arr.map(x=>x.trim()).filter(Boolean);
            }
          }

          this.authLabelsMap = {};
          const lm = this.config.auth_labels || {};
          for (const [k, v] of Object.entries(lm)) {
             if(k && v) this.authLabelsMap[k] = v;
          }

          const as = this.config.auth_sources;
          if (Array.isArray(as)) {
            this.authSourcesList = as.map((x) => (x || "").toString().trim()).filter(Boolean);
          } else if (typeof as === "string") {
            this.authSourcesList = as.split(/[;,\n]/).map((x) => x.trim()).filter(Boolean);
          } else {
            this.authSourcesList = [];
          }
          this.authSourcesList = this.authSourcesList.filter((s) => s.toLowerCase() !== "legacy");
        }
      } catch (e) {
        console.error(e);
      }
    },

    async saveConfig() {
      try {
        this.config.recipients = this.recipientsList.join(", ");
        // ... 原有保存逻辑 ...
        const roomMap = {};
        for (const [room, arr] of Object.entries(this.roomRecipientMap || {})) {
            if(arr && arr.length) roomMap[room] = arr;
        }
        this.config.room_recipients = roomMap;

        const sourceMap = {};
        for (const [src, arr] of Object.entries(this.sourceRecipientMap || {})) {
            if(arr && arr.length) sourceMap[src] = arr;
        }
        this.config.source_recipients = sourceMap;
        
        const labelsMap = {};
        for (const [k, v] of Object.entries(this.authLabelsMap || {})) {
            if(v) labelsMap[k] = v;
        }
        this.config.auth_labels = labelsMap;

        this.config.auth_sources = this.authSourcesList;

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

    // ... 原有的辅助函数 ...
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
      if ((this.authSourcesList || []).some(x => x.toLowerCase() === v.toLowerCase())) {
        this.showToast("该 source 已存在", "error");
        return;
      }
      this.authSourcesList.push(v);
      this.authSourceInput = "";
    },
    removeAuthSource(idx) {
      this.authSourcesList.splice(idx, 1);
    },
    availableRooms() {
      const rooms = Array.isArray(this.status.rooms) ? this.status.rooms : [];
      const set = new Set(rooms.map(r=>r.room).filter(Boolean));
      return Array.from(set).sort((a, b) => a.localeCompare(b, "zh-CN"));
    },
    unknownMappedRooms() {
      const known = new Set(this.availableRooms());
      return Object.keys(this.roomRecipientMap).filter(k=>!known.has(k)).sort();
    },
    ensureRoomArray(roomName) {
      if(!this.roomRecipientMap[roomName]) this.roomRecipientMap[roomName] = [];
      return this.roomRecipientMap[roomName];
    },
    isRecipientSelected(roomName, mail) {
        return this.ensureRoomArray(roomName).includes(mail);
    },
    toggleRoomRecipient(roomName, mail, checked) {
        const list = this.ensureRoomArray(roomName);
        if(checked) { if(!list.includes(mail)) list.push(mail); }
        else { const idx = list.indexOf(mail); if(idx>=0) list.splice(idx,1); }
    },
    getRoomRecipientCount(roomName) { return this.ensureRoomArray(roomName).length; },
    
    availableSources() {
      return this.getDisplayAuthSources().filter(s=>s!=='legacy');
    },
    ensureSourceArray(src) {
        if(!this.sourceRecipientMap[src]) this.sourceRecipientMap[src] = [];
        return this.sourceRecipientMap[src];
    },
    isSourceRecipientSelected(src, mail) { return this.ensureSourceArray(src).includes(mail); },
    toggleSourceRecipient(src, mail, checked) {
        const list = this.ensureSourceArray(src);
        if(checked) { if(!list.includes(mail)) list.push(mail); }
        else { const idx = list.indexOf(mail); if(idx>=0) list.splice(idx,1); }
    },
    getSourceRecipientCount(src) { return this.ensureSourceArray(src).length; },

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

    syncRecipientsFromString() {
      const str = (this.config.recipients || "").trim();
      this.recipientsList = str ? str.split(/[;,\n]/).map(s=>s.trim()).filter(Boolean) : [];
    },
    addRecipient() {
      const email = (this.recipientInput || "").trim();
      if (!email || !this.validateEmail(email)) {
        this.showToast("邮箱格式不正确", "error");
        return;
      }
      if (this.recipientsList.includes(email)) return;
      this.recipientsList.push(email);
      this.recipientInput = "";
    },
    removeRecipient(idx) {
      this.recipientsList.splice(idx, 1);
    },
    validateEmail(email) {
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    },

    async submitManualCookie() {
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