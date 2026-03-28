#!/usr/bin/env python3
"""
Maggie 一键创建会议脚本
合并：选号 + 创建 + 回显 + 注册，一个脚本搞定！

用法：
  python3 maggie_book_meeting.py \
    --subject "联想客户会议" \
    --start "2026-03-26 22:00" \
    --end "2026-03-26 23:00" \
    --meeting-type external \
    --requester-email "yulei@scrmtech.com" \
    --requester-name "于雷" \
    --requester-chatid "ou_xxx" \
    --attendees "张三,李四"

返回 JSON：
{
  "ok": true,
  "display": "完整回显文本（直接发给用户）",
  "meeting_code": "123456789",
  "join_url": "https://..."
}
或：
{
  "ok": false,
  "message": "所有账号冲突：..."
}
"""

import json
import sys
import argparse
import requests
from datetime import datetime
from pathlib import Path

MCP_BASE_URL = "https://mcp.meeting.tencent.com/mcp/wemeet-open/v1"
MCP_VERSION = "v1.0.5"

MEETING_ACCOUNTS = [
    {"name": "个人账号1", "token": "37vIRdmuPIcWROkOXPe0X48BtSfDdMUbadEMqgfu7nHfsCYV"},
    {"name": "个人账号2", "token": "z5hv6bQgMH5q6S7fjZfzAgkVz7oW3PEwvRzn4OK5Q5G7dNnI"},
    {"name": "企业账号（40分钟限制）", "token": "IsE7g5h4Ud7l1HbLPnWKKS3CLyPL05YYZbRIaAQ7WD2iPKfa"},
]

MEETINGS_FILE = Path('/root/.openclaw/workspace/data/maggie_meetings.json')
TIMESTAMP_SCRIPT = Path('/root/.openclaw/workspace/scripts/meeting_timestamp.py')

PINYIN_MAP = {
    "于雷": "yulei", "郑飞鹏": "zhengfeipeng", "康亮": "kangliang",
    "胡昕怡": "huxinyi", "常云": "changyun", "林盛南": "linshengnan",
    "赵金": "zhaojin", "田径": "tianjing", "方青": "fangqing",
    "赛斯": "saisi", "daijun": "daijun",
}


def name_to_pinyin(name):
    return PINYIN_MAP.get(name, name.lower().replace(" ", ""))


def call_mcp(tool, args, token):
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args}
    }
    headers = {
        "Content-Type": "application/json",
        "X-Tencent-Meeting-Token": token,
        "X-Skill-Version": MCP_VERSION,
    }
    try:
        resp = requests.post(MCP_BASE_URL, json=payload, headers=headers, timeout=15)
        result = resp.json()
        content = result.get('result', {}).get('content', [{}])[0].get('text', '')
        parsed = json.loads(content)
        status = parsed.get('status_code')
        if status != 200:
            error_body = parsed.get('body', '')
            return {"error": error_body}
        body = parsed.get('body', '{}')
        if isinstance(body, str):
            return json.loads(body)
        return body
    except Exception as e:
        return {"error": str(e)}


def get_account_meetings(token):
    """从腾讯会议 API 获取账号的会议列表"""
    all_meetings = []
    page = 1
    while True:
        data = call_mcp('get_user_meetings', {"page_size": 50, "page_number": page}, token)
        if not data or 'error' in data:
            return None  # 明确返回 None 表示 API 失败
        meetings = data.get('meeting_info_list', [])
        if not meetings:
            break
        all_meetings.extend(meetings)
        remaining = data.get('remaining', 0)
        if remaining <= 0:
            break
        page += 1
    return all_meetings


def get_local_meetings(token_prefix):
    """从本地 maggie_meetings.json 查询某个账号的会议（兜底）"""
    try:
        with open(MEETINGS_FILE, 'r') as f:
            data = json.load(f)
        meetings = data.get('meetings', [])
        now_ts = int(datetime.now().timestamp())
        return [
            m for m in meetings
            if m.get('account_token', '').startswith(token_prefix)
            and int(m.get('end_time', 0)) > now_ts
        ]
    except Exception:
        return []


