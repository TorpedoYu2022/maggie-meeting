---
name: maggie-meeting
description: "腾讯会议全流程管理技能。约会议（多账号冲突检测+自动选号）、会议纪要（SPCA/标准格式）、Salesforce表单自动提交、邮件通知。适用于企业微信/飞书等消息通道的会议预约agent。触发词：约会议、预约会议、创建会议、取消会议、会议纪要、SPCA纪要、Salesforce CSM、客户会议表单。"
---

# Maggie 会议管理 Skill

腾讯会议全流程自动化：约会议 → 冲突检测 → 纪要生成 → SF 提交。

## 架构

```
用户 → Agent → maggie_book_meeting.py → 冲突检测 → 选号 → 创建会议
                                                                    ↓
会结束 → 获取纪要 → 整理SPCA → 发邮件 → 预约人确认 → 自动写SF CSM__c
```

## 文件说明

| 文件 | 功能 |
|------|------|
| `scripts/maggie_book_meeting.py` | 约会议主脚本（冲突检测+选号+创建+写本地表） |
| `scripts/meeting_timestamp.py` | 时间戳生成（禁止心算，必须用脚本） |
| `scripts/select_meeting_account.py` | 3账号选空闲账号 |
| `scripts/maggie_csm_server.py` | SF表单服务（端口9090） |
| `scripts/maggie_csm_form.html` | 表单前端页面 |
| `references/maggie-skill-summary.md` | 完整技能文档 |
| `scripts/.env.example` | 环境变量模板 |

## 快速开始

1. 复制 `scripts/.env.example` 为 `scripts/.env`，填入真实值
2. 安装依赖：`pip install requests flask python-dateutil`
3. 启动表单服务：`python3 scripts/maggie_csm_server.py`

## 约会议

```bash
python3 scripts/maggie_book_meeting.py \
  --subject "客户会议" \
  --start "2026-03-29 08:00" \
  --end "2026-03-29 09:00" \
  --meeting-type external \
  --requester-email "name@scrmtech.com" \
  --requester-name "名字" \
  --requester-chatid "chat_id"
```

**冲突检测流程：**
1. 查本地表 `maggie_meetings.json`
2. 调 API 查 3 个账号真实会议
3. 合并去重
4. 选空闲账号（全部冲突→报错退出）
5. 创建 → 写本地表 → 回显

**3个账号配置（.env）：**
| 账号 | 限制 |
|------|------|
| 账号1（个人1） | 无时长限制 |
| 账号2（个人2） | 无时长限制 |
| 账号3（企业） | 40分钟限制 |

**⚠️ 必传参数：** `time_zone: "Asia/Shanghai"`

## 会议纪要

**客户会议（SPCA 模型）：** S背景 → P痛点 → C共识 → A行动
**内部会议（标准格式）：** 主题、参会人、讨论内容、决议、行动项

**⚠️ 两套ID：**
- `meeting_code`（9位数，给人用）
- `meeting_id`（长数字，API查数据用）

**查纪要正确步骤：**
1. `get_user_ended_meetings` → 匹配 meeting_code → 取 meeting_id
2. start_time 往前推24小时，end_time 往后推1小时
3. 用 meeting_id 查 `get_smart_minutes`

## Salesforce 表单

流程：生成 token → 预填链接 → 发邮件 → 预约人提交 → 自动写 CSM__c

字段映射见 `references/maggie-skill-summary.md`

## 邮件配置

- SMTP_SSL: smtp.qiye.163.com:465
- 发件人: yulei@scrmtech.com
- 所有纪要抄送管理员

## 回复模板

**约会议成功：**
```
📅 2026年3月29日 08:00-09:00（60分钟）
主题：微软客户会议
会议号：123456789
入会链接：https://meeting.tencent.com/dm/xxx
```

**冲突：** 一句话说明，不超过2行。
**转写为空：** "转写正在生成中，稍后会自动发送纪要到您的邮箱。"
