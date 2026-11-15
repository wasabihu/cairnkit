# V2EX 首发草稿（v0.7.0）

状态：待确认，未发布。建议节点：[分享创造](https://www.v2ex.com/go/create)。

## 标题

开源 cairnkit v0.7.0：给业务后端用的轻量 Python Agent 运行层，带完整审批、SSE 与零调用记忆示例

## 正文

做业务系统里的 AI 助手时，我比较在意两件事：**谁在操作**，以及**模型提出的修改何时真正落库**。

我把这部分运行层整理成了 cairnkit（MIT 开源，目前 `v0.7.0` 已上 PyPI）。它是一个小型 Python 3.12+ 库，核心只依赖标准库和 `httpx`，适合已经有登录、角色权限和数据库的后端系统把工具调用、记忆与上下文管理接进去，不绑定 Web 框架或数据库。

仓库：https://github.com/wasabihu/cairnkit

仓库里准备了几个可直接离线跑通的示例（均使用 `ScriptedModel` 和虚构数据，不需要 API key）：

```bash
pip install cairnkit
# 或者克隆仓库直接运行示例：
git clone https://github.com/wasabihu/cairnkit.git
cd cairnkit
uv run python examples/approval.py          # 终端交互式批准 / 拒绝账单邮箱修改草稿
uv run python examples/web_approval.py      # 纯标准库 ASGI + SQLite + SSE 流式提议 + 403/409 乐观锁校验
uv run python examples/zero_call_memory.py  # 零模型调用写入筛选、序数分层、不删原表归档投影与真超限合并
```

具体分工是：应用通过 `ToolContext` 注入当前用户与记录范围，工具注册表按角色过滤并在执行前复核；`read / propose / write` 声明工具用途，审批队列与数据库事务由应用自己实现，不是加一个标签就自动完成安全控制。

记忆方面也尽量省 Token：常规写入先做注入扫描和无损预整理（零模型调用），长时记忆按序数分层并通过 `project_archive` 投影工作视图，保留规范原表不删数据；只有在真正超出字符上限时才由 `consolidate_memory` 做最多 3 轮有界合并提案。另有一个需要联网的联动示例 `examples/verify_citations.py`，演示交给人审核前先调用 [claimcite](https://github.com/wasabihu/claimcite) 核对草稿里的文献引用。

也说明来源：不少运行机制移植自 Hermes Agent v0.23.0（MIT，Nous Research）。仓库保留了逐文件来源、MIT 声明与移植对照表（`docs/hermes-porting.md`）；项目与 Nous Research 没有隶属或背书关系。示例中的 `ScriptedModel` 展示的是宿主接入边界，不是大模型评测。

想听听已经把 AI 接进现有业务系统的同行反馈：示例是否容易跑通？你们的人工审核和事务边界通常会卡在哪一步？遇到问题欢迎带最小复现提 Issue。