def has_conflict(new_start, new_end, existing_start, existing_end):
    return new_start < existing_end and new_end > existing_start


def format_time(ts):
    return datetime.fromtimestamp(int(ts)).strftime('%H:%M')


def merge_meetings(api_meetings, local_meetings):
    """合并 API 和本地数据，按 start_time 去重"""
    seen = set()
    merged = []
    for m in api_meetings + local_meetings:
        key = (int(m.get('start_time', 0)), int(m.get('end_time', 0)), m.get('subject', ''))
        if key not in seen:
            seen.add(key)
            merged.append(m)
    return merged


def select_account(new_start, new_end):
    """选择空闲账号（双重检测：API + 本地表）"""
    conflicts = []
    api_ok = False  # 至少一个账号 API 查询成功

    for account in MEETING_ACCOUNTS:
        # 1. API 查询
        api_meetings = get_account_meetings(account['token'])

        if api_meetings is None:
            # API 失败 → 用本地表兜底
            token_prefix = account['token'][:10]
            local_meetings = get_local_meetings(token_prefix)
            if not local_meetings:
                # API 和本地都查不到 → 报错不跳过
                conflicts.append(f"  {account['name']}: ❌ API 查询失败且本地无记录，无法确认是否空闲")
                continue
            conflicts.append(f"  {account['name']}: ⚠️ API 查询失败，使用本地记录兜底")
            meetings = local_meetings
        else:
            api_ok = True
            # 2. 本地表兜底
            token_prefix = account['token'][:10]
            local_meetings = get_local_meetings(token_prefix)
            # 3. 合并去重
            meetings = merge_meetings(api_meetings, local_meetings)

        # 4. 检查冲突
        conflict_found = False
        for m in meetings:
            m_start = int(m.get('start_time', 0))
            m_end = int(m.get('end_time', 0))
            if has_conflict(new_start, new_end, m_start, m_end):
                conflict_found = True
                m_subject = m.get('subject', '未知会议')
                m_code = m.get('meeting_code', '')
                conflicts.append(
                    f"  {account['name']}: ❌ 与【{m_subject}】({m_code}) "
                    f"{format_time(m_start)}-{format_time(m_end)} 冲突"
                )
                break

        if not conflict_found:
            # 5. 检查企业账号40分钟限制
            is_limited = '40分钟' in account['name']
            if is_limited:
                duration = new_end - new_start
                if duration > 2400:
                    conflicts.append(f"  {account['name']}: ❌ 时长超过40分钟限制")
                    continue
            return {"ok": True, "account": account, "conflicts": conflicts}

    # 全部账号都有冲突或无法确认
    if not api_ok:
        return {
            "ok": False, "account": None,
            "conflicts": conflicts + [""],
            "message": "⚠️ 所有账号 API 查询均失败，建议检查腾讯会议 MCP token 是否过期"
        }

    return {"ok": False, "account": None, "conflicts": conflicts}


