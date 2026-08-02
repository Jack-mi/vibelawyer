# MARKETPLACE-UPDATE — 发版 / 重扫操作手册

> 记录日期：2026-08-02。本文件是 **后续改依赖、修 CVE、升版本后** 同步三处（PyPI / 官方 Registry / mcp-marketplace）的可复用流程。  
> 首次上架表单字段见 [`LAUNCHGUIDE.md`](LAUNCHGUIDE.md)；历史勾选见 [`TODO-marketplace.md`](TODO-marketplace.md)。

---

## 渠道与 URL

| 渠道 | URL / 标识 | 说明 |
|------|------------|------|
| PyPI | https://pypi.org/project/vibelawyer/ | 源包；安全扫描读这里的依赖 |
| 官方 MCP Registry | `io.github.Jack-mi/vibelawyer` | `server.json` + `mcp-publisher` |
| Marketplace 手工 listing | https://mcp-marketplace.io/server/vibelawyer | Creator 提交；**不会**因 Registry 更新自动变分 |
| Marketplace Registry 导入 | https://mcp-marketplace.io/server/io-github-jack-mi-vibelawyer | 跟官方 Registry；通常随 publish 更新 |

手工 listing 后台 ID（2026-08 起）：

- **serverId**: `a2f9b266-61cc-45f4-9038-d400a43673c5`
- **编辑页**: https://mcp-marketplace.io/dashboard/edit/a2f9b266-61cc-45f4-9038-d400a43673c5
- **Dashboard**: https://mcp-marketplace.io/dashboard

---

## 发版顺序（必须按序）

```
代码 bump → Git push → PyPI → Official Registry → Marketplace 手工 listing 更新+重扫 → 验收
```

Registry 校验会查 PyPI 上是否已有该 version；手工 listing 重扫也依赖 PyPI 依赖元数据。  
**先 PyPI，再 Registry，再 marketplace。**

---

## Step 0 — 代码与元数据

1. `pyproject.toml`：`version = "x.y.z"`，依赖下限修到安全版本（例：`Pillow>=12.3.0`）。
2. **主 console script 必须叫 `vibelawyer` 且指向 MCP**：
   ```toml
   [project.scripts]
   vibelawyer = "vibelawyer.mcp_server:main"      # registry/marketplace: uvx vibelawyer
   vibelawyer-mcp = "vibelawyer.mcp_server:main"  # 别名
   vibelawyer-cli = "vibelawyer.run:main"         # 本地 CLI
   ```
   原因：官方 Registry / marketplace 对 PyPI 包会拼成 `uvx <identifier>`，**不会**可靠地加 `--from ... vibelawyer-mcp`。
3. `server.json`：顶层 `version` 与 `packages[0].version` 同步；**不要**再加会把入口弄乱的 `packageArguments`（当前形态仅 `runtimeHint: uvx` + `identifier: vibelawyer`）。
4. `README.md` 顶部保留所有权标记（Registry 强制）：
   ```html
   <!-- mcp-name: io.github.Jack-mi/vibelawyer -->
   ```
   缺了会：`ownership validation failed ... must appear as mcp-name ... in the package README`。
5. 文档里的安装示例与 `LAUNCHGUIDE.md` 保持 `uvx vibelawyer`。
6. `git commit` + `git push origin main`。

---

## Step 1 — 构建并发布 PyPI

凭证：项目根目录 `.env`（已 gitignore）：

```bash
UV_PUBLISH_TOKEN=pypi-...
PYPI_API_TOKEN=pypi-...
```

```bash
cd /path/to/vibelawyer
rm -rf dist
uv build

# 校验 wheel：版本、Pillow 下限、mcp-name、入口
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile
wh = next(Path('dist').glob('*.whl'))
meta = ZipFile(wh).read([n for n in ZipFile(wh).namelist() if n.endswith('METADATA')][0]).decode()
assert '<!-- mcp-name: io.github.Jack-mi/vibelawyer -->' in meta
print([ln for ln in meta.splitlines() if ln.startswith(('Name:', 'Version:')) or ln.lower().startswith('requires-dist: pillow')])
print(ZipFile(wh).read([n for n in ZipFile(wh).namelist() if n.endswith('entry_points.txt')][0]).decode())
PY

set -a && source .env && set +a
uv publish --token "$UV_PUBLISH_TOKEN"

# 确认
curl -sL "https://pypi.org/pypi/vibelawyer/x.y.z/json" | python3 -c \
  "import sys,json;d=json.load(sys.stdin);print(d['info']['version'], d['info']['requires_dist'])"
```

注意：PyPI **不能覆盖**同版本。若已上传但缺 `mcp-name`，只能再 bump（例如当时 `0.1.2` → `0.1.3`）。

---

## Step 2 — 官方 MCP Registry

```bash
# 如无二进制：
curl -fsSL -o /tmp/mcp-publisher.tgz \
  "https://github.com/modelcontextprotocol/registry/releases/download/v1.8.0/mcp-publisher_Darwin_arm64.tar.gz"
tar -xzf /tmp/mcp-publisher.tgz -C /tmp mcp-publisher

/tmp/mcp-publisher validate
/tmp/mcp-publisher login github   # 设备码：https://github.com/login/device
/tmp/mcp-publisher publish
```

成功示例：`Server io.github.Jack-mi/vibelawyer version x.y.z`。

验收：

```bash
curl -sL "https://registry.modelcontextprotocol.io/v0/servers?search=vibelawyer" | python3 -m json.tool | head
```

---

## Step 3 — Marketplace 手工 listing 更新 + 重扫

