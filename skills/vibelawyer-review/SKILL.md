---
name: vibelawyer-review
description: >
  刑事案件阅卷：通过 vibelawyer MCP 在本机读卷/登记/导出 Word 笔录与 Excel 目录。
  在用户要阅卷、整理卷宗、生成阅卷笔录/阅卷目录，或已配置 vibelawyer MCP 时使用。
  不依赖 Claude Code CLI；由当前宿主 Agent 按本 Skill 编排工具调用。
---

# 刑事案件阅卷（宿主 Agent + vibelawyer MCP）

卷宗 PDF 只在用户本机处理。你（宿主 Agent）负责推理与编排；`vibelawyer` MCP（入口 `uvx vibelawyer` / 别名 `vibelawyer-mcp`）提供读卷、登记、校验、导出工具。

## 前置：接入 MCP

任选一种（command 相同）：

**Cursor / 通用 `mcp.json`：**

```json
{
  "mcpServers": {
    "vibelawyer": {
      "command": "uvx",
      "args": ["vibelawyer"]
    }
  }
}
```

已 `pip install vibelawyer` 时可用 `"command": "vibelawyer"`（或别名 `vibelawyer-mcp`）、`args` 留空。

Kimi Code / OpenCode / Codex 等：在各自 MCP 配置里填入同一 command。

## FastMCP 调用约定

- 先 `create_case(case_dir="/绝对路径/到卷宗目录")` → 得到 `case_id`。
- 读卷/登记/校验类工具签名：`tool_name(case_id, args={...})`。
  例：`read_pages(case_id="...", args={"volume": "主卷", "start_page": 1, "end_page": 5})`。
- 也可用 `start_review(case_id)` 拉取结构化 playbook（**不会**启动后台 LLM job）。
- 进度看 `get_case_status` / `get_workspace_summary` 的登记计数，不要相信口头「已完成」。

## 铁律

1. **严禁幻觉**：只能基于 `read_pages` 实际读到的内容登记，绝不臆测。
2. **来源必标**：每条记录必须带真实卷宗名与页码区间；拿不准就再读一遍。
3. **交付物 = 工具调用**：必须实际调用 `record_*` / `add_*` 写入工作区；只在回复里复述不算完成。
4. **扫描件**：`read_pages` 已含本地中文 OCR；仍不清则标注「OCR识别不清/待核查」，勿空转要图。
5. **高效**：先 `get_volume_outline`，再 `read_pages` 精读；用 `search_volumes` 防遗漏。
6. **每步收尾**：`get_workspace_summary` 或 `get_case_status` 核实计数后再进入下一步。

## 标准步骤（严格按序）

### 0. 建案

- `create_case(case_dir=...)`（可选 `defendant_hint` / `charge_hint` / `output_dir`）
- 可选：`start_review(case_id)` 获取完整 playbook

### 1. 编制阅卷目录（`case-indexer`）

- 工具：`list_volumes` → `get_volume_outline` → `add_catalog_entry`（逐文件）
- 完成判据：目录条目 > 0，且已定位起诉书/起诉意见书卷页

### 2. 起诉书与当事人（`indictment-reader`）

- 工具：`search_volumes` / `read_pages` → `set_case_basic` → `record_party` → `record_indictment` → `add_charged_fact`
- `record_party` **只登本案被告人**，不是同案人；职务犯罪填任职
- 完成判据：案件基本信息、当事人、起诉书已登记

### 3. 被告人供述（`defendant-statement-extractor`）

- `record_statement`，`args.role = "defendant"`；**必须含 full_text 逐字问答全文**
- 一份讯问笔录一次调用；按时间逐份登记

### 4. 同案人供述（`codefendant-statement-extractor`）

- 无同案人则注明并跳过；有则 `role = "codefendant"`，同样要 full_text

### 5. 证人证言（`witness-statement-extractor`）

- `role = "witness"`；金额/账户/日期等细节原样保留在 full_text

### 6. 程序性文书（`procedural-extractor`）

- `record_procedural_doc`；尽量提取 **文号 doc_no**；按时间覆盖立案至当前

### 7. 书证与资金流水（`evidence-extractor`）

- `record_documentary_evidence`（含 fact_group）
- 流水类必须再 `add_transaction` **逐笔**登记

### 8. 阅卷结论（`conclusion-synthesizer`）

- `record_conclusions`（核心事实 / 证据链 / 矛盾点 / 疑点）
- `record_funds_summary`（各口径金额；不一致在 note 说明）
- **不**输出正式辩护策略

### 9. 校验与导出

- `validate_citations`
- `write_outputs`
- `download_output(case_id, fmt="docx"|"xlsx")`

## 产出

- 阅卷笔录 Word（`.docx`）
- 阅卷目录 Excel（`.xlsx`）

结构化数据完整进文档；不要另造 JSON 交付物。
