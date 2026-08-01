# vibelawyer

通用化刑事案件阅卷 Agent —— 基于 claude-agent-sdk-python 的多智能体系统。
输入卷宗 PDF 目录 → 产出阅卷笔录(Word) + 阅卷目录(Excel)。最终产出仅 docx/xlsx（无 JSON），结构化数据完整渲染无截断。

## 快速命令

```bash
# 用 conda base python（依赖已装：pypdfium2/python-docx/openpyxl/claude_agent_sdk/fastmcp）
/opt/homebrew/Caskroom/miniconda/base/bin/python -m vibelawyer.run

# 启动 MCP Server（本机 stdio；对外 http/鉴权见 README 的「MCP Server」一节）
VIBELAWYER_MCP_TRANSPORT=stdio /opt/homebrew/Caskroom/miniconda/base/bin/python -m vibelawyer.mcp_server

# 诊断（不调用 LLM）
/opt/homebrew/Caskroom/miniconda/base/bin/python scripts/diag.py

# 渲染冒烟（合成 workspace，不调用 LLM，验证 docx/xlsx 结构对标律师版）
/opt/homebrew/Caskroom/miniconda/base/bin/python scripts/smoke_render.py
```

## 架构要点（改代码前必读）

- **主编排器** `vibelawyer/orchestrator.py: run_case` 顺序运行 8 个子 agent（各为独立 top-level `query()` 会话，**非** Task 工具——本环境 Task 子 agent 收不到 MCP 工具结果）。
- **原子工具** `vibelawyer/tools.py` 经 `create_sdk_mcp_server` 进程内 MCP；所有子 agent 共享同一 `CaseWorkspace`（`workspace.py`，带锁）。
- **每条记录强制带来源引用**（卷宗名+页码），`validate_citations` 校验页码合法性防幻觉。改输出格式看 `generators/`。
- **卷宗解析回退链** `pdf_volume.py`：docling 缓存（`docling_cache.py` 调 `~/.local/share/docling-venv`）→ pypdfium2 文本层 → tesseract chi_sim（`tessdata/`）。docling 质量最高，首次运行预转换约 4 分钟，缓存于 `output/.docling_cache/`。
- `permission_mode=bypassPermissions`；禁用 Bash/Read/Edit/Web 等内置工具，信息只经 MCP 工具留痕。
- **MCP 服务化** `vibelawyer/mcp_server.py`：用 FastMCP 把工具面封装为带 `case_id` 的对外 MCP Server（读卷/登记/校验导出工具复用 `tools.py` 的 handler，零逻辑重复）；`sessions.py` 按 `case_id` 隔离多案件会话。全流程 job 运行期间拒绝他案并发调用（v1 单进程单 job）。

## 示例案件

`data/` 下为张小双涉嫌非法吸收公众存款案（4 卷 54 页扫描件，非模板的受贿案——系统通用化）。
