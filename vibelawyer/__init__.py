"""vibelawyer —— 通用化刑事案件阅卷 Agent 系统.

基于 Claude Agent SDK Python 构建。给定一个存放卷宗 PDF 的目录，
主 agent 编排若干专职子 agent 完成阅卷笔录（Word）与阅卷目录（Excel），
所有事实/证据引用均可回溯到具体卷宗与页码。

用法:
    python -m vibelawyer.run --case-dir ./data --output-dir ./output
"""

__version__ = "0.1.0"
