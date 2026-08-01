# vibelawyer —— 通用化刑事案件阅卷 MCP

本地 [FastMCP](https://github.com/PrefectHQ/fastmcp) 阅卷工具箱。给定卷宗 PDF 目录，由 **任意 Coding Agent**（Cursor / Kimi Code / OpenCode / Codex / Claude Desktop 等）调用工具，产出：

- **阅卷笔录**（Word `.docx`）—— 七部分结构 + 案件基本信息 + 阅卷结论（结构化数据完整渲染，无截断）
- **阅卷目录**（Excel `.xlsx`）—— 分卷总览 / 阅卷目录 / 案件信息 / 证据索引

**不依赖 Claude Code CLI。** LLM 推理由宿主 Agent 提供；PDF 解析、OCR、Word/Excel 生成均在本机完成，卷宗不经过本服务上传。

事实与证据须标注来源卷宗及页码（如 `见《主卷》P55-76`），并可机器校验，落实「禁止幻觉、结论可回溯」。

> 对任意刑事案件通用，不假定具体罪名或当事人。本仓库**不收录**真实卷宗；运行时将 PDF 放入本地 `data/`（已 gitignore），产物写入 `output/`（已 gitignore）。

---

## 两种用法（可穿插）

同一 `case_id` 下，**完整流程**与**零散按需**共用全部工具，工作区状态共享。

| 模式 | 何时用 | 怎么做 |
|------|--------|--------|
| **完整阅卷** | 「把这案件按标准流程阅完」 | `create_case` → `start_review` 拿 playbook → 按 Skill 八步顺序调工具 → 校验导出 |
| **按需调用** | 「只查某页 / 只补一条供述 / 只出 Word」 | `create_case` 后直接调 `read_pages` / `record_*` / `write_outputs` 等 |

可先按 playbook 走完大半，再零散补登；也可先散读若干页，再按 playbook 补齐缺步。服务端**不**强制锁步；顺序约束写在 Skill / playbook 里，由宿主 Agent 遵守。

---

## 架构

```
┌──────── 宿主 Coding Agent（Cursor / Kimi / OpenCode / Codex …）────────┐
│  读 skills/vibelawyer-review/SKILL.md；完整流程或按需调 MCP 工具        │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ stdio / http
                                ▼
┌──────── vibelawyer-mcp（FastMCP）─────────────────────────────────────┐
│  create_case / 读卷 / record_* / validate / write_outputs / download   │
│  CaseWorkspace（case_id 隔离）+ 本机 PDF/OCR                            │
└───────────────────────────────┬───────────────────────────────────────┘
                                ▼
               docling → pypdfium2 → tesseract chi_sim
               → 阅卷笔录.docx + 阅卷目录.xlsx
```

| 组件 | 作用 |
|------|------|
| [`vibelawyer/tools.py`](vibelawyer/tools.py) + [`tool_spec.py`](vibelawyer/tool_spec.py) | 原子工具（本地 `ToolSpec`，无 `claude-agent-sdk`） |
| [`vibelawyer/mcp_server.py`](vibelawyer/mcp_server.py) | FastMCP 对外暴露；passthrough 复用 handler |
| [`vibelawyer/playbook.py`](vibelawyer/playbook.py) | 标准步骤与铁律；与 Skill / `start_review` 同源 |
| [`skills/vibelawyer-review/SKILL.md`](skills/vibelawyer-review/SKILL.md) | 宿主可加载的阅卷 Skill |
| [`vibelawyer/sessions.py`](vibelawyer/sessions.py) | 多案件 `case_id` 隔离 |

`start_review` **只下发 playbook**，不启动后台 LLM job。

可选遗留：`pip install 'vibelawyer[legacy-agent]'` + `python -m vibelawyer.run --legacy`（需本机 Claude Code CLI，非默认路径）。

---

## 安装

```bash
pip install vibelawyer
# 开发安装
pip install -e .
```

- Python ≥ 3.11  
- **无需** Claude Code CLI  
- 可选（推荐）：本地 docling venv（`~/.local/share/docling-venv`）提升扫描件 OCR  
- 可选：`tesseract` + `chi_sim` 作为 OCR 回退  

---

## 接入宿主 Agent（推荐）

```bash
uvx --from vibelawyer vibelawyer-mcp
# 已 pip install 时：
vibelawyer-mcp
```

### Cursor / 通用 `mcp.json`

```json
{
  "mcpServers": {
    "vibelawyer": {
      "command": "uvx",
      "args": ["--from", "vibelawyer", "vibelawyer-mcp"]
    }
  }
}
```

### Claude Desktop（`claude_desktop_config.json`）

```json
{
  "mcpServers": {
    "vibelawyer": {
      "command": "uvx",
      "args": ["--from", "vibelawyer", "vibelawyer-mcp"]
    }
  }
}
```

### Kimi Code / OpenCode / Codex

在各自 MCP 配置中填入同一 `command` / `args`。已安装包时可将 `command` 改为 `vibelawyer-mcp`、`args` 留空。

配置完成后，让 Agent 阅读并遵循：

**[`skills/vibelawyer-review/SKILL.md`](skills/vibelawyer-review/SKILL.md)**

（或调用 `start_review` 获取与 Skill 同源的结构化 playbook。）

---

## 典型流程

### A. 完整阅卷

1. `create_case(case_dir="/绝对路径/到卷宗目录")` → `case_id`  
   （可选 `defendant_hint` / `charge_hint` / `output_dir`）
2. `start_review(case_id)` → 拿到 steps / 铁律 / 调用约定
3. 按步：编目录 → 起诉书/当事人 → 被告供述 → 同案 → 证人 → 程序性文书 → 书证/流水 → 结论  
   每步用 `get_case_status` 或 `get_workspace_summary` **核实登记计数**（勿信口头「已完成」）
4. `validate_citations` → `write_outputs` → `download_output(fmt="docx"|"xlsx")`

### B. 按需单次调用

```
create_case(...)
list_volumes / search_volumes / read_pages / get_volume_outline   # 只读
record_* / add_*                                                   # 补登记
write_outputs / download_output                                    # 仅导出
```

### CLI 辅助

```bash
python -m vibelawyer.run                # 打印 MCP 接入指引
python -m vibelawyer.run --print-playbook   # 打印完整 playbook（Markdown）

# 诊断 / 渲染冒烟（不调用 LLM）
python scripts/diag.py
python scripts/smoke_render.py
```

### HTTP（可选）

```bash
VIBELAWYER_MCP_TRANSPORT=http VIBELAWYER_MCP_PORT=8000 vibelawyer-mcp
# 可选鉴权：VIBELAWYER_MCP_TOKEN=<secret>
```

---

## 工具一览（约 25 个）

Passthrough 读/写/校验工具签名：`tool_name(case_id, args={...})`。

### 生命周期与工作流

| 工具 | 作用 |
|------|------|
| `create_case` | 发现 PDF、建会话，返回 `case_id` |
| `list_cases` / `get_case_status` | 会话列表与各部分登记计数 |
| `start_review` | 下发 playbook（宿主执行；无后台 job） |
| `get_review_progress` | 说明无后台 job，并再次附上 playbook |
| `download_output` | 取回 `docx` / `xlsx` |

### 读卷

| 工具 | 作用 |
|------|------|
| `list_volumes` | 卷宗名 / 文件 / 页数 |
| `get_volume_outline` | 逐页概览（定位文书边界） |
| `read_pages` | 页码区间文本（含本地 OCR） |
| `search_volumes` | 跨卷关键词检索 |
| `get_page_image` | 渲染页面图像（视觉） |

### 登记（强制带来源卷宗名 + 页码）

| 工具 | 笔录部分 |
|------|----------|
| `set_case_basic` | 案件基本信息 |
| `record_party` | 一、当事人（仅本案被告人） |
| `record_indictment` / `add_charged_fact` | 二、起诉书 / 指控事实 |
| `record_statement(role=defendant\|codefendant\|witness)` | 三～五、供述与证言（宜含 `full_text`） |
| `record_procedural_doc` | 六、程序性文书（含文号） |
| `record_documentary_evidence` / `add_transaction` | 七、书证与资金流水 |
| `add_catalog_entry` | 阅卷目录条目 |
| `record_conclusions` / `record_funds_summary` | 结论与资金勾稽 |

### 校验与导出

| 工具 | 作用 |
|------|------|
| `get_workspace_summary` | 各部分登记进度 |
| `validate_citations` | 校验引用页码合法性 |
| `write_outputs` | 生成 Word 笔录 + Excel 目录 |

---

## 标准阅卷步骤（playbook）

与 [`playbook.py`](vibelawyer/playbook.py) / Skill 一致：

1. **编制阅卷目录** — `add_catalog_entry`，定位起诉书页  
2. **起诉书与当事人** — `set_case_basic` / `record_party` / `record_indictment` / `add_charged_fact`  
3. **被告人供述** — `record_statement(role=defendant)`，含逐字 `full_text`  
4. **同案人供述** — 无则跳过；有则 `role=codefendant`  
5. **证人证言** — `role=witness`  
6. **程序性文书** — `record_procedural_doc`（尽量含文号）  
7. **书证与流水** — `record_documentary_evidence` + 流水类 `add_transaction`  
8. **阅卷结论** — `record_conclusions` / `record_funds_summary`（不做正式辩护策略）  
9. **校验导出** — `validate_citations` → `write_outputs` → `download_output`  

### 铁律（摘要）

1. 只能依据 `read_pages` 实际读到的内容登记，严禁编造  
2. 每条记录必须带来源卷宗名与页码  
3. **交付物 = 工具调用**，不是口头报告  
4. 先 `get_volume_outline` 再精读；用 `search_volumes` 防遗漏  
5. 每步结束用 `get_workspace_summary` / `get_case_status` 核实计数  

---

## 阅卷笔录结构

1. 当事人基本情况（职务犯罪含任职情况）  
2. 起诉书、起诉意见书内容  
3. 被告人的供述和辩解  
4. 同案人员的供述和辩解  
5. 证人证言  
6. 程序性文书  
7. 书证  

附：阅卷目录、阅卷结论（核心事实 / 证据链条 / 矛盾点 / 待核查疑点）。

---

## 在新案件上使用

1. 新建本地目录，放入卷宗 PDF（文件名即卷宗名；会清理 `(2)` 等后缀）  
2. 宿主 Agent：`create_case(case_dir="<绝对路径>")`  
3. 完整流程走 Skill，或按需调工具后 `write_outputs`  

无需改代码即可用于受贿、贪污、诈骗、非法吸收公众存款等；职务犯罪会提取任职情况。

---

## 约束与边界

- **仅本地工具面**：解析 / OCR / 生成在本机；不把卷宗上传到 vibelawyer 服务（宿主模型调用由其厂商负责）  
- **可回溯**：事实须带来源页码；`validate_citations` 防幻觉页码  
- **范围**：只做阅卷目录与笔录梳理，**不生成**正式辩护策略或出庭意见  
- **仓库不含案卷**：`data/`、`output/`、`tessdata/` 已 gitignore，勿提交真实卷宗或当事人信息  

---

## 目录结构

```
vibelawyer/
  tool_spec.py       本地 @tool / ToolSpec
  tools.py           原子工具 handler
  playbook.py        宿主步骤与铁律（与 Skill 同源）
  mcp_server.py      FastMCP Server
  sessions.py        case_id 会话
  workspace.py       CaseWorkspace + 引用校验
  pdf_volume.py      docling / pypdfium2 / tesseract
  config.py          案件发现与配置
  orchestrator.py    可选 legacy（Claude Code）
  agents.py          分步提示别名
  run.py             CLI 指引 / --print-playbook / --legacy
  generators/        docx + xlsx
skills/vibelawyer-review/SKILL.md
scripts/diag.py
scripts/smoke_render.py
```

---

## License

MIT
