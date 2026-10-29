# Codex 公考智能备考 Agent

个人备考工作区：两个项目内 Skills 承担讲解与复盘，本地 Markdown/JSON 保存知识、错题与复习状态，私有 GitHub 仓库做全量备份。粉笔是学习主线；未导入粉笔讲义前，基础考点均标"暂定"。

## 常用口令（日常使用）

| 场景 | 说法示例 |
|---|---|
| 行测讲题 | "行测解答这道题" / 贴题后按 Skill 提示选择①存档②解法③复盘 |
| 行测复盘 | "我选 C，正确答案是 A，当时思路是……帮我复盘" |
| 变式训练 | "举一反三" / "考我 5 道类比推理"（真题优先，来自题库） |
| 错题复测 | "错题复测" / "复习我的两期比重错题" |
| 学情总结 | "学情报告" / "按本地记录写周报"（无记录时如实报暂无） |
| 导入题目 | "把这道题收进题库"（走题库导入协议，只存档不讲解） |
| 记套题成绩 | "今天做了浙江职测模考，资料分析错 3/20"（走日报写入器） |
| 切目标考试 | "目标考试切为 2027 江西省考"（未见公告不猜类别） |

路由、答案核验与写回门禁的权威规则见 [AGENTS.md](AGENTS.md)。

## 架构总览

```text
AGENTS.md（路由宪法：Skill 选择、答案权威、写回门禁、隐私边界）
├── .agents/skills/xingce-review-pro/   行测：讲解/复盘/错因卡/弱点档案/幂等写回（GPL-3.0-only）
│   ├── references/method-libraries/    方法卡 + 综合方法库（讲解的方法依据）
│   └── scripts/writeback.py            唯一结构化写回入口（--cwd data/）
├── .agents/skills/kaogong/             申论/综应/职测/公基/规划（MIT）
├── scripts/record_daily.py             日报写入器（event_id 幂等，独立于上游朱批录）
├── webapp/                             纯静态网页客户端（自有 OpenAI 兼容端点，见 webapp/README.md）
├── tests/test_project_contract.py      项目契约测试（路由规则/索引 schema/写回幂等）
└── data/
    ├── knowledge/                      暂定知识树 index.json + 派生文档（思维导图）
    ├── 复盘引擎/                        权威逐题状态：错因卡/弱点档案/学习者画像/母题补充/题库
    ├── tracker/daily/（首条日报时创建） 套题与每日汇总原始记录
    └── exams/ catalog.json             考试元数据（全部"待官方核验"）
```

**两个数据视图，分别汇报、不能相加**：逐题错误以 `data/复盘引擎/` 为准；每日/套题统计以 `data/tracker/daily/` 原始记录重算。

### 外部研究库（exam-research）挂载

`.agents/skills/xingce-review-pro/references/method-libraries/exam-research/` 内除 INDEX.md 外均为指向 `~/Downloads/exam-research`（58,890 题真题研究库，非 git 仓库）的软链接：公式手册、成语频次、高频考点 Top100、95 张母题卡。接入点与质量分级见该目录 [INDEX.md](.agents/skills/xingce-review-pro/references/method-libraries/exam-research/INDEX.md)；题库本体在 `data/复盘引擎/题库/`（总题库 387 题 + 全量池 20,921 题，rg 按 kp/qid/year 检索）。

**学习闭环**：讲题收尾做母题归纳（引用母题卡）→ 新变体沉淀到 `data/复盘引擎/母题补充/<主考点>.md` → `考我` 按总题库 → 母题补充 → 全量池的顺序取题。

## 网页客户端（webapp/）

不依赖 ZCode 的浏览器版：`python3 webapp/serve.py` 启动（含题库/方法库一键只读挂载），本地 <http://127.0.0.1:8901> 即用，或按 [webapp/README.md](webapp/README.md) 部署到 GitHub Pages。讲解走你自己的 OpenAI 兼容端点（DeepSeek/智谱/Ollama/LM Studio）；方法库、题库、错题、API Key 全部只存浏览器本地，部署产物不含任何题库与个人数据。

## 数据备份与恢复（私有仓库策略）

- 仓库 `fejxc/codex-kaogong-agent` 自 **2026-10-29 起为私有**，作为个人存放平台：`data/`（题库、错因卡、画像、日报）全量入库，约 39MB。
- **转公开前必须先移除 `data/` 个人数据与题库**，并重跑 [GitHub开源预检](docs/GitHub开源预检.md)。
- 新机恢复：克隆本仓库 → 安装 exam-research 到 `~/Downloads/exam-research` → 重建挂载软链接（参照 INDEX.md 表格内的源路径）→ 新开任务刷新技能索引。
- 不上传飞书或任何第三方服务；不开启 OCR API 或定时任务。

## 日常操作约定

- **添加错题**：给题目、自己的答案、标准答案/来源和解题过程；满足门禁（已核验判错 + 讲解完成 + 题面无冲突）才写 `data/复盘引擎/`。错因不明只标"待确认"。
- **添加粉笔知识点**：提供讲义/目录/截图并注明课程章节，核对后再更新知识节点；模糊截图中的数字先核对。
- **真题与来源**：考试来源、年份、科目只接受用户提供或来源核验的信息；没有已核验题库时不虚构真题。

## 第三方 Skills 与更新

- `.agents/skills/` 内两份 Skill 是**唯一权威副本**（版本化）。用户级目录若装有同名 `kaogong`，以项目副本为准；两处同时存在时应对齐，避免漂移。
- 更新流程：按[审查报告](docs/第三方技能审查.md)记录的仓库和版本重新克隆到临时目录审查验证，再更新 `.agents/skills/`；不执行上游安装脚本；个人状态永远留在 `data/`，不进 Skill 包。
- 朱批录 `kaogong-study-tracker` 只作日报字段参考；不调用其非幂等计数脚本（`update_daily.js` 会重复计数，错题列表无幂等键）。
- 花生十三仅作明确要求时的补充参考；上游无独立 LICENSE，不复制其资料。

## 许可证

**多许可证仓库**：项目自有文件 MIT；`kaogong` 上游 MIT；`xingce-review-pro` 上游 GPL-3.0-only。逐目录范围见 [LICENSES.md](LICENSES.md)，不要整体标作单一 MIT。
