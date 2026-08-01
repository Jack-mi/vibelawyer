# vibelawyer —— 通用化刑事案件阅卷 Agent

基于 [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python) 构建的多智能体阅卷系统。
给定一个存放卷宗 PDF 的目录，由**主编排器**按阅卷工作流顺序运行若干**专职子 agent** 完成阅卷梳理，产出：

- **阅卷笔录**（Word `.docx`）—— 含七部分结构 + 案件基本信息表 + 阅卷结论（结构化数据完整渲染，无截断）
- **阅卷目录**（Excel `.xlsx`）—— 卷宗目录 / 案件信息 / 证据索引追溯总表

最终产出仅为 Word + Excel（无 JSON）；所有结构化数据（含来源引用对象、context、法律条文、结论原文）均完整渲染进 docx，信息不丢失。

所有事实与证据引用均标注来源卷宗及页码（如 `见《主卷》P55-76`），并可机器校验，落实“禁止幻觉、结论可回溯”。

> 系统对任意刑事案件通用，不假定具体罪名或当事人；本案以 `data/` 下的卷宗为示例运行。

---

## 架构

```
┌──────────────── Python 主编排器（vibelawyer/orchestrator.py: run_case）────────────────┐
│  按阅卷工作流顺序运行各专职子 agent（每个为独立 top-level query() 会话），             │
│  共享同一进程内 MCP 工具与 CaseWorkspace；每步用 get_workspace_summary 核实实际登记数。 │
│                                                                                        │
│  case-indexer → indictment-reader → defendant-statement-extractor                      │
│                                  → codefendant-statement-extractor                      │
│                                  → witness-statement-extractor                          │
│                                  → procedural-extractor                                 │
│                                  → evidence-extractor                                   │
│                                  → conclusion-synthesizer                               │
│  → validate_citations + write_outputs（生成 Word/Excel，完整渲染结构化数据）              │
└────────────────────────────────────────────────────────────────────────────────────────┘
        │ 所有 agent 共享进程内 MCP 工具（读卷 + 登记 + 校验 + 导出）+ CaseWorkspace │
        ▼ 卷宗文本提取（三级回退）：docling(RapidOCR) → pypdfium2 文本层 → tesseract chi_sim
```

- **原子工具**（`vibelawyer/tools.py`）：以 `@tool` 定义，经 `create_sdk_mcp_server` 注册为进程内 MCP server，所有子 agent 共享，直接操作同一 `CaseWorkspace`。
- **子 agent**（`vibelawyer/agents.py`）：`AgentDefinition` 定义，各负责笔录一个部分；主编排器以独立 `query()` 会话顺序运行（共享进程内工具与工作区，OCR 结果缓存复用）。
- **主编排器**（`vibelawyer/orchestrator.py`）：`run_case` 顺序编排 + 逐步核实 + 校验导出。
- **卷宗解析**（`vibelawyer/pdf_volume.py` + `docling_cache.py`）：首选 docling（RapidOCR，中文扫描件质量最高），不可用时回退 pypdfium2 文本层 + tesseract chi_sim。

### 工具接口被刻意收窄

`disallowed_tools` 禁用了文件改写（Edit/Write/Bash）、联网（WebFetch/WebSearch）、自由读盘（Read/Grep/Glob）等内置工具，强制一切信息经 MCP 工具留痕；`permission_mode="bypassPermissions"` 实现端到端无人值守运行。

### 为什么子 agent 用顺序 top-level 会话而非 Task 工具

实测在本环境（SDK CLI 经代理路由）下，`Task` 工具启动的子 agent 收不到 MCP 工具结果（返回空），会导致退化循环。改为由 Python 主编排器把每个子 agent 作为独立 `query()` 会话顺序运行，工具结果稳定可达，且 OCR 结果在进程内缓存、后续 agent 读取同页近乎零成本。

---

## 工具目录（原子化）

### 读工具
| 工具 | 作用 |
|---|---|
| `list_volumes` | 列出全部卷宗（名称/文件/页数） |
| `read_pages` | 读取指定卷宗页码区间文本（自动经 docling/tesseract OCR），每页标注页码 |
| `search_volumes` | 跨卷关键词检索，返回命中卷/页/片段 |
| `get_volume_outline` | 逐页概览（字数+首行），快速定位文书边界 |
| `get_page_image` | 渲染页面为图片返回，用于视觉识别（仅 `--vision` 时启用） |

