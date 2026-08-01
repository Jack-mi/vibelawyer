# Marketplace 上架 TODO（本地跟踪）

> 更新：2026-08-01。目标：PyPI 本地包 + mcp-marketplace.io **免费**上架 + 官方 Registry。

## 已完成

- [x] 确认主形态：本地 stdio MCP（PyPI），非 Docker / 非公网托管
- [x] `pyproject.toml` 补齐元数据、`vibelawyer-mcp` 入口、MIT
- [x] README：Cursor / Claude Code / Claude Desktop 接入示例
- [x] `LAUNCHGUIDE.md` 提交表单建议值
- [x] `uv build` 本地构建通过
- [x] GitHub 仓库改为 **Public**
- [x] 推送含打包改动的 `main`
- [x] PyPI 发布 `vibelawyer==0.1.0` / `0.1.1`（含 `<!-- mcp-name: io.github.Jack-mi/vibelawyer -->`）
- [x] 新增 `server.json`；`mcp-publisher validate` 通过
- [x] 冒烟：`uvx --from vibelawyer vibelawyer-mcp` 可启动 FastMCP stdio

## 待办（需人工 GitHub 登录）

- [ ] 在 [mcp-marketplace.io](https://mcp-marketplace.io) 用 GitHub 登录 Creator 账号
- [ ] 打开 [/submit](https://mcp-marketplace.io/submit)，按 `LAUNCHGUIDE.md` 填表，定价选 **Free**
- [ ] `mcp-publisher login github` + `mcp-publisher publish` → [官方 Registry](https://registry.modelcontextprotocol.io)
- [ ] 等待安全扫描与审核通过；核对 listing 安装命令为 `uvx --from vibelawyer vibelawyer-mcp`

## 上架后可选

- [ ] Smithery 本地 MCPB（发现渠道，非必须）
- [ ] mcp.so / Glama / awesome-mcp-servers 发现渠道
- [ ] 日后收费：接入 `mcp-marketplace-license`，改 listing 定价

## 官方 Registry 一键命令（登录后）

```bash
/tmp/mcp-publisher login github
cd /path/to/vibelawyer && /tmp/mcp-publisher publish
```
