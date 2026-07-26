# 阅卷 Skills（特定场景技能）

每个 skill 对应阅卷笔录的一个特定场景，由同名子 agent（`vibelawyer/agents.py`）承载执行。
技能定义了该场景的目标、提取字段、来源要求与易错点，可被主编排器复用。

| Skill | 场景 | 关键产出 |
|---|---|---|
| `locate-indictment` | 定位起诉书/起诉意见书并提取指控事实 | record_indictment + add_charged_fact |
| `extract-party` | 提取当事人基本情况（职务犯罪含任职） | record_party |
| `extract-defendant-statement` | 按指控事实整理被告人供述（讯问笔录） | record_statement(role=defendant) |
| `extract-witness-statement` | 整理证人证言（询问笔录） | record_statement(role=witness) |
| `extract-procedural-docs` | 整理从被调查至当前的程序性文书 | record_procedural_doc |
| `extract-documentary-evidence` | 整理书证（客观证据） | record_documentary_evidence |
| `build-catalog` | 编制阅卷目录（卷宗目录） | add_catalog_entry |
| `synthesize-conclusions` | 形成阅卷结论（事实/证据链/矛盾/疑点） | record_conclusions |

通用守则见 `vibelawyer/agents.py:_COMMON_RULES`（严禁幻觉、来源必标、交付物=工具调用）。