### 写工具（登记结构化记录，强制带来源引用）
| 工具 | 对应笔录部分 |
|---|---|
| `set_case_basic` | 案件基本信息表 |
| `record_party` | 一、当事人基本情况（含任职情况） |
| `record_indictment` / `add_charged_fact` | 二、起诉书/起诉意见书内容 |
| `record_statement(role=defendant)` | 三、被告人供述和辩解 |
| `record_statement(role=codefendant)` | 四、同案人员供述和辩解 |
| `record_statement(role=witness)` | 五、证人证言 |
| `record_procedural_doc` | 六、程序性文书 |
| `record_documentary_evidence` | 七、书证 |
| `add_catalog_entry` | 阅卷目录 |
| `record_conclusions` | 阅卷结论 |

### 校验与导出工具
| 工具 | 作用 |
|---|---|
| `get_workspace_summary` | 查看各部分登记进度 |
| `validate_citations` | 校验全部来源引用页码合法性（防幻觉） |
| `write_outputs` | 生成 Word 阅卷笔录 + Excel 阅卷目录 |

> 每条 `record_*` 写入前即时校验页码是否落在真实卷宗页数区间内；`validate_citations` 在导出前对全量记录复核。

---

## 阅卷笔录七部分结构

1. 当事人基本情况（职务犯罪含任职情况）
2. 起诉书、起诉意见书内容
3. 被告人的供述和辩解（按指控事实分组：笔录时间/办案人员/办案地点/同步录音录像/笔录内容）
4. 同案人员的供述和辩解
5. 证人证言
6. 程序性文书（含具体时间、地点）
7. 书证（时间/文件名称/卷宗页码/主要内容）

附：阅卷目录、阅卷结论（已查明核心事实 / 证据链条 / 证据矛盾点 / 待核查疑点）。

---

## 安装与运行

### 依赖
- Python ≥ 3.11
- `claude-agent-sdk`、`pypdfium2`、`python-docx`、`openpyxl`、`Pillow`、`numpy`、`fastmcp`（MCP Server 用）
- **可选（强烈推荐）**：本地 `docling` venv（`~/.local/share/docling-venv`，含 torch/opencv/rapidocr）—— 启用后扫描件 OCR 质量显著优于 tesseract。无则自动回退 tesseract+chi_sim。
- **可选**：`tesseract` + `chi_sim.traineddata`（放 `tessdata/`）—— docling 不可用时的回退 OCR。
- 本机已登录 Claude Code CLI（SDK 以子进程方式调用）

```bash
pip install pypdfium2 python-docx openpyxl Pillow numpy claude-agent-sdk fastmcp
```

### 运行

```bash
# 默认对 ./data 目录下的卷宗阅卷，输出到 ./output（首选 docling，自动回退 tesseract）
python -m vibelawyer.run

# 指定案件目录与输出目录，并给当事人/罪名提示（可选）
python -m vibelawyer.run --case-dir ./data --output-dir ./output \
    --defendant 张小双 --verbose

# 禁用 docling，仅用 pypdfium2+tesseract
python -m vibelawyer.run --no-docling

# 启用视觉识别（仅当 SDK 运行环境支持图像输入时）
python -m vibelawyer.run --vision

# 诊断（不调用 LLM，验证 PDF 解析/工具层/生成器）
python scripts/diag.py
```

首次运行若启用 docling，会在项目级 `.cache/docling_cache/` 预转换全部卷宗为按页文本缓存（一次性，约 4 分钟/54 页），之后复用。该缓存是中间产物，不进入 `output/`。

运行结束后（`output/` 仅含以下交付物 + 运行日志）：
- `output/<案名>_阅卷笔录.docx`
- `output/<案名>_阅卷目录.xlsx`

### 在新案件上运行

1. 新建案件目录，放入卷宗 PDF（文件名即卷宗名，会自动清理 `(2)` 等后缀）。
2. `python -m vibelawyer.run --case-dir <新案件目录>`。
3. 系统自动发现卷宗、识别当事人/罪名/金额，按工作流产出笔录与目录。

无需改代码即适用于受贿、贪污、诈骗、职务侵占等各类刑事案件；职务犯罪会自动提取任职情况。

---

## MCP Server（对外服务化）

