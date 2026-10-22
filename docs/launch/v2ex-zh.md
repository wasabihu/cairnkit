# V2EX 首发草稿

状态：待确认，未发布。建议节点：[分享创造](https://www.v2ex.com/go/create)。

## 标题

开源 cairnkit：给业务系统用的 Python 智能体运行层，附完整审批示例

## 正文

做业务系统里的 AI 助手时，我比较在意一件事：模型提出了修改，谁决定这次修改真的写进系统？

我把相关运行层整理成了 cairnkit。它是一个小型 Python 库，适合已经有登录、权限和数据存储的应用，把工具调用、记忆和上下文管理接进去。

仓库：https://github.com/wasabihu/cairnkit

准备了一个可以自己跑的虚构工单示例：

1. 工单要求修改账单邮箱。
2. 智能体读取工单，生成待审核草稿，原邮箱不变。
3. 终端提示审核人选择批准或拒绝。
4. 批准后由应用保存；拒绝则保持原记录。

```bash
git clone https://github.com/wasabihu/cairnkit.git
cd cairnkit
uv run python examples/approval.py
```

需要 Python 3.12+ 和 uv。这个例子使用离线 ScriptedModel，不需要 API key，也不会请求真实模型。

具体分工是：应用通过 `ToolContext` 提供身份和记录范围，工具注册表按角色决定哪些工具可用。`read / propose / write` 表达工具用途，审批队列和最终写入由应用实现，不是加一个标签就自动完成安全控制。

核心依赖只有标准库和 httpx；另外有工具循环、技能、历史检索、记忆编辑计划、上下文压缩，以及可选的文档读取模块。没有绑定 Web 框架或数据库。

也说明来源：不少运行机制移植自 Hermes Agent v0.22.2（MIT，Nous Research）。仓库保留了署名、文件来源和移植对照表；项目和 Nous Research 没有隶属或背书关系。

目前还是早期版本，暂无 PyPI 发布，也没有做过可用于比较的性能或安全基准。想先请真正需要把 AI 接进现有系统的人试试：示例是否容易跑通？你们的人工审核通常会放在哪一步？如果遇到问题，可以带一个最小例子提 Issue。
