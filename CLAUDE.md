# vibelawyer

通用化刑事案件阅卷 —— **FastMCP 本地工具箱 + 宿主 Agent Skill**。
输入卷宗 PDF 目录 → 宿主 Agent 按 playbook 调工具 → 产出阅卷笔录(Word) + 阅卷目录(Excel)。
**不依赖 Claude Code CLI**；默认安装不含 `claude-agent-sdk`。

## 快速命令

```bash
# 打印 MCP 接入指引
python -m vibelawyer.run

# 打印宿主阅卷 playbook
python -m vibelawyer.run --print-playbook

# 启动 MCP Server（stdio）
python -m vibelawyer.mcp_server
# 或: vibelawyer-mcp

# 诊断 / 渲染冒烟（不调用 LLM）
python scripts/diag.py
python scripts/smoke_render.py
```

宿主请阅读并执行：`skills/vibelawyer-review/SKILL.md`。

## 架构要点（改代码前必读）

- **默认路径**：任意 Coding Agent 接 `vibelawyer-mcp`，按 [`playbook.py`](vibelawyer/playbook.py) / Skill 八步调用工具；也可同一 `case_id` 下零散按需调工具。`start_review` **只下发 playbook**，不启后台 LLM job。
- **原子工具** [`tools.py`](vibelawyer/tools.py)：本地 [`tool_spec.py`](vibelawyer/tool_spec.py) 的 `ToolSpec`；FastMCP 薄封装复用 `.handler`。
- **每条记录强制带来源引用**；`validate_citations` 防幻觉页码。改输出看 `generators/`。
- **卷宗解析**：docling → pypdfium2 → tesseract chi_sim。
- **可选 legacy**：`pip install 'vibelawyer[legacy-agent]'` + `python -m vibelawyer.run --legacy`（需本机 Claude Code CLI）。

## 数据约定

本仓库**不收录**真实卷宗或产出物。运行时把 PDF 放到本地 `data/`（已 gitignore），产物写入 `output/`（已 gitignore）。
