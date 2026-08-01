# OpenCode 会话任务轨迹：律师版对标迭代 + FastMCP 服务化

> 来源：OpenCode session `ses_0437bf8bfffebYyYCdQDYr2FBF`  
> 标题：律师答案与Agent输出对照及迭代建议  
> 时间：2026-08-01 16:49 – 17:22  
> 本文按会话结束时的真实代码状态梳理（含会话中途写入 `迭代进度.md` 之后又完成的 `docx_notes.py` 重写）。

---

## 一、目标是什么

两条并行目标，由用户在该 session 中先后提出：

### A. 对标律师版，补齐产出差距

对照律师手工材料的产出颗粒度与当前 Agent 规格，把整条链路迭代到律师可用的深度，同时**保留我方领先能力**（强制 Citation + 页码校验、证据索引总表、阅卷结论/矛盾点）。

律师版暴露的核心差距（按严重度）：

| 优先级 | 差距 | 落地方向 |
|--------|------|----------|
| P0 | 笔录只有摘要，律师是逐字问答全文 | `Statement.full_text` + 提取指令 + docx 渲染 |
| P0 | 书证平铺，律师按「待证事实」分组 | `fact_group` + 分组渲染 |
| P0 | 无逐笔资金流水 | `Transaction` + `add_transaction` + 流水子表 |
| P1 | 缺金额勾稽（报案/合同/违法所得/已退赔等） | `FundsSummary` + 结论前勾稽表 |
| P1 | 程序性文书缺文号；docx 无自动目录 | `doc_no` + TOC 域 |
| P2 | 供述标题行、xlsx 分卷总览、量刑情节结构化 | 标题格式 / 新 sheet / `sentencing_circumstances` |

### B. 用 FastMCP 封装为可对外部署的 MCP Server

把系统抽象成带 `case_id` 的工具面，支持：

- 案件生命周期（创建 / 列表 / 状态）
- 读卷（目录、页码、检索）
- 登记（当事人、起诉书、笔录、书证、流水、结论、资金勾稽等）
- 校验与导出（Citation 校验、写 docx/xlsx、下载 File）
- 全流程异步 job（`start_review` + 进度轮询）

技术选型（session 内 librarian 核实，fastmcp **3.4.5**）：

- 钉版 `fastmcp>=3.4.5,<4`
- 部署：`mcp.run(transport="http")`，客户端连 `http://host:port/mcp`（SSE 已废弃）
- 长任务：`job_id` + 状态轮询（v1 不依赖 4.0 TasksExtension）
- 文件下发：tool 返回 `File` 或 resource bytes
- 多案件状态：`sessions.py` 模块级注册表；v1 全流程 job 期间拒绝他案交互调用

对照材料已清除（不入库）；差距目标见上文 P0/P1/P2 清单。

---

## 二、他做了哪些（已完成）

### 1. 对照分析（流程目标）

- 曾写入对照分析文档，**已删除**（含真实案情，不入库）
- 输出 P0/P1/P2 差距清单并落到具体文件改动点（见上文）

### 2. 环境

- 新建 `.venv`（Python 3.12），安装 pypdfium2 / python-docx / openpyxl / Pillow / numpy / **fastmcp 3.4.5** / claude-agent-sdk
- 确认 CLAUDE.md 中 conda base 路径已失效（文档修正仍属未完成）

### 3. 数据模型 `vibelawyer/workspace.py`

- `Transaction`（日期/付款方/收款方/金额/账户/备注/页码）
- `FundsSummary`（报案合计/合同合计/指控金额/已返还/违法所得/已退赔/勾稽说明）
- `Statement` +`full_text`、+`occasion`
- `ProceduralDoc` / `DocumentaryEvidence` +`doc_no`、+`fact_group`；书证 +`transactions`
- `IndictmentInfo` +`sentencing_circumstances`
- `CaseWorkspace.funds`、`attach_transaction()`、校验与 `to_dict()` 同步；`set_workspace()` 供会话绑定

### 4. 会话注册表 `vibelawyer/sessions.py`（新文件）

- `CaseSession`：cfg + VolumeStore + CaseWorkspace + job 状态，按 `case_id` 隔离
- `SessionManager` / 全局 `MANAGER`：create / ensure_docling_cache / get / list / running_session
- v1 并发约束：全流程 job 运行中拒绝他案交互调用

