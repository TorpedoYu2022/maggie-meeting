#!/usr/bin/env python3
"""
Maggie CSM 表单服务
- 托管会议纪要确认表单
- 接收表单提交，保存到本地
- ⚠️ 不直接写入 Salesforce，由 CSM-OP 执行
- 异常访问监控，通知 T Sir
"""

import json
import os
import sys
import logging
import time
import uuid
import hashlib
import requests
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# 配置
DATA_DIR = '/root/.openclaw/workspace/data/maggie_submissions'
ACCESS_LOG = '/root/.openclaw/workspace/data/maggie_access.log'
TOKEN_DIR = '/root/.openclaw/workspace/data/maggie_tokens'
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TOKEN_DIR, exist_ok=True)

# Token 过期时间：24小时
TOKEN_EXPIRY_SECONDS = 24 * 60 * 60

# 邮件配置（异常通知用）
SMTP_CONFIG = {
    'host': 'smtp.qiye.163.com',
    'port': 25,
    'user': 'yulei@scrmtech.com',
    'password': os.environ.get('EMAIL_PASSWORD', ''),
    'admin_email': 'yulei@scrmtech.com'
}

# 访问频率限制
ACCESS_TRACKER = {}  # {ip: [timestamps]}
MAX_REQUESTS_PER_5MIN = 10
RATE_LIMIT_WINDOW = 300  # 5分钟

# 服务大类选项（与 Salesforce CSM__c ActivityType__c 一致）
SERVICE_TYPES = [
    '产品梳理及培训', '例会', '活动支持', '定制沟通', '项目启动会',
    '产品更新介绍', 'B2B营销策略诊断及分享', '策略建议', 'M2L',
    '新功能更新讲解培训', '其他', '售前支持'
]

# 续约判断选项（与 Salesforce CSM__c Renewal__c 一致）
RENEWAL_OPTIONS = [
    '确定续约', '大概率续约', '小概率续约', '大概率不续约',
    '确定不续约', '暂无判断'
]

