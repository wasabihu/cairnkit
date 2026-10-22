# cairnkit

**给业务系统用的小型智能体运行层。** 谁在操作、能做什么由应用决定；模型只能提议。适合这样的网站：AI 助手要处理多人共用的真实数据（客户记录、服务笔记、知识库），而保存什么由人说了算。

cairn 是山路上堆起来的石头路标，后来的人沿着它走。cairnkit 给智能体做同样的事：审核过的记忆、可检索的历史、整理好的技能，下一次对话接着用。

[English](README.md)

## 和其它框架有什么不同

- **身份来自应用，不来自模型。** 工具从 `ToolContext` 拿到当前登录的人、他的岗位、正在处理的记录。
- **写操作变成草稿。** 工具声明访问级别（`read` / `propose` / `write`）和可用岗位；记忆修改以可审核的计划返回，不会悄悄写入。
- **有护栏的记忆。** 按原文定位的增 / 改 / 删、容量上限、注入扫描、会话内固定快照，移植自 Hermes Agent。
- **长对话也省钱。** 完整移植 Hermes 的上下文压缩：增量结构化摘要、真实 token 锚点、失败冷却、保留用户原话。
- **小。** 核心只依赖标准库和 `httpx`；不带 Web 框架、数据库或向量库，存储和权限留在你的应用里。

模块清单、接入步骤和示例见 [英文 README](README.md)，代码示例两种语言通用。

## 安装

暂未发布到 PyPI，从 GitHub 固定版本标签安装：

```bash
uv add "cairnkit @ git+https://github.com/wasabihu/cairnkit@v0.4.1"
# 需要读取 PDF / Word / Excel 时：
uv add "cairnkit[documents] @ git+https://github.com/wasabihu/cairnkit@v0.4.1"
```

需要 Python 3.12 或更新版本。

## 几条规则

- **身份不由模型决定。** 把用户和记录放进 `ToolContext`。
- **系统提示一个会话只组装一次。** 后续轮次把 `RunResult.system_prompt` 传回 `run(system_prompt=...)`，保住服务商的提示缓存。
- **会改数据的工具优先用 `access="propose"`**，由人批准。
- **离线测试**用 `ScriptedModel`，自动化测试不调用真实模型。
- **用户、文件、工具返回的文字都是数据**，不要放进系统提示。

## 和 Hermes Agent 的关系

很多机制和算法移植自 [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.22.2（MIT，Nous Research），每个移植文件头部都写明了来源。Hermes 是带文件、终端和几十个平台的个人助手；cairnkit 保留算法，替换了存储、配置和权限三层，以适配多人使用的网站。对照表见 [docs/hermes-porting.md](docs/hermes-porting.md)。cairnkit 与 Nous Research 没有隶属或背书关系。

## 版本

1.0 之前：修订号（0.3.0 → 0.3.1）只修缺陷和文档，可直接升级；次版本（0.3 → 0.4）可能需要改代码，[CHANGELOG.md](CHANGELOG.md) 会写清楚怎么改。

## 许可证

MIT，见 [LICENSE](LICENSE)；移植的 Hermes 代码保留其 MIT 声明，见 [NOTICE.md](NOTICE.md)。
