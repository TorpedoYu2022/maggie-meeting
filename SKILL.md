---
name: maggie-meeting
description: "腾讯会议全流程管理技能。约会议（多账号冲突检测+自动选号）、会议纪要（SPCA/标准格式）、Salesforce表单自动提交、邮件通知。当用户需要：创建会议、预约会议、取消会议、查询会议、会议纪要、智能纪要、SPCA纪要、发邮件通知、Salesforce CSM__c写入、客户会议表单时使用此技能。"
---

# Maggie 会议管理 Skill

腾讯会议全流程自动化：约会议 → 冲突检测 → 纪要生成 → SF 提交。

## 快速参考

| 阶段 | 脚本/工具 | 说明 |
|------|----------|------|
| 约会议 | `scripts/maggie_book_meeting.py` | 冲突检测+选号+创建+写本地表 |
| 时间戳 | `scripts/meeting_timestamp.py` | 禁止心算，必须用脚本 |
| 选号 | `scripts/select_meeting_account.py` | 3账号选空闲 |
| 纪要 | 腾讯会议 MCP get_smart_minutes | 需要 meeting_id |
| 表单 | `scripts/maggie_csm_server.py` | 端口9090，自动写SF |

## 约会议流程

```
收到请求 → maggie_book_meeting.py
  ├── 查本地表（maggie_meetings.json）
  ├── 调 API 查 3 个账号真实会议
  ├── 合并去重
  ├── 选空闲账号（全部冲突→报错）
  ├── schedule_meeting 创建
  ├── 写本地表
  └── 回显：📅 时间 + 主题 + 会议号 + 入会链接
```

**3个账号：**
| 账号 | Token | 限制 |
|------|-------|------|
| 账号1（个人1） | `37vIRdmuPIcWROkOXPe0X48BtSfDdMUbadEMqgfu7nHfsCYV` | 无 |
| 账号2（个人2） | `z5hv6bQgMH5q6S7fjZfzAgkVz7oW3PEwvRzn4OK5Q5G7dNnI` | 无 |
| 账号3（企业） | `IsE7g5h4Ud7l1HbLPnWKKS3CLyPL05YYZbRIaAQ7WD2iPKfa` | 40分钟 |

**必传参数：** time_zone: "Asia/Shanghai"

## 会议纪要

**客户会议用 SPCA：**
- S（背景）→ P（痛点）→ C（共识）→ A（行动）

**内部会议用标准格式：**
- 主题、参会人、讨论内容、决议、行动项

**⚠️ 两套ID千万别搞混：**
- meeting_code（9位数，给人用）
- meeting_id（长数字，API查数据用）

**查纪要正确步骤：**
1. get_user_ended_meetings → 匹配 meeting_code → 取 meeting_id
2. start_time 往前推24小时，end_time 往后推1小时
3. 用 meeting_id 查 get_smart_minutes

## Salesforce 表单

表单服务：`maggie_csm_server.py`（端口 9090）

**流程：** 生成 token → 预填链接 → 发邮件 → 预约人提交 → 自动写 SF CSM__c

**字段映射见** `references/maggie-skill-summary.md`

## 邮件配置

- SMTP_SSL: smtp.qiye.163.com:465
- 发件人: yulei@scrmtech.com
- 所有纪要抄送 T Sir

## 回复模板

**约会议成功：**
```
📅 2026年3月25日 10:00-11:00（60分钟）
主题：微软客户会议
会议号：123456789
入会链接：https://meeting.tencent.com/dm/xxx
```

**冲突：** 一句话说明，不超过2行。

**转写为空：** "转写正在生成中，稍后会自动发送纪要到您的邮箱。"
