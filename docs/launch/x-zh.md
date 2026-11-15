# X 首发草稿 — 中文（v0.7.0）

状态：待确认，未发布。第一条附 `docs/assets/cairnkit-approval-demo.mp4`，第二条作为同一串帖的补充。

## 第一条

如果你的业务系统要接 AI Agent，但不敢让模型直接改数据库，可以看看我开源的 cairnkit（v0.7.0，MIT，已上 PyPI）。

身份、权限和最终写入留在应用里，模型只通过 `propose` 提草稿，人在系统里拍板后再按乐观锁版本入库。

35 秒离线演示：
https://github.com/wasabihu/cairnkit

## 第二条

核心只依赖标准库 + httpx。新增两个可离线跑的示例：`web_approval.py`（标准库 ASGI + SQLite + SSE + 403/409 冲突拦截）和 `zero_call_memory.py`（热路径零模型调用写入筛选 + 不删原记录的归档投影）。

不少机制移植自 Hermes Agent v0.23.0（MIT，Nous Research，仓库保留来源对照，无官方隶属）；视频使用 ScriptedModel 和虚构数据演示宿主边界。`pip install cairnkit`
