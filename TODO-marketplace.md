# Marketplace 上架 TODO（本地跟踪）

> 更新：2026-08-02。目标：PyPI 本地包 + mcp-marketplace.io **免费**上架 + 官方 Registry。

## 已完成

- [x] 确认主形态：本地 stdio MCP（PyPI），非 Docker / 非公网托管
- [x] `pyproject.toml` 补齐元数据、MCP 主入口、MIT
- [x] README：Cursor / Claude Code / Claude Desktop 接入示例
- [x] `LAUNCHGUIDE.md` 提交表单建议值
- [x] `uv build` 本地构建通过
- [x] GitHub 仓库改为 **Public**
- [x] 推送含打包改动的 `main`
- [x] PyPI 发布 `vibelawyer==0.1.0` / `0.1.1`
- [x] 新增 `server.json`；`mcp-publisher validate` 通过
- [x] `mcp-publisher login github` + `mcp-publisher publish` → 官方 Registry（`io.github.Jack-mi/vibelawyer` @ 0.1.1）
- [x] marketplace listing 可见（v0.1.1）

## 0.1.2 修复（Pillow CVE + 入口对齐）

- [x] `Pillow>=12.3.0`（清 marketplace 报告的 5 个 Pillow CVE）
- [x] 主入口 `vibelawyer` → MCP（使 registry/marketplace 的 `uvx vibelawyer` 正确）
- [x] 保留别名 `vibelawyer-mcp`；CLI 迁至 `vibelawyer-cli`
- [x] `server.json` 去掉错误的 `packageArguments`，版本 0.1.2
- [x] 构建 + PyPI 发布 `0.1.2`（缺 mcp-name）/ **`0.1.3`**
- [x] 官方 Registry 发布 `0.1.3`
- [x] marketplace 已出现 `0.1.3` listing：`uvx vibelawyer==0.1.3`，securityScore **10**
- [x] 手工 listing [`/server/vibelawyer`](https://mcp-marketplace.io/server/vibelawyer) 已更新到 **0.1.3** 并重扫通过（score **10.0**，无 ACTION REQUIRED）

## 上架后可选

- [ ] Smithery 本地 MCPB（发现渠道，非必须）
- [ ] mcp.so / Glama / awesome-mcp-servers 发现渠道
- [ ] 日后收费：接入 `mcp-marketplace-license`，改 listing 定价

## 发布命令

```bash
uv build
uv publish   # 需 PyPI API Token

# Official Registry
curl -L "https://github.com/modelcontextprotocol/registry/releases/download/v1.8.0/mcp-publisher_Darwin_arm64.tar.gz" | tar -xz -C /tmp mcp-publisher
/tmp/mcp-publisher login github
/tmp/mcp-publisher publish
```