# HTML 表单模板
FORM_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>会议纪要确认 - Maggie 📅</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }
.container { max-width: 720px; margin: 0 auto; padding: 20px; }
.form-card { background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 32px; margin-bottom: 20px; }
.form-header { text-align: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #FF6B35; }
.form-header h1 { color: #1A1A2E; font-size: 24px; margin-bottom: 8px; }
.form-header p { color: #888; font-size: 14px; }
.form-header .meeting-info { background: #f0f8ff; padding: 10px 16px; border-radius: 8px; margin-top: 12px; font-size: 13px; color: #555; }
.section-title { color: #FF6B35; font-size: 18px; font-weight: bold; margin: 28px 0 16px 0; padding-left: 12px; border-left: 4px solid #FF6B35; }
.field-group { margin-bottom: 18px; }
.field-label { display: block; font-weight: 600; margin-bottom: 6px; color: #444; font-size: 14px; }
.field-label .required { color: #e74c3c; margin-left: 4px; }
.field-label .hint { color: #999; font-weight: 400; font-size: 12px; margin-left: 8px; }
input[type="text"], input[type="number"], input[type="date"], textarea, select { width: 100%; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 15px; transition: border-color 0.2s; font-family: inherit; }
input:focus, textarea:focus, select:focus { outline: none; border-color: #FF6B35; box-shadow: 0 0 0 3px rgba(255,107,53,0.1); }
textarea { resize: vertical; min-height: 80px; }
.row { display: flex; gap: 16px; }
.row .field-group { flex: 1; }
@media (max-width: 600px) { .row { flex-direction: column; gap: 0; } }
.spcacard { border: 2px solid #f0f0f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; background: #fafafa; }
.spcacard .spca-title { font-weight: bold; color: #1A1A2E; margin-bottom: 8px; font-size: 15px; }
.spcacard .spca-subtitle { color: #888; font-size: 12px; margin-bottom: 10px; }
.submit-btn { display: block; width: 100%; padding: 14px; background: #FF6B35; color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 0.2s; margin-top: 10px; }
.submit-btn:hover { background: #e55a2b; }
.submit-btn:disabled { background: #ccc; cursor: not-allowed; }
.footer { text-align: center; color: #999; font-size: 12px; margin-top: 20px; padding: 16px; }
.loading { display: none; text-align: center; padding: 40px; }
.loading .spinner { border: 3px solid #f0f0f0; border-top: 3px solid #FF6B35; border-radius: 50%; width: 30px; height: 30px; animation: spin 0.8s linear infinite; margin: 0 auto 10px; }
@keyframes spin { to { transform: rotate(360deg); } }
.success-msg { display: none; text-align: center; padding: 40px 20px; }
.success-msg .icon { font-size: 48px; margin-bottom: 16px; }
.success-msg h2 { color: #27ae60; margin-bottom: 8px; }
.success-msg p { color: #666; }
.error-msg { display: none; text-align: center; padding: 40px 20px; }
.error-msg .icon { font-size: 48px; margin-bottom: 16px; }
.error-msg h2 { color: #e74c3c; margin-bottom: 8px; }
.error-msg p { color: #666; }
</style>
</head>
<body>

<div class="container">

<div class="form-card" id="formCard">
    <div class="form-header">
        <h1>📋 会议纪要确认</h1>
        <p>请确认本次会议信息，提交后将由 CSM-OP 写入 Salesforce</p>
        <div class="meeting-info" id="meetingInfo"></div>
    </div>

    <form id="csmForm">

        <div class="section-title">📌 基本信息</div>

        <div class="field-group">
            <label class="field-label">客户<span class="required">*</span></label>
            <input type="text" id="client" name="client" required placeholder="请输入客户名称">
        </div>

        <div class="row">
            <div class="field-group">
                <label class="field-label">服务时间<span class="required">*</span></label>
                <input type="date" id="serviceDate" name="date__c" required>
            </div>
            <div class="field-group">
                <label class="field-label">拜访方式<span class="required">*</span></label>
                <select id="visitMethod" name="VisitMethod__c" required>
                    <option value="">请选择</option>
                    <option value="线上">线上</option>
                    <option value="线下">线下</option>
                </select>
            </div>
        </div>

        <div class="field-group">
            <label class="field-label">服务大类<span class="required">*</span></label>
            <select id="serviceType" name="ActivityType__c" required>
                <option value="">请选择</option>
                ''' + '\n                    '.join(f'<option value="{t}">{t}</option>' for t in SERVICE_TYPES) + '''
            </select>
        </div>

        <div class="section-title">👥 参会人</div>

        <div class="field-group">
            <label class="field-label">参会人（客户方）<span class="required">*</span></label>
            <textarea id="customerAttendees" name="attendAcount__c" required placeholder="客户方参会人员，多人用逗号分隔"></textarea>
        </div>

        <div class="field-group">
            <label class="field-label">参会人（我方）<span class="required">*</span><span class="hint">多人用英文 ; 隔开</span></label>
            <textarea id="ourAttendees" name="AttendMe__c" required placeholder="例如：常云;于雷"></textarea>
        </div>

        <div class="row">
            <div class="field-group">
                <label class="field-label">KP参与<span class="required">*</span><span class="hint">客户关键决策人是否参会</span></label>
                <select id="kpJoin" name="KP__c" required>
                    <option value="">请选择</option>
                    <option value="是">是</option>
                    <option value="否">否</option>
                </select>
            </div>
            <div class="field-group">
                <label class="field-label">是否深度服务<span class="required">*</span></label>
                <select id="deepService" name="DeepService__c" required>
                    <option value="">请选择</option>
                    <option value="是">是</option>
                    <option value="否">否</option>
                </select>
            </div>
        </div>

        <div class="section-title">⏱️ 工时</div>

        <div class="row">
            <div class="field-group">
                <label class="field-label">准备工时（小时）<span class="required">*</span></label>
                <input type="number" id="prepareTime" name="PrepareTime__c" step="0.5" min="0" required value="0">
            </div>
            <div class="field-group">
                <label class="field-label">服务工时（小时）<span class="required">*</span></label>
                <input type="number" id="effort" name="Effort__c" step="0.5" min="0" required value="0">
            </div>
        </div>

        <div class="section-title">📊 服务评估</div>

        <div class="field-group">
            <label class="field-label">续约判断<span class="required">*</span></label>
            <select id="renewal" name="Renewal__c" required>
                <option value="">请选择</option>
                ''' + '\n                    '.join(f'<option value="{t}">{t}</option>' for t in RENEWAL_OPTIONS) + '''
            </select>
        </div>

        <div class="field-group">
            <label class="field-label">服务详情</label>
            <textarea id="serviceDetail" name="ServiceDetail__c" placeholder="简要描述本次服务内容"></textarea>
        </div>

        <div class="section-title">📝 SPCA 会议纪要</div>

        <div class="spcacard">
            <div class="spca-title">🟢 S - Situation（背景）</div>
            <div class="spca-subtitle">客户背景、当前现状</div>
            <textarea id="spca_s" name="spca_s" placeholder="客户背景情况、当前使用现状..."></textarea>
        </div>

        <div class="spcacard">
            <div class="spca-title">🔴 P - Pain/Problem（痛点）</div>
            <div class="spca-subtitle">客户面临的痛点问题</div>
            <textarea id="spca_p" name="spca_p" placeholder="客户核心痛点、具体问题..."></textarea>
        </div>

        <div class="spcacard">
            <div class="spca-title">🟡 C - Consensus（共识）</div>
            <div class="spca-subtitle">双方达成的共识和不共识</div>
            <textarea id="spca_c" name="spca_c" placeholder="✅ 共识的点&#10;❌ 不共识的点（待进一步讨论）"></textarea>
        </div>

        <div class="spcacard">
            <div class="spca-title">🔵 A - Action（行动）</div>
            <div class="spca-subtitle">下一步行动项</div>
            <textarea id="spca_a" name="spca_a" placeholder="| 事项 | 负责人 | 截止时间 |&#10;|------|--------|----------|&#10;| xxx  | xxx    | xxx     |"></textarea>
        </div>

        <div class="section-title">📎 补充信息</div>

        <div class="field-group">
            <label class="field-label">客户反馈的问题</label>
            <textarea id="feedback" name="Feedback__c" placeholder="客户在会议中反馈的问题..."></textarea>
        </div>

        <div class="field-group">
            <label class="field-label">未解决事项和风险</label>
            <textarea id="risk" name="UnresolveIssueRisk__c" placeholder="需要关注的风险事项..."></textarea>
        </div>

        <button type="submit" class="submit-btn" id="submitBtn">✅ 提交确认</button>

    </form>
</div>

<div class="form-card loading" id="loading">
    <div class="spinner"></div>
    <p>正在保存...</p>
</div>

<div class="form-card success-msg" id="success">
    <div class="icon">✅</div>
    <h2>提交成功！</h2>
    <p>会议纪要已保存，CSM-OP 将写入 Salesforce。</p>
    <p style="color:#999;font-size:13px;margin-top:8px;">感谢您的确认。</p>
</div>

<div class="form-card error-msg" id="error">
    <div class="icon">❌</div>
    <h2>提交失败</h2>
    <p id="errorMsg">请稍后重试，或联系 Maggie。</p>
</div>

<div class="footer">📅 Maggie · 牛逼轰轰市场部 · CSM-OP 将写入 Salesforce</div>

</div>

<script>
const urlParams = new URLSearchParams(window.location.search);
const meetingId = urlParams.get('meeting_id') || '';
const clientName = urlParams.get('client') || '';
const meetingSubject = urlParams.get('subject') || '';
const meetingDate = urlParams.get('date') || '';
const visitMethod = urlParams.get('visit') || '';
const customerAttendees = urlParams.get('cust_attendees') || '';
const ourAttendees = urlParams.get('our_attendees') || '';
const spcaS = urlParams.get('spca_s') || '';
const spcaP = urlParams.get('spca_p') || '';
const spcaC = urlParams.get('spca_c') || '';
const spcaA = urlParams.get('spca_a') || '';

// 显示会议信息
if (meetingId || clientName) {
    let info = '';
    if (meetingSubject) info += '<strong>会议主题：</strong>' + meetingSubject;
    if (meetingId) info += (info ? ' | ' : '') + '<strong>会议号：</strong>' + meetingId;
    if (clientName) info += (info ? ' | ' : '') + '<strong>客户：</strong>' + clientName;
    if (visitMethod) info += (info ? ' | ' : '') + '<strong>方式：</strong>' + visitMethod;
    document.getElementById('meetingInfo').innerHTML = info;
}

// 预填表单（只填能确定的，含糊的不填）
function prefill(id, value) { if (value) document.getElementById(id).value = value; }
prefill('client', clientName);
prefill('serviceDate', meetingDate);
prefill('visitMethod', visitMethod);
prefill('customerAttendees', customerAttendees);
prefill('ourAttendees', ourAttendees);
prefill('spca_s', spcaS);
prefill('spca_p', spcaP);
prefill('spca_c', spcaC);
prefill('spca_a', spcaA);

// 如果有预填的日期就不覆盖，否则默认今天
if (!meetingDate) document.getElementById('serviceDate').valueAsDate = new Date();
document.getElementById('serviceDate').valueAsDate = new Date();

document.getElementById('csmForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    const submitBtn = document.getElementById('submitBtn');
    submitBtn.disabled = true;
    document.getElementById('loading').style.display = 'block';

    const formData = {
        meeting_id: meetingId,
        client: document.getElementById('client').value,
        date__c: document.getElementById('serviceDate').value,
        VisitMethod__c: document.getElementById('visitMethod').value,
        ActivityType__c: document.getElementById('serviceType').value,
        attendAcount__c: document.getElementById('customerAttendees').value,
        AttendMe__c: document.getElementById('ourAttendees').value,
        KP__c: document.getElementById('kpJoin').value,
        DeepService__c: document.getElementById('deepService').value,
        PrepareTime__c: parseFloat(document.getElementById('prepareTime').value) || 0,
        Effort__c: parseFloat(document.getElementById('effort').value) || 0,
        Renewal__c: document.getElementById('renewal').value,
        ServiceDetail__c: document.getElementById('serviceDetail').value,
        spca_s: document.getElementById('spca_s').value,
        spca_p: document.getElementById('spca_p').value,
        spca_c: document.getElementById('spca_c').value,
        spca_a: document.getElementById('spca_a').value,
        Feedback__c: document.getElementById('feedback').value,
        UnresolveIssueRisk__c: document.getElementById('risk').value
    };

    try {
        const response = await fetch('/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        if (response.ok) {
            document.getElementById('formCard').style.display = 'none';
            document.getElementById('loading').style.display = 'none';
            document.getElementById('success').style.display = 'block';
        } else {
            const err = await response.json();
            throw new Error(err.error || '提交失败');
        }
    } catch (error) {
        document.getElementById('formCard').style.display = 'none';
        document.getElementById('loading').style.display = 'none';
        document.getElementById('errorMsg').textContent = error.message;
        document.getElementById('error').style.display = 'block';
    }
});
</script>

</body>
</html>'''


# ============ 访问监控 ============

def log_access(ip, path, method='GET', extra=''):
    """记录访问日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"{timestamp} | {ip} | {method} {path} | {extra}\n"
    with open(ACCESS_LOG, 'a', encoding='utf-8') as f:
        f.write(log_line)


def check_rate_limit(ip):
    """检查访问频率，返回是否超限"""
    now = time.time()
    if ip not in ACCESS_TRACKER:
        ACCESS_TRACKER[ip] = []

    # 清理过期记录
    ACCESS_TRACKER[ip] = [t for t in ACCESS_TRACKER[ip] if now - t < RATE_LIMIT_WINDOW]

    ACCESS_TRACKER[ip].append(now)

    if len(ACCESS_TRACKER[ip]) > MAX_REQUESTS_PER_5MIN:
        return True
    return False


def check_off_hours():
    """检查是否非工作时间"""
    hour = datetime.now().hour
    return hour >= 22 or hour < 8


def send_alert_email(subject, body):
    """发送异常通知邮件给 T Sir"""
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body, 'html', 'utf-8')
        msg['From'] = SMTP_CONFIG['user']
        msg['To'] = SMTP_CONFIG['admin_email']
        msg['Subject'] = f'⚠️ Maggie 异常告警：{subject}'

        server = smtplib.SMTP(SMTP_CONFIG['host'], SMTP_CONFIG['port'])
        server.starttls()
        server.login(SMTP_CONFIG['user'], SMTP_CONFIG['password'])
        server.sendmail(SMTP_CONFIG['user'], [SMTP_CONFIG['admin_email']], msg.as_string())
        server.quit()
        logging.info(f"异常通知已发送: {subject}")
    except Exception as e:
        logging.error(f"异常通知发送失败: {e}")


def alert_off_hours_access(ip, path):
    """非工作时间访问告警"""
    send_alert_email(
        '非工作时间访问',
        f'''<h3>⚠️ 非工作时间表单访问</h3>
        <table style="border-collapse:collapse;">
        <tr><td style="padding:4px 12px;border:1px solid #ddd;font-weight:bold;">IP</td><td style="padding:4px 12px;border:1px solid #ddd;">{ip}</td></tr>
        <tr><td style="padding:4px 12px;border:1px solid #ddd;font-weight:bold;">时间</td><td style="padding:4px 12px;border:1px solid #ddd;">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</td></tr>
        <tr><td style="padding:4px 12px;border:1px solid #ddd;font-weight:bold;">页面</td><td style="padding:4px 12px;border:1px solid #ddd;">{path}</td></tr>
        </table>
        <p style="color:#999;margin-top:12px;">📅 Maggie 自动告警</p>'''
    )


def alert_rate_limit(ip, count):
    """频繁访问告警"""
    send_alert_email(
        '频繁访问',
        f'''<h3>⚠️ 表单频繁访问</h3>
        <table style="border-collapse:collapse;">
        <tr><td style="padding:4px 12px;border:1px solid #ddd;font-weight:bold;">IP</td><td style="padding:4px 12px;border:1px solid #ddd;">{ip}</td></tr>
        <tr><td style="padding:4px 12px;border:1px solid #ddd;font-weight:bold;">请求次数</td><td style="padding:4px 12px;border:1px solid #ddd;">{count} 次/5分钟</td></tr>
        <tr><td style="padding:4px 12px;border:1px solid #ddd;font-weight:bold;">时间</td><td style="padding:4px 12px;border:1px solid #ddd;">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</td></tr>
        </table>
        <p style="color:#999;margin-top:12px;">📅 Maggie 自动告警</p>'''
    )


# ============ Token 管理 ============

EXPIRED_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>链接已失效 - Maggie 📅</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f5f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
.card { background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 40px; text-align: center; max-width: 420px; }
.icon { font-size: 48px; margin-bottom: 16px; }
h2 { color: #e74c3c; margin-bottom: 8px; }
p { color: #888; font-size: 14px; line-height: 1.6; }
</style></head>
<body>
<div class="card">
<div class="icon">🔒</div>
<h2>此链接已失效</h2>
<p>表单链接已过期或已被使用。<br>如需重新获取，请联系预约人。</p>
</div>
</body></html>'''


def create_token():
    """生成唯一 token 并记录"""
    token = uuid.uuid4().hex[:16]
    token_file = os.path.join(TOKEN_DIR, f'{token}.json')
    data = {
        'created_at': datetime.now().isoformat(),
        'expires_at': (datetime.now().timestamp() + TOKEN_EXPIRY_SECONDS),
        'submitted': False
    }
    with open(token_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logging.info(f"Token 创建: {token} (24h有效)")
    return token


def validate_token(token):
    """检查 token 是否有效。返回 (valid, reason)"""
    token_file = os.path.join(TOKEN_DIR, f'{token}.json')
    if not os.path.exists(token_file):
        return False, '链接不存在'

    with open(token_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if data.get('submitted'):
        return False, '已提交'

    if time.time() > data.get('expires_at', 0):
        return False, '已过期（24h）'

    return True, 'ok'


def mark_submitted(token):
    """标记 token 为已提交"""
    token_file = os.path.join(TOKEN_DIR, f'{token}.json')
    if os.path.exists(token_file):
        with open(token_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['submitted'] = True
        data['submitted_at'] = datetime.now().isoformat()
        with open(token_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Token 已标记为已提交: {token}")


def cleanup_expired_tokens():
    """清理过期的 token 文件"""
    now = time.time()
    for filename in os.listdir(TOKEN_DIR):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(TOKEN_DIR, filename)
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            if data.get('submitted') or now > data.get('expires_at', 0):
                os.remove(filepath)
        except:
            pass

# ============ Salesforce 自动写入（CSM-OP 角色） ============

SF_CONFIG = {
    'url': 'https://zhiqu.my.salesforce.com',
    'client_id': os.environ.get('SF_CLIENT_ID', ''),
    'client_secret': os.environ.get('SF_CLIENT_SECRET', ''),
    'username': 'meetingapi@scrmtech.com',
    'password': 'SCRM20250512pQZtOgpv8a4cp7atgX8lh59VG'
}

def get_sf_token():
    """获取 Salesforce token"""
    try:
        res = requests.post(
            f"{SF_CONFIG['url']}/services/oauth2/token",
            data={
                'grant_type': 'password',
                'client_id': SF_CONFIG['client_id'],
                'client_secret': SF_CONFIG['client_secret'],
                'username': SF_CONFIG['username'],
                'password': SF_CONFIG['password']
            },
            timeout=15
        )
        return res.json().get('access_token')
    except Exception as e:
        logging.error(f"SF token 获取失败: {e}")
        return None

def trigger_csm_op_write_sf(form_data, filepath):
    """表单提交后自动写入 Salesforce（模拟 CSM-OP 操作）"""
    client_name = form_data.get('client', '')
    if not client_name:
        logging.warning("表单缺少客户名称，跳过 SF 写入")
        return {'status': 'skipped', 'reason': '缺少客户名称'}

    token = get_sf_token()
    if not token:
        logging.error("SF token 获取失败，跳过写入")
        return {'status': 'error', 'reason': 'SF token 获取失败'}

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    # 1. 查找客户 Account ID
    try:
        query = f"SELECT Id, Name, CSOwner__c, OwnerId FROM Account WHERE Name LIKE '%{client_name}%' LIMIT 3"
        acc_res = requests.get(
            f"{SF_CONFIG['url']}/services/data/v58.0/query/",
            headers=headers,
            params={'q': query},
            timeout=15
        )
        acc_data = acc_res.json()
        if isinstance(acc_data, list):
            return {'status': 'error', 'reason': f'SF查询错误: {acc_data[0].get("message", "未知错误")[:100]}'}
        accounts = acc_data.get('records', [])
        if not accounts:
            logging.warning(f"SF 未找到客户: {client_name}")
            return {'status': 'error', 'reason': f'未找到客户: {client_name}'}

        account = accounts[0]
        account_id = account['Id']
        matched_name = account['Name']
        # 自动填充 CSM 负责人（从 Account 继承）
        csm_owner = account.get('CSOwner__c')
        logging.info(f"SF 匹配客户: {matched_name} (CSOwner: {csm_owner or '未分配'})")
    except Exception as e:
        logging.error(f"SF 查询客户失败: {e}")
        return {'status': 'error', 'reason': f'查询客户失败: {e}'}

    # 2. 构建 SPCA 纪要
    spca_parts = []
    for key, label in [('spca_s', '背景'), ('spca_p', '痛点'), ('spca_c', '共识'), ('spca_a', '行动')]:
        val = form_data.get(key, '').strip()
        if val:
            spca_parts.append(f"{label}：{val}")
    spca_text = '\n\n'.join(spca_parts)

    # 3. 构建 CSM__c 记录
    # ⚠️ AttendMe__c 是 SF 受限选项列表，无效值会报错，需要跳过
    # 先查一次有效选项
    valid_attendees = set()
    try:
        describe_url = f"{SF_CONFIG['url']}/services/data/v58.0/sobjects/CSM__c/describe/"
        desc_res = requests.get(describe_url, headers=headers, timeout=15)
        for field in desc_res.json().get('fields', []):
            if field['name'] == 'AttendMe__c' and field.get('picklistValues'):
                valid_attendees = {v['value'] for v in field['picklistValues']}
                break
    except Exception:
        pass

    attend_me_value = form_data.get('AttendMe__c', '').strip()
    if valid_attendees and attend_me_value not in valid_attendees:
        logging.warning(f"AttendMe__c 值 '{attend_me_value}' 不在选项列表中，跳过")
        attend_me_value = None

    record = {
        'date__c': form_data.get('date__c'),
        'VisitMethod__c': form_data.get('VisitMethod__c'),
        'ActivityType__c': form_data.get('ActivityType__c'),
        'attendAcount__c': form_data.get('attendAcount__c'),
        'AttendMe__c': attend_me_value,
        'KP__c': form_data.get('KP__c'),
        'DeepService__c': form_data.get('DeepService__c'),
        'PrepareTime__c': float(form_data.get('PrepareTime__c', 0)) or None,
        'Effort__c': float(form_data.get('Effort__c', 0)) or None,
        'Renewal__c': form_data.get('Renewal__c'),
        'meetingminutes__c': spca_text or None,
        'PromiseTodo__c': form_data.get('spca_c') or None,
        'LaterPlan__c': form_data.get('spca_a') or None,
        'ServiceDetail__c': form_data.get('ServiceDetail__c') or None,
        'Feedback__c': form_data.get('Feedback__c') or None,
        'UnresolveIssueRisk__c': form_data.get('UnresolveIssueRisk__c') or None,
    }
    if account_id:
        record['ExistedAccount__c'] = account_id
    # 从 Account 继承 CSM 负责人
    if csm_owner:
        record['CSManager__c'] = csm_owner

    # 清理 None 值
    record = {k: v for k, v in record.items() if v is not None}

    # 4. 写入 Salesforce
    try:
        sf_res = requests.post(
            f"{SF_CONFIG['url']}/services/data/v58.0/sobjects/CSM__c",
            headers=headers,
            json=record,
            timeout=15
        )
        if sf_res.status_code in (200, 201):
            sf_id = sf_res.json().get('id')
            logging.info(f"✅ SF 写入成功: {sf_id} (客户: {matched_name})")
            return {'status': 'ok', 'sf_id': sf_id, 'client': matched_name}
        else:
            error = sf_res.json()
            logging.error(f"SF 写入失败: {error}")
            return {'status': 'error', 'reason': error}
    except Exception as e:
        logging.error(f"SF 写入异常: {e}")
        return {'status': 'error', 'reason': str(e)}

@app.before_request
def monitor_access():
    """每次请求前检查异常"""
    ip = request.remote_addr
    path = request.path

    # 健康检查和 token 生成不记录
    if path in ('/health', '/generate_token'):
        return

    # 记录访问
    log_access(ip, path, request.method)

    # 检查非工作时间（仅表单页面和提交）
    if path in ('/', '/submit') and check_off_hours():
        logging.warning(f"非工作时间访问: {ip} → {path}")
        alert_key = f'offhours_{ip}'
        if not hasattr(app, '_alert_sent'):
            app._alert_sent = {}
        now = time.time()
        last = app._alert_sent.get(alert_key, 0)
        if now - last > 3600:
            alert_off_hours_access(ip, path)
            app._alert_sent[alert_key] = now

    # 检查频率限制
    if check_rate_limit(ip):
        logging.warning(f"频繁访问: {ip}")
        alert_key = f'ratelimit_{ip}'
        if not hasattr(app, '_alert_sent'):
            app._alert_sent = {}
        now = time.time()
        last = app._alert_sent.get(alert_key, 0)
        if now - last > 1800:
            count = len(ACCESS_TRACKER.get(ip, []))
            alert_rate_limit(ip, count)
            app._alert_sent[alert_key] = now


@app.route('/')
def index():
    """表单页面 - 必须携带有效 token"""
    token = request.args.get('t')
    if not token:
        return EXPIRED_HTML

    valid, reason = validate_token(token)
    if not valid:
        logging.info(f"Token 无效 ({reason}): {token}")
        return EXPIRED_HTML

    # Token 有效，返回表单页面
    # URL 中原有参数仍然作为预填数据传递给前端
    return FORM_HTML


@app.route('/generate_token', methods=['POST'])
def generate_token():
    """生成一次性表单 token（供 Maggie/Alex 调用）"""
    try:
        body = request.json or {}
        token = create_token()
        base_url = body.get('base_url', 'http://163.7.9.79:9090')
        return jsonify({
            'status': 'ok',
            'token': token,
            'url': f'{base_url}/?t={token}',
            'expires_in': TOKEN_EXPIRY_SECONDS
        })
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/submit', methods=['POST'])
def submit():
    """接收表单提交，保存到本地，然后触发 CSM-OP 写入 Salesforce"""
    try:
        data = request.json
        token = data.get('_token')

        # 如果有 token，验证并标记为已使用
        if token:
            valid, reason = validate_token(token)
            if not valid:
                return jsonify({'status': 'error', 'error': f'链接已失效（{reason}）'}), 403
            mark_submitted(token)

        # 保存到本地文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{timestamp}_{data.get("meeting_id", "unknown")}.json'
        filepath = os.path.join(DATA_DIR, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logging.info(f"表单提交保存: {filepath} (客户: {data.get('client', 'N/A')})")

        # ⚠️ 提交后自动触发 CSM-OP 写入 Salesforce
        sf_result = trigger_csm_op_write_sf(data, filepath)

        return jsonify({
            'status': 'ok',
            'message': '提交成功',
            'sf_result': sf_result
        })

    except Exception as e:
        logging.error(f"表单提交失败: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'maggie-csm-form'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9090
    logging.info(f"📅 Maggie CSM 表单服务启动: http://0.0.0.0:{port}")
    logging.info(f"⚠️ SF 写入由 CSM-OP 执行，Maggie 不直接写入")
    app.run(host='0.0.0.0', port=port, debug=False)
