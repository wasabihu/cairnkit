# cairnkit 首发素材包

本包用于 GitHub 首发，包含完整演示、Release 说明和可下载素材。X、V2EX 与 Show HN 文案仍为草稿，尚未在对应平台发布。

## 这次讲什么

一句话：**给业务系统接入 AI 的小型运行层，身份、权限和最终写入由应用掌握。**

面向已经有 Python 后端、用户和数据库的开发者。用“修改账单邮箱”的虚构工单展示接入方式；不涉及任何实际使用方的信息。

## 成品入口

| 素材 | 文件 | 使用方式 |
| --- | --- | --- |
| 35 秒英文演示 | [MP4](../assets/cairnkit-approval-demo.mp4) | X 首帖附件、GitHub Release 附件 |
| README 动图 | [GIF](../assets/approval-demo.gif) | 已接入中英文 README |
| 静态预览 | [PNG](../assets/approval-poster.png) | 展示“草稿存在但原记录未改” |
| 中文字幕 | [SRT](demo.zh-CN.srt) | 与 MP4 同步，方便中文讲解 |
| 可运行示例 | [approval.py](../../examples/approval.py) | 终端输入 approve / reject |
| 分步回放 | [index.html](../../examples/approval-demo/index.html) | 本地打开或用静态服务器查看 |
| Release 正文 | [v0.4.1](release-v0.4.1.md) | 发布在已有 v0.4.1 标签上 |
| X 英文 | [两条串帖](x-en.md) | 第一条配视频，第二条说明来源和边界 |
| X 中文 | [两条串帖](x-zh.md) | 中文受众版本，避免同一天重复刷屏 |
| V2EX | [标题和正文](v2ex-zh.md) | 分享创造节点；发前查看节点当前规则 |
| Show HN | [标题和首评](show-hn-en.md) | 例子和素材公开后再发，发布者需能回应问题 |

## 建议顺序

1. 确认本包；将示例、测试、README 和素材提交并推送到 main。
2. 为已有 v0.4.1 标签创建 GitHub Release。不要移动旧标签。新演示是 main 上的文档更新，Release 已明确区分。
3. 发一组 X 首帖和一篇 V2EX，观察安装和示例的真实反馈。
4. 解决首批问题后再做 Show HN。优先记录成功跑通、具体反馈和 Issue；Star 仅作辅助指标。

以上为发布步骤；实际发布结果见本文件末尾的发布记录。

## 素材的真实性边界

- 使用真实 cairnkit 工具循环和实际导出的状态快照。
- `ScriptedModel` 使用预设响应；不是实时 LLM 演示或模型效果评测。
- 视频中的批准选择由 `--decision approve` 模拟。终端交互模式允许人实际选择批准或拒绝。
- 记录在进程内存里，不是数据库；生产应用需要自己的认证、权限和事务。
- 不宣称“绝对安全”“更快”“更省钱”或兼容所有模型。
- 保留 Hermes Agent / Nous Research / MIT 来源，未暗示官方关联。

## 复现

```bash
uv sync --locked --all-extras
uv run python examples/approval.py --decision approve --export examples/approval-demo/trace.js
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
python3 -m http.server 8768 --bind 127.0.0.1 --directory examples/approval-demo
```

截图五个阶段，命名为 `frame-01.png` 至 `frame-05.png`，放到同一个目录，再用已安装的 ffmpeg 生成媒体：

```bash
python3 scripts/render_approval_video.py --frames .run/launch-capture
```

## 本次验证（2026-10-22）

- 基于 main `9935982` / cairnkit v0.4.1；此次仅修改示例、测试、文档和宣传素材，未改运行层 API。
- 独立环境按 `uv sync --locked --all-extras` 安装，锁文件未改。
- `uv run pytest -q`：112 项通过，包括提议不写入、批准与拒绝、角色与范围限制、旧版本冲突、模型不能审批，以及终端无输入/无效输入时默认拒绝。
- `uv run ruff check .` 和 `uv run ruff format --check .`：通过。
- 浏览器实际点击全部阶段，确认批准前版本为 1、邮箱未变，批准后版本为 2、邮箱更新；35 秒自动回放结束时停止。
- 390px 窄屏无水平溢出；桌面 1470px；浏览器未记录错误或警告。
- MP4：H.264，1470 × 910，30 fps，35.000 秒，约 826 KB；GIF 约 491 KB；PNG 约 88 KB。已抽看视频中段。
- Markdown 本地链接无缺失；生成素材中只含虚构工单及公开项目信息。
- GitHub 远端 main 与起始提交相同，已有 v0.4.1 标签。公开 Releases 页面当时尚无 Release；本次只准备发布说明。

## 渠道参考

- [Show HN 官方说明](https://news.ycombinator.com/showhn.html)：提供能实际尝试的作品，解释动机，发布后参与讨论；不要组织投票。
- [V2EX 帮助](https://www.v2ex.com/help)：帖子按节点组织，支持 Markdown。使用创造者自己的说明和可运行例子。

这些规则在 2026-10-22 查询；实际发布时仍以站点当前规则为准。
