---
name: answer-first-preference
description: 用户提问时直接给结论/表格即可，不要为了“更稳”继续跑探测或做多余操作
metadata:
  node_type: memory
  type: feedback
  originSessionId: session_1707fbe19c06638ca85d347c9dc416d6
---

2026-10-19：排查 OpenCode Go “关思考”参数时，用户中途打断并说「没事了，我解决了，你只需要告诉我现在的模型表，价格 模型 速度都是怎么样的」。

**Why**：用户要的是结论本身；长时间后台探测/反复验证会让他干等，而问题往往他自己已经解决。

**How to apply**：信息够回答就直接答，能一张表给完就一张表给完；想再跑验证前先确认它会不会改变答案。用户说“只需要告诉我 X”时，只给 X，不要附带新的排查动作或额外产出。相关：[[zcode-ui-ordering-preferences]]。
