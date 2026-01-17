// js/config.js

function configPage() {
    return {
        // --- 基础状态 ---
        currentTime: '',
        isAdmin: false,
        adminInputToken: '',
        newAdminToken: '',
        
        // --- 模态框控制 ---
        showAdminLogin: false,
        showSetup: false,
        showTestEmailModal: false,
        toast: { show: false, message: '', type: 'success' },

        // --- 核心数据 ---
        status: { rooms: [], auth_sources: [] }, // 用于提供选项列表
        config: { 
            auth_sources: [], 
            interval: 1800, 
            threshold: 20, 
            cooldown_seconds: 21600, 
            recipients: '', 
            smtp_server: '', 
            server_ip: '' 
        },

        // --- 映射编辑状态 ---
        recipientsList: [],
        recipientInput: '',
        authSourcesList: [],
        authSourceInput: '',
        
        roomRecipientMap: {},   // 房间 -> 收件人列表
        sourceRecipientMap: {}, // Source -> 收件人列表
        authLabelsMap: {},      // Source -> 显示名称

        // --- 测试邮件状态 ---
        testEmailMode: 'select', // select | custom
        selectedRecipients: [],
        customRecipientEmail: '',

        init() {
            this.updateTime();
            setInterval(() => this.updateTime(), 1000);
            
            this.checkSystemSetup();
            this.tryAutoLogin();
            // 即使未登录也加载 status 以获取 rooms 用于显示(如果后端允许)
            this.loadStatus(); 
        },

        // --- 核心业务逻辑 ---

        async loadConfig() {
            if (!this.isAdmin) return;
            try {
                const resp = await fetch('/api/config', { headers: this.getAuthHeaders() });
                if (resp.status === 401) {
                    this.logout();
                    return;
                }
                const data = await resp.json();
                if (data.success) {
                    this.config = data.config;
                    
                    // 1. 还原收件人列表
                    this.syncRecipientsFromString();
                    
                    // 2. 还原 Auth Sources
                    this.authSourcesList = this.normalizeList(this.config.auth_sources);
                    this.authSourcesList = this.authSourcesList.filter(s => s && s.toLowerCase() !== 'legacy');

                    // 3. 还原各种映射 (确保格式正确)
                    this.roomRecipientMap = this.normalizeMapList(this.config.room_recipients);
                    this.sourceRecipientMap = this.normalizeMapList(this.config.source_recipients);
                    this.authLabelsMap = { ...(this.config.auth_labels || {}) };

                    // 初始化测试邮件选中项
                    if (this.recipientsList.length > 0) {
                        this.selectedRecipients = [this.recipientsList[0]];
                    }
                }
            } catch (e) { 
                console.error("Config load error:", e);
                this.showToast('配置加载失败', 'error'); 
            }
        },

        async saveConfig() {
            try {
                // 1. 序列化收件人
                this.config.recipients = this.recipientsList.join(', ');
                
                // 2. 序列化 Auth Sources
                this.config.auth_sources = this.authSourcesList;

                // 3. 序列化映射 (过滤空值)
                this.config.room_recipients = this.cleanMap(this.roomRecipientMap);
                this.config.source_recipients = this.cleanMap(this.sourceRecipientMap);
                this.config.auth_labels = this.authLabelsMap;

                const resp = await fetch('/api/config', {
                    method: 'POST',
                    headers: this.getAuthHeaders(),
                    body: JSON.stringify(this.config)
                });
                const data = await resp.json();
                this.showToast(data.message, data.success ? 'success' : 'error');
                
                if (data.success) {
                    this.loadStatus(); // 刷新状态以更新可用列表
                }
            } catch (e) { 
                this.showToast('保存失败', 'error'); 
            }
        },

        async loadStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                if (data.success) {
                    this.status = data;
                }
            } catch (e) { console.error(e); }
        },

        // --- 列表/映射 操作逻辑 ---

        syncRecipientsFromString() {
            const str = (this.config.recipients || '').toString();
            this.recipientsList = str ? str.split(/[;,\n]/).map(s => s.trim()).filter(Boolean) : [];
        },

        addRecipient() {
            const email = this.recipientInput.trim();
            if (!email) return;
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return this.showToast('邮箱格式错误', 'error');
            if (this.recipientsList.includes(email)) return this.showToast('邮箱已存在', 'error');
            
            this.recipientsList.push(email);
            this.recipientInput = '';
        },

        removeRecipient(idx) {
            this.recipientsList.splice(idx, 1);
        },

        addAuthSource() {
            const v = this.authSourceInput.trim();
            if (!v) return;
            if (v.toLowerCase() === 'legacy') return this.showToast('legacy 为保留关键词', 'error');
            if (!/^[A-Za-z0-9_-]+$/.test(v)) return this.showToast('Source 仅允许字母、数字、下划线', 'error');
            if (this.authSourcesList.includes(v)) return this.showToast('已存在', 'error');
            
            this.authSourcesList.push(v);
            this.authSourceInput = '';
        },

        removeAuthSource(idx) {
            this.authSourcesList.splice(idx, 1);
        },

        // --- 映射辅助 ---

        availableRooms() {
            const rooms = (this.status && Array.isArray(this.status.rooms)) ? this.status.rooms : [];
            return [...new Set(rooms.map(r => r.room))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
        },

        unknownMappedRooms() {
            const known = new Set(this.availableRooms());
            return Object.keys(this.roomRecipientMap).filter(k => !known.has(k));
        },

        availableSources() {
            return this.authSourcesList; // 直接使用配置中的列表
        },

        // 通用映射切换
        toggleMapItem(mapObj, key, val, checked) {
            if (!mapObj[key]) mapObj[key] = [];
            if (!Array.isArray(mapObj[key])) mapObj[key] = [];
            
            if (checked) {
                if (!mapObj[key].includes(val)) mapObj[key].push(val);
            } else {
                mapObj[key] = mapObj[key].filter(x => x !== val);
            }
        },

        // 房间映射
        isRecipientSelected(room, mail) { return (this.roomRecipientMap[room] || []).includes(mail); },
        toggleRoomRecipient(room, mail, checked) { this.toggleMapItem(this.roomRecipientMap, room, mail, checked); },
        getRoomRecipientCount(room) { return (this.roomRecipientMap[room] || []).length; },

        // Source映射
        isSourceRecipientSelected(src, mail) { return (this.sourceRecipientMap[src] || []).includes(mail); },
        toggleSourceRecipient(src, mail, checked) { this.toggleMapItem(this.sourceRecipientMap, src, mail, checked); },
        getSourceRecipientCount(src) { return (this.sourceRecipientMap[src] || []).length; },


        // --- 测试邮件逻辑 ---

        openTestEmailModal() {
            // 初始化选中状态：如果有列表，默认选中第一个；否则切到自定义模式
            if (this.recipientsList.length > 0) {
                this.testEmailMode = 'select';
                if (this.selectedRecipients.length === 0) {
                    this.selectedRecipients = [this.recipientsList[0]];
                }
            } else {
                this.testEmailMode = 'custom';
            }
            this.showTestEmailModal = true;
        },

        async sendTestEmail() {
            let toList = [];
            if (this.testEmailMode === 'select') {
                toList = this.selectedRecipients;
            } else {
                if (this.customRecipientEmail) toList = [this.customRecipientEmail];
            }

            if (toList.length === 0) return this.showToast('请提供有效收件人', 'error');

            try {
                this.showToast('发送中...', 'success');
                const resp = await fetch('/api/test-email', {
                    method: 'POST',
                    headers: this.getAuthHeaders(),
                    body: JSON.stringify({ to: toList })
                });
                const data = await resp.json();
                this.showToast(data.message || '发送完毕', data.success ? 'success' : 'error');
                if (data.success) this.showTestEmailModal = false;
            } catch (e) { this.showToast('发送请求失败', 'error'); }
        },

        // --- Admin & Setup ---

        async checkSystemSetup() {
            try {
                const res = await fetch('/api/admin/check');
                const data = await res.json();
                if (!data.has_token) this.showSetup = true;
            } catch (e) {}
        },

        async setupAdmin() {
            try {
                const res = await fetch('/api/admin/setup', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: this.newAdminToken })
                });
                const data = await res.json();
                if (data.success) {
                    localStorage.setItem('dorm_admin_token', this.newAdminToken);
                    this.isAdmin = true;
                    this.showSetup = false;
                    this.loadConfig();
                    this.showToast('初始化成功!', 'success');
                } else {
                    this.showToast(data.message, 'error');
                }
            } catch (e) { this.showToast('网络请求失败', 'error'); }
        },

        async loginAdmin() {
            try {
                const res = await fetch('/api/admin/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token: this.adminInputToken })
                });
                const data = await res.json();
                if (data.success) {
                    localStorage.setItem('dorm_admin_token', this.adminInputToken);
                    this.isAdmin = true;
                    this.showAdminLogin = false;
                    this.adminInputToken = '';
                    this.loadConfig(); // 登录成功立即加载配置
                    this.showToast('登录成功', 'success');
                } else {
                    this.showToast(data.message, 'error');
                }
            } catch (e) { this.showToast('登录失败', 'error'); }
        },

        async tryAutoLogin() {
            const token = localStorage.getItem('dorm_admin_token');
            if (token) {
                try {
                    const res = await fetch('/api/admin/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ token: token })
                    });
                    const data = await res.json();
                    if (data.success) {
                        this.isAdmin = true;
                        this.loadConfig(); // 自动登录成功也加载配置
                    } else {
                        localStorage.removeItem('dorm_admin_token');
                    }
                } catch (e) {}
            }
        },

        logout() {
            localStorage.removeItem('dorm_admin_token');
            this.isAdmin = false;
            window.location.href = '/'; // 退出后跳回仪表盘
        },

        // --- 工具函数 ---

        getAuthHeaders() {
            const headers = { 'Content-Type': 'application/json' };
            const token = localStorage.getItem('dorm_admin_token');
            if (token) headers['X-Admin-Token'] = token;
            return headers;
        },

        updateTime() {
            this.currentTime = new Date().toLocaleString('zh-CN', {
                month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
            });
        },

        showToast(message, type = 'success') {
            this.toast = { show: true, message, type };
            setTimeout(() => { this.toast.show = false; }, 3000);
        },

        // 数据清洗：将后端可能传来的字符串/数组统一转为数组
        normalizeList(val) {
            if (Array.isArray(val)) return val;
            if (typeof val === 'string') return val.split(/[;,\n]/).map(s => s.trim()).filter(Boolean);
            return [];
        },

        // 数据清洗：将 Map<Key, String|Array> 统一为 Map<Key, Array>
        normalizeMapList(mapObj) {
            const res = {};
            if (!mapObj || typeof mapObj !== 'object') return res;
            for (const [k, v] of Object.entries(mapObj)) {
                res[k] = this.normalizeList(v);
            }
            return res;
        },
        
        // 保存前清洗：移除空数组
        cleanMap(mapObj) {
            const res = {};
            for (const [k, v] of Object.entries(mapObj)) {
                if (v && v.length > 0) res[k] = v;
            }
            return res;
        }
    }
}