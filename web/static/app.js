/* ai-ticker-copilot 前端（Vue3 全局构建 + ECharts，本地 vendor 无构建链）
   约定（docs/08-web）：信号固定语义色（加仓绿/观望灰/减仓橙红）；日期标注美东。 */
const { createApp, ref, reactive, onMounted } = Vue;

const api = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    return r.json();
  },
  async send(url, method, body) {
    const r = await fetch(url, {
      method, headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.status);
    return data;
  },
};

const app = createApp({
  setup() {
    const tabs = [
      { key: "overview", label: "总览" },
      { key: "stock", label: "个股详情" },
      { key: "events", label: "事件中心" },
      { key: "x", label: "X 观点" },
      { key: "analysis", label: "分析" },
      { key: "chat", label: "对话" },
    ];
    const tab = ref("overview");
    const mockMode = ref(false);
    const unread = ref(0);
    const dash = reactive({ empty: false, message: "", cards: [] });
    const regime = ref(null);
    const sources = reactive({});
    const detailSymbol = ref("");
    const detailWindow = ref("6M");
    const detail = ref(null);
    const scopeFilter = ref("");
    const events = ref([]);
    const eventsMessage = ref("加载中…");
    const lib = ref([]);
    const calendar = ref([]);
    const calendarNote = ref("");
    const influencers = ref([]);
    const running = ref(false);
    const runError = ref("");
    const result = ref(null);
    const historyMessage = ref("（DB 配置后显示历史运行记录）");
    const chatMessages = ref([]);
    const chatInput = ref("");
    const chatBusy = ref(false);
    const chatError = ref("");
    let lastSeen = new Date().toISOString().slice(0, 10);
    let klineChart = null;

    const scopes = [
      { key: "", label: "全部" },
      { key: "macro_policy", label: "宏观政策" },
      { key: "geopolitical", label: "国际热点" },
      { key: "industry", label: "行业" },
      { key: "company", label: "企业" },
    ];

    const signalLabel = (s) => ({
      accumulate: "建仓/加仓", watch_add: "观望偏加", watch: "观望", reduce: "减仓/回避",
    }[s] || s);
    const scopeLabel = (s) => ({
      macro_policy: "宏观政策", geopolitical: "国际热点", industry: "行业", company: "企业",
    }[s] || s);
    const indicatorLabel = (k) => ({
      close: "收盘", ma20: "MA20", ma50: "MA50", ma200: "MA200", rsi14: "RSI14",
      atr14_pct: "ATR14%", volume_ratio: "量比", drawdown_52w: "距52周高回撤%",
      bias_ma200: "乖离MA200%",
    }[k] || k);
    const fmt = (v) => (typeof v === "number" ? v.toFixed(2) : (v ?? "-"));

    async function loadDashboard(refresh = false) {
      try {
        const data = await api.get(`/api/dashboard${refresh ? "?refresh=1" : ""}`);
        Object.assign(dash, data);
        regime.value = data.regime && !data.regime.error ? data.regime : data.regime;
        Object.assign(sources, data.sources || {});
        if (!detailSymbol.value && data.cards.length) detailSymbol.value = data.cards[0].symbol;
      } catch (e) { dash.empty = true; dash.message = "加载失败：" + e.message; }
    }

    async function loadDetail() {
      if (!detailSymbol.value) return;
      try {
        detail.value = await api.get(
          `/api/stocks/${detailSymbol.value}?window=${detailWindow.value}`);
        renderKline();
      } catch (e) { alert("详情加载失败：" + e.message); }
    }

    function renderKline() {
      const el = document.getElementById("kline");
      if (!el || !detail.value) return;
      klineChart = klineChart || echarts.init(el);
      const bars = detail.value.bars;
      const ma = (n) => bars.map((b, i) =>
        i >= n - 1 ? +(bars.slice(i - n + 1, i + 1).reduce((s, x) => s + x.close, 0) / n).toFixed(2) : null);
      klineChart.setOption({
        tooltip: { trigger: "axis" },
        legend: { data: ["K线", "MA20", "MA50"] },
        grid: { left: 60, right: 20, top: 30, bottom: 40 },
        xAxis: { type: "category", data: bars.map(b => b.date) },
        yAxis: { scale: true },
        dataZoom: [{ type: "inside" }],
        series: [
          { name: "K线", type: "candlestick",
            data: bars.map(b => [b.open, b.close, b.low, b.high]),
            itemStyle: { color: "#c62828", color0: "#2e7d32", borderColor: "#c62828", borderColor0: "#2e7d32" } },
          { name: "MA20", type: "line", data: ma(20), showSymbol: false, lineStyle: { width: 1 } },
          { name: "MA50", type: "line", data: ma(50), showSymbol: false, lineStyle: { width: 1 } },
        ],
      }, true);
    }

    async function loadEvents() {
      try {
        const data = await api.get(`/api/events?scope=${scopeFilter.value}&limit=100`);
        events.value = data.events;
        eventsMessage.value = data.db_ok
          ? (data.events.length ? "" : "暂无事件（等待管道轮询）")
          : `当前事件读取失败：${data.message}`;
      } catch (e) { eventsMessage.value = "加载失败：" + e.message; }
    }

    async function loadLib() {
      try { lib.value = (await api.get("/api/events/lib")).events; } catch (e) { lib.value = []; }
    }

    async function loadCalendar() {
      try {
        const data = await api.get("/api/calendar");
        calendar.value = data.upcoming;
        calendarNote.value = data.note;
      } catch (e) { calendar.value = []; }
    }

    async function loadConfig() {
      try {
        const data = await api.get("/api/config");
        influencers.value = data.influencers;
        Object.assign(sources, data.sources || {});
      } catch (e) { /* 忽略 */ }
    }

    async function runAnalysis(refresh) {
      running.value = true; runError.value = ""; result.value = null;
      try {
        result.value = await api.send("/api/analysis/run", "POST", { refresh });
      } catch (e) {
        runError.value = e.message.includes("已有分析") ? e.message : "分析失败：" + e.message;
      } finally { running.value = false; }
    }

    async function pollEvents() {
      try {
        const data = await api.get(`/api/events/poll?since=${lastSeen}`);
        if (data.count > 0) {
          unread.value += data.count;
          lastSeen = new Date().toISOString().slice(0, 10);
        }
      } catch (e) { /* 静默 */ }
    }

    function switchTab(key) {
      tab.value = key;
      if (key === "events") { unread.value = 0; loadEvents(); loadLib(); loadCalendar(); }
      if (key === "stock") setTimeout(loadDetail, 50);
      if (key === "x") loadConfig();
      if (key === "analysis") {
        api.get("/api/analysis/history").then(h => {
          if (h.runs && h.runs.length) {
            historyMessage.value = h.runs.map(r => `#${r.run_id} ${r.created_at}`).join("　");
          } else if (h.message) historyMessage.value = "历史读取失败（DB）：" + h.message;
        }).catch(() => {});
      }
    }

    async function sendChat() {
      const text = chatInput.value.trim();
      if (!text || chatBusy.value) return;
      chatError.value = "";
      chatMessages.value.push({ role: "user", content: text });
      chatInput.value = "";
      chatBusy.value = true;
      scrollChat();
      try {
        const data = await api.send("/api/chat", "POST",
          { messages: chatMessages.value.map(m => ({ role: m.role, content: m.content })) });
        chatMessages.value.push({ role: "assistant", content: data.reply });
      } catch (e) {
        chatError.value = e.message;
        if (e.message.includes("LLM")) {
          chatError.value += "（对话是唯一强依赖 LLM 的功能，评分/分析不受影响）";
        }
      } finally {
        chatBusy.value = false;
        scrollChat();
      }
    }

    function scrollChat() {
      setTimeout(() => {
        const box = document.getElementById("chatBox");
        if (box) box.scrollTop = box.scrollHeight;
      }, 30);
    }

    function openStock(symbol) { detailSymbol.value = symbol; switchTab("stock"); }

    onMounted(async () => {
      try { mockMode.value = (await api.get("/api/health")).mock_mode; } catch (e) {}
      await loadDashboard();
      loadEvents(); loadLib(); loadCalendar(); loadConfig();
      setInterval(pollEvents, 30000);  // 事件中心 30s 增量轮询（docs/08-web/api.md）
    });

    return {
      tabs, tab, mockMode, unread, dash, regime, sources,
      detailSymbol, detailWindow, detail, scopes, scopeFilter,
      events, eventsMessage, lib, calendar, calendarNote, influencers,
      running, runError, result, historyMessage,
      chatMessages, chatInput, chatBusy, chatError, sendChat,
      signalLabel, scopeLabel, indicatorLabel, fmt,
      switchTab, openStock, loadDashboard, loadDetail, loadEvents, runAnalysis,
    };
  },
});
app.mount("#app");
