#!/usr/bin/env python
"""v2.0 完整验证测试 — 含逾期通知自动生成 + 管理员手动提醒"""
import json, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = "http://localhost:5000"
PASS, FAIL = 0, 0

def api(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body else None
    req = Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req) as r: return json.loads(r.read())
    except HTTPError as e: return json.loads(e.read())

def check(desc, ok):
    global PASS, FAIL
    if ok: PASS += 1; print(f"  ✅ {desc}")
    else:   FAIL += 1; print(f"  ❌ {desc}")

import time; ts = str(int(time.time()))
uname = f"v2test_{ts}"

# ═══════════════════════════════════════
# 1. 用户认证
# ═══════════════════════════════════════
print("1. 用户认证...")
admin = api("POST", "/api/login", body={"username":"admin","password":"admin123"})
AT = admin.get("token","")
check("管理员登录", "token" in admin)

r = api("POST", "/api/register", body={"username":uname,"password":"p","role":"student"})
check("新用户注册", r.get("msg") == "注册成功")

stu = api("POST", "/api/login", body={"username":uname,"password":"p"})
ST = stu.get("token","")
check("学生登录", "token" in stu)

# ═══════════════════════════════════════
# 2. 借用设备（过去日期 = 即刻逾期）
# ═══════════════════════════════════════
print("2. 借用设备（过去日期触发逾期）...")
eqs = api("GET", "/api/equipment", token=ST)
check("设备列表非空", len(eqs) > 0)
eid = eqs[0]["id"]

r = api("POST", "/api/borrow", token=ST, body={
    "equipment_id": eid,
    "expected_return": "2026-06-19 19:10:00"  # 一定过期
})
check("借用成功", r.get("msg") == "借用成功")

# ═══════════════════════════════════════
# 3. ★ 核心验证：逾期通知自动生成 ★
# ═══════════════════════════════════════
print("3. 逾期通知自动生成...")
recs = api("GET", "/api/borrow/records", token=ST)
check("记录存在", len(recs) >= 1)
bid = recs[0]["id"]
check(f"记录已标记逾期 (status={recs[0]['status']})", recs[0]["status"] == "overdue")

notifs = api("GET", "/api/notifications", token=ST)
check(f"自动生成通知 (count={len(notifs)})", len(notifs) >= 1)
if notifs:
    check(f"通知内容含「逾期」", "逾期" in notifs[0]["content"])

# ═══════════════════════════════════════
# 4. 未读通知数
# ═══════════════════════════════════════
print("4. 未读通知...")
unread = api("GET", "/api/notifications/unread-count", token=ST)
check(f"未读数正确 (count={unread.get('count',-1)})", unread.get("count", 0) >= 1)

# ═══════════════════════════════════════
# 5. 标记已读
# ═══════════════════════════════════════
print("5. 标记已读...")
if notifs:
    r = api("POST", f"/api/notifications/{notifs[0]['id']}/read", token=ST)
    check("标记已读成功", r.get("msg") == "已标记为已读")
    unread2 = api("GET", "/api/notifications/unread-count", token=ST)
    check("未读数减1", unread2.get("count", 99) == unread.get("count", 0) - 1)

# ═══════════════════════════════════════
# 6. ★ 管理员手动提醒（批量） ★
# ═══════════════════════════════════════
print("6. 管理员批量提醒...")
r = api("POST", "/api/admin/send-reminder", token=AT, body={})
check("批量提醒成功", r.get("sent", 0) >= 1)

# ═══════════════════════════════════════
# 7. ★ 管理员手动提醒（指定记录） ★
# ═══════════════════════════════════════
print("7. 管理员指定记录提醒...")
r = api("POST", "/api/admin/send-reminder", token=AT, body={
    "borrow_id": bid,
    "message": "测试：请于明天归还！"
})
check("指定记录提醒成功", r.get("msg") == "提醒已发送")

# ═══════════════════════════════════════
# 8. 归还设备
# ═══════════════════════════════════════
print("8. 归还设备...")
r = api("POST", f"/api/borrow/{bid}/return", token=ST)
check("归还成功", r.get("msg") == "归还成功")

# ═══════════════════════════════════════
# 9. 数据统计
# ═══════════════════════════════════════
print("9. 数据统计...")
stats = api("GET", "/api/statistics/equipment", token=AT)
check("设备统计非空", len(stats) > 0)
users = api("GET", "/api/statistics/users", token=AT)
check("用户统计非空", len(users) > 0)

# ═══════════════════════════════════════
# 总结
# ═══════════════════════════════════════
total = PASS + FAIL
print(f"\n{'='*60}")
print(f"结果: {PASS}/{total} 通过, {FAIL} 失败")
if FAIL == 0:
    print("🎉 全部测试通过！v2.0 所有功能正常！")
else:
    print("⚠️ 部分测试失败")
    sys.exit(1)
