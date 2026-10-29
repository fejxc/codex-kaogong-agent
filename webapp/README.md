# 网页客户端（webapp/）

公考备考台的纯静态网页版：不依赖 ZCode / Codex，在任何浏览器里使用，讲解由你自己的 **OpenAI 兼容端点**（DeepSeek / 智谱 / Ollama / LM Studio / vLLM 等）生成。

## 功能

- **学习对话**：四个模式（自由 / 行测讲题 / 行测复盘 / 申论·综应·公基），系统提示词按原 Skill 协议提炼；行测模式会自动检索已导入的方法卡注入上下文；回复按 **Markdown 渲染**（标题/表格/列表/代码块，本地打包 marked v15 MIT，含轻量消毒），思考型模型的思考过程灰字显示。
- **考我**：从导入的题库按考点抽样，**判分在本地**（对照库内官方答案，不花 token），讲解可选调用模型生成。
- **历史对话**：自动持久化到浏览器 IndexedDB（每轮对话结束即存），侧栏可回看任意旧对话（Markdown 版式还原）、一键新对话、删除单条；刷新或重开浏览器后自动恢复最近一次对话。与错题记录一样只存本机，无导出键时可整段复制。
- **错题记录**：`event_id` 幂等（SHA-256 短键），存浏览器 IndexedDB，可导出 JSON 手动合并回本机 `data/复盘引擎/`。
- **数据边界**：方法库、题库、错题、API Key 全部只存本浏览器；没有任何后端，部署产物不含任何版权题库与个人数据。

## 本地运行（推荐：一键载入题库与方法库）

```bash
python3 webapp/serve.py        # 默认 8901 端口，可加参数改端口
```

打开 <http://127.0.0.1:8901>，在「设置 → 载入资料」点**一键载入题库 / 一键载入方法库**：运行器会把 `data/复盘引擎/题库/exam-research-pool.jsonl`（20,921 题）和 Skill 方法库（1,253 张卡）只读挂载给页面，约几秒完成，题库含图片的题在出题时自动过滤。

> serve.py 只监听 127.0.0.1、只做静态文件和两个只读挂载，无任何业务逻辑；不启动它时页面仍可用「手动文件导入」，或退回 `python3 -m http.server -d webapp 8000`（无一键载入）。

## 部署到 GitHub Pages（免费）

仓库是私有的，而免费版 Pages 要求公开仓库，所以走"**新建一个公开的纯客户端仓库**"：

1. 在 GitHub 新建公开仓库（如 `kaogong-web`）。
2. 只把 `webapp/` 下的三个文件（index.html / app.js / style.css）+ 本 README 复制进去推送。
3. 仓库 Settings → Pages → Source 选 `main` 根目录。
4. 打开 `https://<用户名>.github.io/kaogong-web/`，在「设置」里填端点。

> 这三个文件是纯自研客户端代码，不含题库、方法库和个人数据——版权内容全部通过"设置页导入"进你自己浏览器的 IndexedDB，永不进入公开仓库。
> 若你有 GitHub Pro，也可以直接把本私有仓库的 `webapp/` 用 Actions 部署为私有 Pages。

## 端点与 CORS

| 端点 | Base URL | 备注 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | 浏览器直连可用 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | 浏览器直连可用 |
| Ollama | `http://localhost:11434/v1` | 启动前设 `OLLAMA_ORIGINS=*` |
| LM Studio | `http://localhost:1234/v1` | 默认允许本地跨域 |
| 自建 vLLM 等 | `http://你的服务/v1` | 浏览器直连常被 CORS 拦（Failed to fetch）→ 勾选**「本地代理」**，经 serve.py 同源转发即可，无需改服务器；服务器侧也可加 `--allowed-origins '["*"]'` 根治 |

- 模型名注意**大小写**要和 `/v1/models` 返回的 id 完全一致（如 `qwen3.8-27b-fp8`）。
- 思考型模型（Qwen3/GLM 思考版等）会先流式输出思考过程（灰字显示），正文随后；自建集群首字可能要一两分钟，属排队，不是页面卡死。
- API Key 存在 localStorage，仅个人浏览器使用；公共电脑不要保存 Key。

## 与本机 data/ 的关系

- 导出按钮生成 `webapp-records-YYYY-MM-DD.json`，字段与 `data/复盘引擎/` 错题结构对齐，可手动归档。
- 网页端与本机 ZCode 端是**两个独立记录源**，统计时同样不能互相相加。
