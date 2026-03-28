#!/usr/bin/env python3
"""
会议时间戳生成工具
用法：python3 meeting_timestamp.py "2026-03-24 18:20" "2026-03-24 19:20"
输出：start_time 和 end_time 的秒级时间戳（北京时间 Asia/Shanghai）
"""
import sys
from datetime import datetime, timezone, timedelta

BJ_TZ = timezone(timedelta(hours=8))

def parse_time(time_str):
    """解析时间字符串，支持多种格式"""
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%m-%d %H:%M",
        "%m/%d %H:%M",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str.strip(), fmt)
            # 如果没有年份，用当前年份
            if dt.year == 1900:
                now = datetime.now(BJ_TZ)
                dt = dt.replace(year=now.year)
            dt = dt.replace(tzinfo=BJ_TZ)
            return dt
        except ValueError:
            continue
    return None

def main():
    if len(sys.argv) < 3:
        print("用法: python3 meeting_timestamp.py <开始时间> <结束时间>")
        print("示例: python3 meeting_timestamp.py '2026-03-24 18:20' '2026-03-24 19:20'")
        print("示例: python3 meeting_timestamp.py '03-24 18:20' '03-24 19:20'")
        sys.exit(1)

    start_str = sys.argv[1]
    end_str = sys.argv[2]

    start_dt = parse_time(start_str)
    end_dt = parse_time(end_str)

    if not start_dt:
        print(f"错误: 无法解析开始时间 '{start_str}'")
        sys.exit(1)
    if not end_dt:
        print(f"错误: 无法解析结束时间 '{end_str}'")
        sys.exit(1)

    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    # 校验：回显北京时间
    start_check = datetime.fromtimestamp(start_ts, tz=BJ_TZ)
    end_check = datetime.fromtimestamp(end_ts, tz=BJ_TZ)

    print(f"start_time={start_ts}")
    print(f"end_time={end_ts}")
    print(f"校验: {start_check.strftime('%Y-%m-%d %H:%M')} ~ {end_check.strftime('%Y-%m-%d %H:%M')} (北京时间)")

if __name__ == "__main__":
    main()
