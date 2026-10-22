# X 首发草稿 — 中文

状态：待确认，未发布。第一条附 `docs/assets/cairnkit-approval-demo.mp4`，第二条作为同一串帖的补充。

## 第一条

我把一个给业务系统用的 Python 智能体运行层开源了，叫 cairnkit。

录了一个离线示例：读取工单 → 提出修改 → 等人审核 → 应用保存。AI 可以帮忙处理请求，身份、权限和最后写入仍由应用掌握。

MIT 开源：https://github.com/wasabihu/cairnkit

## 第二条

不少机制移植自 Hermes Agent，保留了 MIT 署名和来源对照。

视频使用 ScriptedModel 和虚构工单，展示应用怎么接入审批，不是实时大模型测试。审批和存储仍需由接入方实现。

如果你正在给已有系统接 AI，想听听你会在哪一步保留人工审核。
