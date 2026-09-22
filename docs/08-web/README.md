# 08 ｜ Web 面板（web/）

> **职责**：REST API 六个路由组（dashboard / stocks / events / analysis / config / chat，另有 /api/health）、前端六个页签、本地 vendor 化的前端技术要点——系统的展示、对话与人工触发入口。
> **对应代码**：web/（app.py / deps.py / api/ / static/） ｜ **依赖模块**：全部 ｜ **实施阶段**：P8（对话页签为实施期增补）
> **内容来源**：原方案 §8

## 成分文档

| 文档 | 内容 | 对应代码 | 来源 |
|---|---|---|---|
| [api.md](api.md) | REST API 清单（15 个端点）与全局锁约定 | web/api/ | 原方案 §8.1 |
| [pages.md](pages.md) | 前端六个页签的内容定义 | web/static/ | 原方案 §8.2 |
| [frontend.md](frontend.md) | 前端技术要点（vendor 本地化/无构建链/配色约定） | web/static/ | 原方案 §8.3 |
