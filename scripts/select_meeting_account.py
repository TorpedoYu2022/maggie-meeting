#!/usr/bin/env python3
"""
腾讯会议账号选号脚本
- 输入：目标时间段（start_time, end_time）
- 输出：返回第一个空闲的账号，或提示全部冲突
- Maggie 约会议前必须调用此脚本！

用法：
  python3 select_account.py <start_timestamp> <end_timestamp>
  
返回格式（JSON）：
  {"ok": true, "account": {"name": "个人账号1", "token": "xxx"}, "message": ""}
  {"ok": false, "account": null, "message": "所有账号在该时间段均有会议"}
"""

import json
import sys
import requests
from datetime import datetime

MCP_BASE_URL = "https://mcp.meeting.tencent.com/mcp/wemeet-open/v1"
MCP_VERSION = "v1.0.5"

MEETING_ACCOUNTS = [
    {"name": "个人账号1", "token": "37vIRdmuPIcWROkOXPe0X48BtSfDdMUbadEMqgfu7nHfsCYV"},
    {"name": "个人账号2", "token": "z5hv6bQgMH5q6S7fjZfzAgkVz7oW3PEwvRzn4OK5Q5G7dNnI"},
    {"name": "企业账号（40分钟限制）", "token": "IsE7g5h4Ud7l1HbLPnWKKS3CLyPL05YYZbRIaAQ7WD2iPKfa"},
]


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
            return None
        body = parsed.get('body', '{}')
        if isinstance(body, str):
            return json.loads(body)
        return body
    except Exception as e:
        return None


def get_account_meetings(token):
    """获取账号下所有已预约的会议（包括未来和正在进行）"""
    all_meetings = []
    page = 1
    while True:
        data = call_mcp('get_user_meetings', {"page_size": 50, "page_number": page}, token)
        if not data:
            break
        meetings = data.get('meeting_info_list', [])
        if not meetings:
            break
        all_meetings.extend(meetings)
        remaining = data.get('remaining', 0)
        if remaining <= 0:
            break
        page += 1
    return all_meetings


def has_conflict(new_start, new_end, existing_start, existing_end):
    """判断两个时间段是否重叠"""
    return new_start < existing_end and new_end > existing_start


def format_time(ts):
    return datetime.fromtimestamp(int(ts)).strftime('%H:%M')


def select_account(new_start, new_end):
    """选择空闲账号"""
    conflicts = []  # 记录所有冲突信息
    
    for account in MEETING_ACCOUNTS:
        meetings = get_account_meetings(account['token'])
        
        if meetings is None:
            # API 调用失败，跳过这个账号
            conflicts.append(f"  {account['name']}: ⚠️ 查询失败")
            continue
        
        # 过滤掉已结束的会议（只看未来的）
        now_ts = int(datetime.now().timestamp())
        upcoming = [m for m in meetings if int(m.get('end_time', 0)) > now_ts]
        
        # 检查冲突
        conflict_found = False
        for m in upcoming:
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
            is_40min_limited = '40分钟' in account['name']
            message = f"使用【{account['name']}】"
            if is_40min_limited:
                duration = new_end - new_start
                if duration > 2400:  # 40分钟 = 2400秒
                    conflicts.append(f"  {account['name']}: ❌ 时长超过40分钟限制")
                    continue
                message += "（⚠️ 40分钟限制）"
            
            return {
                "ok": True,
                "account": {"name": account["name"], "token": account["token"]},
                "message": message
            }
    
    return {
        "ok": False,
        "account": None,
        "message": "所有账号在该时间段均有会议冲突：\n" + "\n".join(conflicts)
    }


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(json.dumps({"ok": False, "account": None, "message": "用法: python3 select_account.py <start_timestamp> <end_timestamp>"}, ensure_ascii=False))
        sys.exit(1)
    
    new_start = int(sys.argv[1])
    new_end = int(sys.argv[2])
    
    result = select_account(new_start, new_end)
    print(json.dumps(result, ensure_ascii=False))
    
    if not result["ok"]:
        sys.exit(2)
