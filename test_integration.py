#!/usr/bin/env python3
"""Full integration test for lab equipment borrowing system"""
import json, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = "http://localhost:5000"
OK, FAIL = 0, 0

def api(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body else None
    req = Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req) as r:
            return json.loads(r.read())
    except HTTPError as e:
        return json.loads(e.read())

def check(desc, ok):
    global OK, FAIL
    if ok:
        OK += 1
        print(f"  [PASS] {desc}")
    else:
        FAIL += 1
        print(f"  [FAIL] {desc}")

# ── Admin login ──
print("1. Admin login...")
admin = api("POST", "/api/login", body={"username": "admin", "password": "admin123"})
check("admin login returns token", "token" in admin)
AT = admin.get("token", "")

# ── Add equipment ──
print("2. Add equipment...")
for name in ["Oscilloscope", "Multimeter", "SignalGen", "PowerSupply", "SpectrumAnalyzer"]:
    r = api("POST", "/api/equipment", token=AT, body={
        "name": name, "model": f"{name}-X1", "total_qty": 5, "location": "Lab A"
    })
    check(f"add {name}", r.get("msg") == "添加成功")

# ── Register student ──
print("3. Register student...")
r = api("POST", "/api/register", body={"username": "stu001", "password": "pass123", "role": "student"})
check("register student", "msg" in r)

# ── Student login ──
print("4. Student login...")
stu = api("POST", "/api/login", body={"username": "stu001", "password": "pass123"})
check("student login", "token" in stu)
ST = stu.get("token", "")

# ── View equipment ──
print("5. View equipment...")
eqs = api("GET", "/api/equipment", token=ST)
check("equipment list >= 5", len(eqs) >= 5)

# ── Borrow ──
print("6. Borrow equipment...")
r = api("POST", "/api/borrow", token=ST, body={
    "equipment_id": eqs[0]["id"],
    "expected_return": "2026-06-30 18:00:00"
})
check("borrow success", r.get("msg") == "借用成功")

# ── Verify stock decreased ──
eqs2 = api("GET", "/api/equipment", token=ST)
check("stock decreased", eqs2[0]["available_qty"] == eqs[0]["available_qty"] - 1)

# ── My records ──
print("7. My records...")
recs = api("GET", "/api/borrow/records", token=ST)
check("has borrow record", len(recs) >= 1)
check("record status is borrowed", recs[0]["status"] in ("borrowed",))

# ── Return ──
print("8. Return equipment...")
r = api("POST", f"/api/borrow/{recs[0]['id']}/return", token=ST)
check("return success", r.get("msg") == "归还成功")

# ── Verify stock restored ──
eqs3 = api("GET", "/api/equipment", token=ST)
check("stock restored", eqs3[0]["available_qty"] == eqs2[0]["available_qty"] + 1)

# ── Admin stats ──
print("9. Admin statistics...")
stats = api("GET", "/api/statistics/equipment", token=AT)
check("stats available", len(stats) >= 5)

users = api("GET", "/api/statistics/users", token=AT)
check("user stats", len(users) >= 1)

# ── Notifications ──
print("10. Notifications...")
n = api("GET", "/api/notifications/unread-count", token=ST)
check("unread count ok", "count" in n)

# ── CSV export ──
print("11. CSV export...")
# Just check endpoint exists
req = Request(BASE + "/api/statistics/export")
req.add_header("Authorization", f"Bearer {AT}")
try:
    with urlopen(req) as r:
        csv_data = r.read().decode('utf-8-sig')
        check("csv has header", csv_data.startswith("设备名称"))
except HTTPError as e:
    check("csv export accessible", False)

# ── Summary ──
total = OK + FAIL
print(f"\n{'='*50}")
print(f"Results: {OK}/{total} passed, {FAIL} failed")
if FAIL == 0:
    print("ALL TESTS PASSED!")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