### 5. 工具层 `vibelawyer/tools.py`

- 全局 `_STORE/_CFG` → **活动会话绑定**（`bind_session` / `active_session`）
- 登记工具扩展新字段；新增 `add_transaction`、`record_funds_summary`
- `get_workspace_summary` 增强（全文份数、文号、流水、资金勾稽进度）
- 新工具已注册进 `get_tools()`

### 6. 子 agent + 编排 `agents.py` / `orchestrator.py`

- 供述/证言：强制 `full_text` 逐字转录问答
- 程序性文书：提取文号；书证：`fact_group` + 流水逐笔登记
- 起诉书：量刑情节；结论员：全文矛盾比对 + 资金勾稽登记
- `run_case` 支持 `session=` 复用与 `progress=` 回调（供 MCP job 上报）

### 7. Word 生成器 `generators/docx_notes.py`（会话末尾已重写，todo 未勾完但代码已落地）

相对中途 `迭代进度.md` 的「未完成」状态，会话结束前已写入：

- 标题后自动 TOC 域
- 供述一行式标题 + 要点 + **全文渲染**
- 程序/书证按 `fact_group` 分组，表格含**文号列**
- 书证下「资金流水」子表
- 起诉书部分渲染量刑情节
- 结论前「资金勾稽一览」表

---

## 三、还差哪些（未完成）

按建议执行顺序：

| # | 任务 | 状态 | 要点 |
|---|------|------|------|
| 1 | `generators/docx_notes.py` 渲染升级 | **代码已写，待冒烟验证** | 结构已对标；需合成 workspace 渲染并断言关键结构；todo 清单里仍标 pending |
| 2 | `generators/xlsx_catalog.py` 升级 | **未开始** | 新增「分卷总览」sheet（每卷一行 + `P起-止:文件名` 索引式提要）；案件信息 sheet 增加资金勾稽与流水笔数 |
| 3 | `vibelawyer/mcp_server.py` | **未开始（核心交付物）** | FastMCP 薄封装，工具均带 `case_id`：生命周期 / 读卷 / 登记 / 校验导出 / `start_review` + `get_review_progress`；bind 会话后复用 `tools.py`，零逻辑重复 |
| 4 | 打包与文档 | **未开始** | `pyproject.toml` 加 `fastmcp>=3.4.5,<4` 与 `vibelawyer-mcp` 入口；README 补 MCP 用法（stdio / http / 鉴权）；修正 CLAUDE.md 失效 python 路径 |
| 5 | 冒烟验证 | **未开始** | 全模块 `py_compile`；合成 workspace 渲染 docx+xlsx 断言；FastMCP app 实例化并列出工具清单 |

### 遗留风险（会话已标出，仍有效）

- 本机无 `data/` 卷宗 PDF（仓库不收录真实案例），无法端到端实测；拿到脱敏样例后需重跑并做**内容级 diff**（讯问次数、逐字质量、流水完整度、OCR 错字）
- 逐字全文显著抬高 token 成本
- v1 单进程同时只能跑一个全流程 job
- MCP `create_case` 不做 docling 预转换，首次 `start_review` 耗时随页数增长
- **强制 Citation 不得为凑全文而放宽**

---

## 四、建议的下一步（最短路径）

1. 冒烟验证 `docx_notes.py`（合成含 full_text / doc_no / transactions / funds / fact_group 的 workspace）
2. 升级 `xlsx_catalog.py`
3. 实现 `mcp_server.py` + pyproject/README
4. FastMCP 工具清单 + 编译冒烟
5. 有脱敏样例卷宗后再跑全流程，做内容级 diff

---

## 附录：Session Todo 原始清单

| # | 内容 | Session 标记 |
|---|------|--------------|
| 0 | 搭建 .venv 并安装依赖 | completed |
| 1 | workspace.py 数据模型扩展 | completed |
| 2 | tools.py 新字段 + 会话绑定 | completed |
| 3 | agents.py + orchestrator.py 指令升级 | completed |
| 4 | sessions.py 会话注册表 | completed |
| 5 | docx_notes.py 渲染升级 | pending（**代码已写，标记未更新**） |
| 6 | xlsx_catalog.py 升级 | pending |
| 7 | mcp_server.py FastMCP 封装 | pending |
| 8 | pyproject + README MCP 用法 | pending |
| 9 | 冒烟验证 | pending |