def get_timestamps(start_str, end_str):
    """调用 meeting_timestamp.py 获取时间戳"""
    import subprocess
    result = subprocess.run(
        ['python3', str(TIMESTAMP_SCRIPT), start_str, end_str],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, None, f"时间戳生成失败: {result.stderr}"

    lines = result.stdout.strip().split('\n')
    start_ts = end_ts = None
    time_display = ""
    for line in lines:
        if line.startswith('start_time='):
            start_ts = int(line.split('=')[1])
        elif line.startswith('end_time='):
            end_ts = int(line.split('=')[1])
        elif line.startswith('校验:'):
            time_display = line.replace('校验: ', '').split(' (北京时间)')[0]

    return start_ts, end_ts, time_display


def register_meeting(args, meeting_code, join_url, account, start_ts, end_ts, time_display):
    data = {"meetings": []}
    if MEETINGS_FILE.exists():
        with open(MEETINGS_FILE) as f:
            data = json.load(f)

    attendee_list = []
    if args.attendees:
        attendee_list = [a.strip() for a in args.attendees.split(",") if a.strip()]

    data['meetings'].append({
        "meeting_code": meeting_code,
        "meeting_id": "",
        "subject": args.subject,
        "start_time": str(start_ts),
        "end_time": str(end_ts),
        "time_display": time_display,
        "requester_email": args.requester_email,
        "requester_name": args.requester_name,
        "requester_chatid": args.requester_chatid,
        "attendees": attendee_list,
        "meeting_type": args.meeting_type,
        "account_token": account["token"],
        "account_name": account["name"],
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "auto_registered": False,
    })

    with open(MEETINGS_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--subject', required=True)
    parser.add_argument('--start', required=True, help='开始时间，如 2026-03-26 22:00')
    parser.add_argument('--end', required=True, help='结束时间，如 2026-03-26 23:00')
    parser.add_argument('--meeting-type', default='internal')
    parser.add_argument('--requester-email', default='')
    parser.add_argument('--requester-name', default='')
    parser.add_argument('--requester-chatid', default='')
    parser.add_argument('--attendees', default='')
    args = parser.parse_args()

    # Step 1: 生成时间戳
    start_ts, end_ts, time_display = get_timestamps(args.start, args.end)
    if not start_ts:
        result = {"ok": False, "message": time_display}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(2)

    # Step 2: 选号
    selection = select_account(start_ts, end_ts)
    if not selection["ok"]:
        msg = "所有账号在该时间段均有会议冲突：\n" + "\n".join(selection["conflicts"])
        print(json.dumps({"ok": False, "message": msg}, ensure_ascii=False))
        sys.exit(2)

    account = selection["account"]

    # Step 3: 创建会议
    create_result = call_mcp('schedule_meeting', {
        "subject": args.subject,
        "start_time": str(start_ts),
        "end_time": str(end_ts),
        "time_zone": "Asia/Shanghai"
    }, account["token"])

    if not create_result or 'error' in create_result:
        err = create_result.get('error', '未知错误') if create_result else 'API调用失败'
        print(json.dumps({"ok": False, "message": f"创建会议失败: {err}"}, ensure_ascii=False))
        sys.exit(2)

    meeting_list = create_result.get('meeting_info_list', [])
    if not meeting_list:
        print(json.dumps({"ok": False, "message": "创建会议返回为空"}, ensure_ascii=False))
        sys.exit(2)

    info = meeting_list[0]
    meeting_code = info.get('meeting_code', '')
    join_url = info.get('join_url', '')

    # Step 4: 注册到文件
    register_meeting(args, meeting_code, join_url, account, start_ts, end_ts, time_display)

    # Step 5: 生成回显
    duration_min = (end_ts - start_ts) // 60
    lines = []
    lines.append(f"📅 {time_display}（{duration_min}分钟）")
    lines.append(f"主题：{args.subject}")
    lines.append(f"会议号：{meeting_code}")
    lines.append(f"入会链接：{join_url}")

    # 账号说明（非默认账号时显示）
    if account["name"] != "个人账号1":
        warning = f"⚠️ 已自动使用【{account['name']}】创建（默认账号时间冲突）"
        if '40分钟' in account['name']:
            warning += "（⚠️ 40分钟时长限制）"
        lines.append(warning)

    # 纪要发送人（必须有！）
    recipients = []
    if args.requester_email:
        recipients.append(args.requester_email)
    if args.attendees:
        for name in args.attendees.split(","):
            name = name.strip()
            if name:
                email = f"{name_to_pinyin(name)}@scrmtech.com"
                if email not in recipients:
                    recipients.append(email)
    recipients.append("T Sir（抄送）")
    lines.append(f"📬 纪要发送：{' + '.join(recipients)}")

    display = "\n".join(lines)
    result = {
        "ok": True,
        "display": display,
        "meeting_code": meeting_code,
        "join_url": join_url,
        "account_name": account["name"],
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
