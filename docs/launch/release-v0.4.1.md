# cairnkit v0.4.1 — text decoding fix

cairnkit is a small Python agent runtime for business applications. The host supplies
identity, tool permissions and storage. Proposal tools and a host-controlled review step
let a person decide which changes to save.

## In this version

The optional document reader now handles GBK / GB18030 text and Markdown from older
Windows tools correctly, with a warning identifying the decoding used. Western legacy
text handling is unchanged.

If you are coming from v0.3, v0.4 also adds usage hooks for delegated runs and generated
titles, and exposes context-compression usage. See the [changelog](https://github.com/wasabihu/cairnkit/blob/v0.4.1/CHANGELOG.md).

## Install

Python 3.12 or newer. Not on PyPI yet; pin the GitHub tag:

```bash
uv add "cairnkit @ git+https://github.com/wasabihu/cairnkit@v0.4.1"
# Optional document readers:
uv add "cairnkit[documents] @ git+https://github.com/wasabihu/cairnkit@v0.4.1"
```

## Try the approval workflow

The [expanded example on main](https://github.com/wasabihu/cairnkit/blob/main/docs/approval-demo.md)
reads a fictional support ticket, proposes an invoice-email change, and lets a human
approve or reject it. The [35-second walkthrough](https://github.com/wasabihu/cairnkit/blob/main/docs/assets/cairnkit-approval-demo.mp4)
replays states exported from that example.

This expanded demo is a documentation update on main after the v0.4.1 tag. It uses
`ScriptedModel`, fictional data and an in-memory host store; no API key is needed.
The host implements approval and persistence. An access label alone does not enforce review.

cairnkit is early-stage software. No performance, cost or security guarantees are implied.
Bug reports with small offline reproductions are welcome in [Issues](https://github.com/wasabihu/cairnkit/issues).

MIT licensed. Many runtime mechanisms are ported from Hermes Agent v0.22.2 (MIT, Nous Research).
See [NOTICE.md](https://github.com/wasabihu/cairnkit/blob/v0.4.1/NOTICE.md).
Not affiliated with or endorsed by Nous Research.
