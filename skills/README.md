# 阅卷 Skills

| Skill | 场景 |
|---|---|
| [`vibelawyer-review`](vibelawyer-review/SKILL.md) | **主 Skill**：宿主 Agent + FastMCP 完成全流程阅卷（不依赖 Claude Code） |

步骤与铁律的代码源：`vibelawyer/playbook.py`（与 `start_review` 返回的 playbook 同源）。

历史场景拆分（locate-indictment / extract-* 等）已并入上述统一 Skill 的标准步骤。