Registry 导入页（`io-github-jack-mi-vibelawyer`）往往会跟着 Registry 走；**手工页 `/server/vibelawyer` 必须单独更新**，否则仍显示旧 CVE / 旧安装命令。

### 推荐：Creator UI

1. 登录 https://mcp-marketplace.io/dashboard（GitHub）。
2. 打开编辑页：  
   https://mcp-marketplace.io/dashboard/edit/a2f9b266-61cc-45f4-9038-d400a43673c5
3. 确认 / 填写：
   - **Name**: `VibeLawyer`
   - **Version**: 与本次 PyPI 一致（如 `0.1.3`）
   - **PyPI package**: `vibelawyer`（不可空；空则难跟包版本联动）
   - **GitHub URL**: `https://github.com/Jack-mi/vibelawyer`
   - **Changelog**: 简述本次修复
4. 勾选 **Request re-scan**（或等价选项）。
5. **Save Changes**。状态可能短暂变为 `scanning`，公开页可能短暂 404；完成后应为 `approved`。

### 备选：Server Action API（自动化）

编辑页前端调用 Next.js Server Action：

- Action 名：`updateServer`
- Action ID（以线上 bundle 为准，若 404/失败则重新从  
  `/_next/static/chunks/*` 搜 `createServerReference(... "updateServer")`）：  
  `6089d075116d806bca8a4349e9973b0164493dcae5`
- `POST https://mcp-marketplace.io/dashboard/edit/<serverId>`
- Headers：
  - `Next-Action: <actionId>`
  - `Content-Type: text/plain;charset=UTF-8`
  - `Accept: text/x-component`
  - `Cookie`: 浏览器登录态（Supabase `sb-virupvwhtkpkjsiskckg-auth-token.*`）
- Body（JSON 数组）：`[<serverId>, { ...fields, "request_rescan": true }]`

关键字段示例：

```json
{
  "name": "VibeLawyer",
  "tagline": "本地 MCP：刑事案件卷宗阅卷，生成 Word 阅卷笔录与 Excel 目录；PDF 不出本机。",
  "description": "……",
  "github_url": "https://github.com/Jack-mi/vibelawyer",
  "npm_package": "",
  "pypi_package": "vibelawyer",
  "category_id": 3,
  "price_cents": 0,
  "pricing_type": "free",
  "use_cases": ["刑事案件阅卷", "卷宗梳理", "证据索引", "阅卷笔录生成", "本地隐私处理"],
  "tags": ["legal", "criminal-law", "dossier", "mcp", "local", "chinese", "productivity"],
  "documentation_url": "https://github.com/Jack-mi/vibelawyer",
  "health_check_url": "",
  "remote_url": "",
  "hide_source_code": false,
  "version": "0.1.3",
  "changelog": "……",
  "setup_requirements": [],
  "getting_started": [
    "帮我对 ./data 目录下的卷宗做全流程阅卷，导出 Word 笔录和 Excel 目录",
    "先 create_case，再 list_volumes，读取起诉书所在页"
  ],
  "request_rescan": true
}
```

成功响应片段：`{"success":true,"rescan":true}`（或 metadata-only 时 `rescan:false`）。

**坑**：字段解析错误会把 `name` 等写成垃圾值（曾误写成 `Next.MetadataOutlet`）。自动化时务必写死/校验 `name`、`tagline`、`description` 后再 POST；坏了立刻再调一次 `updateServer` 修回去（可先不重扫）。

---

## Step 4 — 验收清单

- [ ] PyPI：`https://pypi.org/pypi/vibelawyer/<ver>/json` 依赖正确；README 含 `mcp-name`
- [ ] Registry：最新 version；packages 无错误 `packageArguments`
- [ ] 冒烟：`uvx --from "vibelawyer==<ver>" python -c "import PIL; print(PIL.__version__)"`（CVE 相关依赖版本正确）
- [ ] 入口：`uvx vibelawyer` 起的是 FastMCP，不是 CLI
- [ ] 手工页 https://mcp-marketplace.io/server/vibelawyer ：
  - Version = 新版本
  - Security **高分 / Low Risk**
  - **无** ACTION REQUIRED / 无旧 Pillow CVE finding
  - 安装命令含 `uvx vibelawyer==<ver>`（或等价）
- [ ] Registry 导入页 https://mcp-marketplace.io/server/io-github-jack-mi-vibelawyer 同步新版本

搜索 API 抽查：

```bash
curl -sL 'https://mcp-marketplace.io/api/registry/search?q=vibelawyer' | python3 -m json.tool
```

---

## 常见故障

| 现象 | 原因 | 处理 |
|------|------|------|
| Registry 400：version not found on PyPI | 尚未 publish 或 CDN 延迟 | 先发 PyPI，稍等重试 |
| Registry 400：缺少 `mcp-name` | README 标记未打进该版本 | bump 版本，补标记后重发 |
| marketplace 安装成 `uvx vibelawyer` 却进 CLI | 主入口指错 `run:main` | 主脚本改 `mcp_server:main` |
| `/server/vibelawyer` 仍旧 CVE | 只发了 Registry，没更新手工 listing | Step 3 编辑 + Request re-scan |
| 公开页短暂 404 | `status=scanning` | 等扫描结束；Dashboard 看状态 |
| `uv publish` 缺凭证 | 无 token | `.env` 配 `UV_PUBLISH_TOKEN`（勿提交） |

---

## 安全注意

- `.env` 只存本地，已在 `.gitignore`；token 若曾在终端明文出现，去 PyPI **轮换**。
- 不要把 Supabase / marketplace Cookie、PyPI token 写进仓库或本手册正文。
- 自动化改 listing 时用浏览器登录态即可，不要存 service role key。
