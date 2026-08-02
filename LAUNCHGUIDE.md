# LAUNCHGUIDE — MCP Marketplace 免费上架清单

目标：把 **vibelawyer**（本地 stdio MCP）以 **Free** 上架到 [mcp-marketplace.io](https://mcp-marketplace.io)。

官方流程摘要：公开 GitHub → 发到 PyPI → [Submit](https://mcp-marketplace.io/submit) → 安全扫描 → 审核通过后可搜到。

---

## 提交表单建议填写

| 字段 | 建议值 |
|------|--------|
| Name / Package | `vibelawyer` |
| Display name | VibeLawyer |
| Short description | Local MCP for Chinese criminal case dossier review (Word notes + Excel catalog). Case PDFs never leave your machine. |
| Long description | See README. FastMCP stdio server: create_case → start_review (playbook for host agent) → read/record tools → download docx/xlsx. No Claude Code CLI required. |
| GitHub URL | `https://github.com/Jack-mi/vibelawyer` |
| PyPI package | `vibelawyer` |
| Install command | `uvx vibelawyer` |
| Transport | Local / stdio |
| Pricing | **Free** |
| Category | Legal / Productivity / Developer Tools（选平台最接近的） |
| Homepage | `https://github.com/Jack-mi/vibelawyer` |

### 客户端安装片段（平台可能自动生成，可作备份）

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

### 工具清单（25）

`create_case`, `list_cases`, `get_case_status`, `list_volumes`, `get_volume_outline`, `read_pages`, `search_volumes`, `get_page_image`, `set_case_basic`, `record_party`, `record_indictment`, `add_charged_fact`, `record_statement`, `record_procedural_doc`, `record_documentary_evidence`, `add_transaction`, `add_catalog_entry`, `record_conclusions`, `record_funds_summary`, `validate_citations`, `get_workspace_summary`, `write_outputs`, `start_review`, `get_review_progress`, `download_output`

---

## 上架前 Checklist

- [ ] GitHub 仓库为 **public**
- [ ] `pyproject.toml` 含 `vibelawyer-mcp` 入口、`readme`、仓库 URL
- [ ] README 含 Cursor / Claude Code / Claude Desktop 配置
- [ ] `uv build` 成功
- [ ] 已 `uv publish` / `twine upload` 到 PyPI（包名 `vibelawyer` 目前可用）
- [ ] 在 [mcp-marketplace.io](https://mcp-marketplace.io) 注册/登录 Creator 账号
- [ ] 打开 [/submit](https://mcp-marketplace.io/submit)，定价选 **Free**，提交
- [ ] 等待安全扫描与审核

## 本地构建与发布命令

```bash
# 构建
uv build

# 发布到 PyPI（需 API Token：https://pypi.org/manage/account/token/）
uv publish
# 或：
# twine upload dist/*
```

## 注意

- 本产品为 **本地 MCP**：卷宗目录在用户机器上；不要误选 Remote URL 上架形态。
- 全流程阅卷依赖用户本机 Claude Code CLI / 模型凭证（BYOK）。
- 当前免费；日后收费可再加 `mcp-marketplace-license` 并改 listing 定价。
