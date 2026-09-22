# 08-Web ｜ 前端技术要点

> 模块：08 Web 面板 ｜ 成分：前端工程约定 ｜ 对应代码：web/static/ ｜ 实施阶段：P8
> 来源：原方案 §8.3

- Vue 3 全局构建（`vue.global.prod.js`）+ ECharts（`echarts.min.js`）**下载进 `web/static/vendor/` 本地化**——不依赖外网 CDN，断网可用（个人工具最常见坑）。
- 无 Vite/npm 构建链：`app.js` 单文件（数百行）+ `index.html`，FastAPI StaticFiles 托管，`uv run python main.py` 一条命令起全部。
- 信号徽章配色约定：accumulate 红/绿？——按 A 股习惯红涨绿跌容易混淆，**固定语义色**：加仓=绿、观望=灰、减仓=橙红（与行情涨跌色无关，README 注明）。
- 所有日期展示标注"美东时间"。
