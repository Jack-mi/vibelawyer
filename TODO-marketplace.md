# Marketplace 上架 TODO（本地跟踪）

> 更新：2026-08-01。目标：PyPI 本地包 + mcp-marketplace.io **免费**上架。

## 已完成

- [x] 确认主形态：本地 stdio MCP（PyPI），非 Docker / 非公网托管
- [x] `pyproject.toml` 补齐元数据、`vibelawyer-mcp` 入口、MIT
- [x] README：Cursor / Claude Code / Claude Desktop 接入示例
- [x] `LAUNCHGUIDE.md` 提交表单建议值
- [x] `uv build` 本地构建通过

## 待办（上架阻塞项）

- [ ] GitHub 仓库改为 **Public**（当前对外 404/私有，Marketplace 要求公开）
- [ ] 推送含打包改动的 `main`（本 commit）
- [ ] 申请 PyPI API Token，执行 `uv publish` 发布 `vibelawyer==0.1.0`
- [ ] 在 [mcp-marketplace.io](https://mcp-marketplace.io) 用 GitHub 登录 Creator 账号
- [ ] 打开 [/submit](https://mcp-marketplace.io/submit)，按 `LAUNCHGUIDE.md` 填表，定价选 **Free**
- [ ] 等待安全扫描与审核通过；核对 listing 安装命令为 `uvx --from vibelawyer vibelawyer-mcp`

## 上架后可选

- [ ] Smithery 本地 MCPB（发现渠道，非必须）
- [ ] 日后收费：接入 `mcp-marketplace-license`，改 listing 定价