`vibelawyer/mcp_server.py` 用 [FastMCP](https://github.com/jlowin/fastmcp) 把阅卷系统封装为带 `case_id` 的对外 MCP Server。工具面：

- **生命周期**：`create_case` / `list_cases` / `get_case_status`
- **读卷**：`list_volumes` / `get_volume_outline` / `read_pages` / `search_volumes` / `get_page_image`
- **登记**：`set_case_basic` / `record_party` / `record_indictment` / `add_charged_fact` / `record_statement` / `record_procedural_doc` / `record_documentary_evidence` / `add_transaction` / `add_catalog_entry` / `record_conclusions` / `record_funds_summary`
- **校验导出**：`validate_citations` / `get_workspace_summary` / `write_outputs` / `download_output`（下发 docx/xlsx）
- **全流程**：`start_review`（后台线程跑 `run_case`，立即返回）/ `get_review_progress`（轮询 status+step+log 尾部）

读/登记/校验/导出类工具直接复用 `tools.py` 的 `handler`，零逻辑重复。

> v1 并发约束：全流程阅卷 job 运行期间，其他案件的交互式工具调用会被拒绝（进程内活动会话绑定不可串号）；同一案件的查询不受影响。

### 本机 stdio（调试 / Claude Desktop 接入）

```bash
VIBELAWYER_MCP_TRANSPORT=stdio python -m vibelawyer.mcp_server
# 或经入口脚本（pip install -e . 后）
vibelawyer-mcp
```

### 对外 http 部署

```bash
VIBELAWYER_MCP_TRANSPORT=http \
VIBELAWYER_MCP_HOST=0.0.0.0 \
VIBELAWYER_MCP_PORT=8000 \
VIBELAWYER_MCP_PATH=/mcp \
python -m vibelawyer.mcp_server
# 客户端连 http://host:8000/mcp
```

### 鉴权（可选）

设置环境变量 `VIBELAWYER_MCP_TOKEN` 即启用 `StaticTokenVerifier`（令牌匹配即放行）：

```bash
VIBELAWYER_MCP_TOKEN=<secret> VIBELAWYER_MCP_TRANSPORT=http python -m vibelawyer.mcp_server
```

如需 JWT，替换 `mcp_server.py` 中 `_make_auth()` 为 `JWTVerifier`：

```python
from fastmcp.server.auth.providers.jwt import JWTVerifier
mcp = FastMCP("vibelawyer", auth=JWTVerifier(jwks_uri="https://<your-idp>/.well-known/jwks.json"))
```

### 典型调用流程

1. `create_case(case_dir="./data")` → 拿到 `case_id`。
2. 交互式逐条登记（`list_volumes` / `read_pages` / `record_*`），或 `start_review(case_id)` 一键跑全流程。
3. `get_review_progress(case_id)` 轮询至 `status=done`。
4. `download_output(case_id, fmt="docx"|"xlsx")` 取件。

`create_case` 不预转换 docling，首次 `start_review` 约 4 分钟/54 页（模型加载 + OCR），之后同案复用缓存。

---

## 约束与边界

- **仅本地**：PDF 解析、OCR、文档生成均在本地完成；禁用联网工具，不上传卷宗到外部服务。
  （LLM 推理经由本机 Claude Code CLI 调用，属 SDK 固有机制。）
- **可回溯**：所有事实/证据必须标注来源卷宗名与页码；`validate_citations` 校验页码合法性，防幻觉与编造。
- **扫描件兜底**：文本层缺失时，`get_page_image` 渲染页面供模型视觉识别；若安装 tesseract + `chi_sim` 语言包则自动本地 OCR。
- **范围限制**：仅做阅卷目录与阅卷笔录的整理及案情梳理，**不生成**正式辩护策略或出庭意见。

---

## 目录结构

```
vibelawyer/
  config.py          案件配置与卷宗自动发现 + OCR 环境确保
  workspace.py       CaseWorkspace 结构化状态 + 引用校验
  pdf_volume.py      PDF 访问层（docling/pypdfium2/tesseract 三级回退 + 检索）
  docling_cache.py   docling 预转换缓存（调用 full docling venv）
  docling_runner.py  docling 转换脚本（在 docling venv 中执行）
  tools.py           原子化 @tool 工具集
  agents.py          8 个专职子 agent 定义
  orchestrator.py    主编排器：顺序子 agent + 核实 + 校验导出
  sessions.py        CaseSession 会话注册表（MCP 多案件隔离）
  mcp_server.py      FastMCP 封装：对外 MCP Server（工具带 case_id）
  run.py             CLI 入口
  generators/
    docx_notes.py    阅卷笔录 Word 生成器
    xlsx_catalog.py  阅卷目录 Excel 生成器（4 表：分卷总览/阅卷目录/案件信息/证据索引）
data/                卷宗 PDF（示例）
tessdata/            tesseract chi_sim 语言包（回退 OCR）
output/              生成结果 + .docling_cache/
scripts/diag.py      诊断脚本
scripts/smoke_render.py  渲染冒烟（合成 workspace，不调 LLM）
```
