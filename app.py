# ============================================================
# 高校实验室设备借用管理系统 — Flask 后端
# 西南财经大学天府学院 · 软件工程期末项目
# ============================================================
import os, json, csv, io
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = 'lab-equipment-secret-key-2026'
DATABASE = os.path.join(os.path.dirname(__file__), 'lab.db')

# ── 数据库工具 ──────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'student' CHECK(role IN ('student','admin')),
            phone       TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS equipment (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            model       TEXT,
            total_qty   INTEGER NOT NULL DEFAULT 1,
            available_qty INTEGER NOT NULL DEFAULT 1,
            location    TEXT,
            status      TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available','unavailable')),
            admin_name  TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS borrow_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            equipment_id    INTEGER NOT NULL,
            equipment_name  TEXT NOT NULL,
            borrow_time     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            expected_return TEXT NOT NULL,
            actual_return   TEXT,
            status          TEXT NOT NULL DEFAULT 'borrowed' CHECK(status IN ('borrowed','returned','overdue')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (equipment_id) REFERENCES equipment(id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            borrow_id   INTEGER,
            content     TEXT NOT NULL,
            is_read     INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (borrow_id) REFERENCES borrow_records(id)
        );
    ''')
    # 创建默认管理员
    db.execute("INSERT OR IGNORE INTO users (username,password,role) VALUES (?,?,?)",
               ['admin', generate_password_hash('admin123'), 'admin'])
    # 预置中文实验设备
    seed_equipment = [
        ('示波器 TDS2024C', 'Tektronix TDS2024C', 3, 3, '实验室A-101', 'available', 'admin'),
        ('数字万用表 Fluke 17B+', 'Fluke 17B+', 10, 10, '实验室A-102', 'available', 'admin'),
        ('信号发生器 DG1022Z', 'Rigol DG1022Z', 2, 2, '实验室B-201', 'available', 'admin'),
        ('直流稳压电源 DP832', 'Rigol DP832', 5, 5, '实验室A-101', 'available', 'admin'),
        ('频谱分析仪 DSA815', 'Rigol DSA815', 1, 1, '实验室B-202', 'available', 'admin'),
        ('逻辑分析仪 LA5016', 'Kingst LA5016', 2, 2, '实验室C-301', 'available', 'admin'),
        ('函数信号发生器 AFG1022', 'Tektronix AFG1022', 4, 4, '实验室B-201', 'available', 'admin'),
        ('电子负载 IT8511+', 'ITECH IT8511+', 3, 3, '实验室A-103', 'available', 'admin'),
        ('LCR电桥 TH2830', 'Tonghui TH2830', 2, 2, '实验室C-302', 'available', 'admin'),
        ('热成像仪 TiS20+', 'Fluke TiS20+', 1, 1, '实验室D-401', 'available', 'admin'),
        ('可编程电源 SPD3303X', 'Siglent SPD3303X', 6, 6, '实验室A-101', 'available', 'admin'),
        ('网络分析仪 E5061B', 'Keysight E5061B', 1, 1, '实验室B-203', 'available', 'admin'),
    ]
    for eq in seed_equipment:
        db.execute('''INSERT OR IGNORE INTO equipment (name,model,total_qty,available_qty,location,status,admin_name)
                      VALUES (?,?,?,?,?,?,?)''', eq)
    db.commit()
    db.close()

# ── 认证装饰器 ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '')
        if not token.startswith('Bearer '): return jsonify({'error':'未登录'}), 401
        db = get_db()
        try:
            user_id = int(token[7:])
            user = db.execute("SELECT * FROM users WHERE id=?", [user_id]).fetchone()
        except: user = None
        if not user: return jsonify({'error':'无效登录'}), 401
        g.user = dict(user)
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user.get('role') != 'admin':
            return jsonify({'error':'需要管理员权限'}), 403
        return f(*args, **kwargs)
    return decorated

# ── 逾期检测（后台更新 + 自动生成通知）───────────────────────
def check_overdue():
    db = get_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 一步完成：找出所有逾期且缺少通知的记录，统一处理
    # 先更新状态
    db.execute('''UPDATE borrow_records SET status='overdue'
                  WHERE status='borrowed' AND expected_return < ?''', [now])
    
    # 再为所有逾期无通知的记录创建通知（一次性 SQL）
    db.execute('''
        INSERT INTO notifications (user_id, borrow_id, content, created_at)
        SELECT br.user_id, br.id,
               '您借用的设备「' || br.equipment_name || '」已逾期，请尽快归还！',
               ?
        FROM borrow_records br
        WHERE br.status = 'overdue'
          AND NOT EXISTS (
              SELECT 1 FROM notifications n
              WHERE n.borrow_id = br.id AND n.content LIKE '%逾期%'
          )
    ''', [now])
    db.commit()

# ────────────────────────────────────────────────────────────
#  用户管理 API
# ────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if not data.get('username') or not data.get('password'):
        return jsonify({'error':'用户名密码不能为空'}), 400
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username=?", [data['username']]).fetchone():
        return jsonify({'error':'用户名已存在'}), 409
    db.execute("INSERT INTO users (username,password,role,phone) VALUES (?,?,?,?)",
               [data['username'], generate_password_hash(data['password']),
                data.get('role','student'), data.get('phone','')])
    db.commit()
    return jsonify({'msg':'注册成功'}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", [data.get('username','')]).fetchone()
    if not user or not check_password_hash(user['password'], data.get('password','')):
        return jsonify({'error':'用户名或密码错误'}), 401
    return jsonify({'token': str(user['id']), 'user': dict(user)})

@app.route('/api/user/info')
@login_required
def user_info():
    return jsonify(g.user)

@app.route('/api/user/password', methods=['PUT'])
@login_required
def change_password():
    data = request.json
    db = get_db()
    if not check_password_hash(g.user['password'], data.get('old_password','')):
        return jsonify({'error':'原密码错误'}), 400
    db.execute("UPDATE users SET password=? WHERE id=?",
               [generate_password_hash(data['new_password']), g.user['id']])
    db.commit()
    return jsonify({'msg':'密码修改成功'})

# ────────────────────────────────────────────────────────────
#  设备管理 API
# ────────────────────────────────────────────────────────────
@app.route('/api/equipment')
@login_required
def list_equipment():
    db = get_db()
    q = request.args.get('q','')
    status = request.args.get('status','')
    sql = "SELECT * FROM equipment WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE ? OR model LIKE ?)"
        params += [f'%{q}%', f'%{q}%']
    if status:
        sql += " AND status=?"
        params.append(status)
    rows = db.execute(sql + " ORDER BY id DESC", params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/equipment/<int:eid>')
@login_required
def get_equipment(eid):
    db = get_db()
    row = db.execute("SELECT * FROM equipment WHERE id=?", [eid]).fetchone()
    if not row: return jsonify({'error':'设备不存在'}), 404
    return jsonify(dict(row))

@app.route('/api/equipment', methods=['POST'])
@login_required
@admin_required
def add_equipment():
    data = request.json
    db = get_db()
    total = int(data.get('total_qty', 1))
    db.execute('''INSERT INTO equipment (name,model,total_qty,available_qty,location,status,admin_name)
                  VALUES (?,?,?,?,?,?,?)''',
               [data['name'], data.get('model',''), total, total,
                data.get('location',''), data.get('status','available'), g.user['username']])
    db.commit()
    return jsonify({'msg':'添加成功', 'id': db.execute("SELECT last_insert_rowid()").fetchone()[0]}), 201

@app.route('/api/equipment/<int:eid>', methods=['PUT'])
@login_required
@admin_required
def update_equipment(eid):
    data = request.json
    db = get_db()
    eq = db.execute("SELECT * FROM equipment WHERE id=?", [eid]).fetchone()
    if not eq: return jsonify({'error':'设备不存在'}), 404
    new_total = int(data.get('total_qty', eq['total_qty']))
    borrowed = eq['total_qty'] - eq['available_qty']
    new_avail = max(0, new_total - borrowed)
    status = 'unavailable' if new_avail == 0 else data.get('status', eq['status'])
    db.execute('''UPDATE equipment SET name=?, model=?, total_qty=?, available_qty=?,
                  location=?, status=?, admin_name=?
                  WHERE id=?''',
               [data.get('name', eq['name']), data.get('model', eq['model']),
                new_total, new_avail, data.get('location', eq['location']),
                status, g.user['username'], eid])
    db.commit()
    return jsonify({'msg':'更新成功'})

@app.route('/api/equipment/<int:eid>', methods=['DELETE'])
@login_required
@admin_required
def delete_equipment(eid):
    db = get_db()
    active = db.execute("SELECT COUNT(*) as c FROM borrow_records WHERE equipment_id=? AND status IN ('borrowed','overdue')",
                        [eid]).fetchone()['c']
    if active: return jsonify({'error':'设备有未归还记录，无法删除'}), 400
    db.execute("DELETE FROM equipment WHERE id=?", [eid])
    db.commit()
    return jsonify({'msg':'删除成功'})

# ────────────────────────────────────────────────────────────
#  借用管理 API
# ────────────────────────────────────────────────────────────
@app.route('/api/borrow', methods=['POST'])
@login_required
def borrow_equipment():
    if g.user['role'] != 'student':
        return jsonify({'error':'仅学生可借用设备'}), 403
    data = request.json
    db = get_db()
    check_overdue()
    # 检查是否有逾期未还
    overdue = db.execute("SELECT COUNT(*) as c FROM borrow_records WHERE user_id=? AND status='overdue'",
                         [g.user['id']]).fetchone()['c']
    if overdue > 0:
        return jsonify({'error':'您有逾期未还的设备，请先归还后再借用'}), 400
    eq = db.execute("SELECT * FROM equipment WHERE id=?", [data['equipment_id']]).fetchone()
    if not eq: return jsonify({'error':'设备不存在'}), 404
    if eq['available_qty'] <= 0:
        return jsonify({'error':'该设备已无可用库存'}), 400
    expected = data.get('expected_return', '')
    # 事务
    db.execute('''INSERT INTO borrow_records (user_id,equipment_id,equipment_name,expected_return)
                  VALUES (?,?,?,?)''',
               [g.user['id'], eq['id'], eq['name'], expected])
    db.execute("UPDATE equipment SET available_qty=available_qty-1 WHERE id=?",
               [eq['id']])
    db.execute("UPDATE equipment SET status='unavailable' WHERE id=? AND available_qty<=0",
               [eq['id']])
    db.commit()
    return jsonify({'msg':'借用成功'}), 201

@app.route('/api/borrow/<int:bid>/return', methods=['POST'])
@login_required
def return_equipment(bid):
    db = get_db()
    record = db.execute("SELECT * FROM borrow_records WHERE id=?", [bid]).fetchone()
    if not record: return jsonify({'error':'记录不存在'}), 404
    if record['status'] in ('returned',):
        return jsonify({'error':'该设备已归还'}), 400
    # 权限：只能还自己的，或管理员可以还任何人的
    if g.user['role'] != 'admin' and record['user_id'] != g.user['id']:
        return jsonify({'error':'无权操作'}), 403
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_status = 'overdue' if now > record['expected_return'] else 'returned'
    db.execute("UPDATE borrow_records SET actual_return=?, status=? WHERE id=?",
               [now, new_status, bid])
    db.execute("UPDATE equipment SET available_qty=available_qty+1 WHERE id=?",
               [record['equipment_id']])
    db.execute("UPDATE equipment SET status='available' WHERE id=? AND available_qty>0",
               [record['equipment_id']])
    db.commit()
    return jsonify({'msg':'归还成功', 'status': new_status})

@app.route('/api/borrow/records')
@login_required
def borrow_records():
    db = get_db()
    check_overdue()
    sql = "SELECT br.*, u.username FROM borrow_records br JOIN users u ON br.user_id=u.id WHERE 1=1"
    params = []
    if g.user['role'] == 'student':
        sql += " AND br.user_id=?"
        params.append(g.user['id'])
    status = request.args.get('status','')
    if status:
        sql += " AND br.status=?"
        params.append(status)
    eid = request.args.get('equipment_id','')
    if eid: sql += " AND br.equipment_id=?"; params.append(eid)
    rows = db.execute(sql + " ORDER BY br.id DESC", params).fetchall()
    return jsonify([dict(r) for r in rows])

# ────────────────────────────────────────────────────────────
#  通知提醒 API
# ────────────────────────────────────────────────────────────
@app.route('/api/notifications')
@login_required
def list_notifications():
    db = get_db()
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC",
                      [g.user['id']]).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
@login_required
def mark_read(nid):
    db = get_db()
    db.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
               [nid, g.user['id']])
    db.commit()
    return jsonify({'msg':'已标记为已读'})

@app.route('/api/notifications/unread-count')
@login_required
def unread_count():
    db = get_db()
    row = db.execute("SELECT COUNT(*) as c FROM notifications WHERE user_id=? AND is_read=0",
                     [g.user['id']]).fetchone()
    return jsonify({'count': row['c']})

@app.route('/api/admin/send-reminder', methods=['POST'])
@login_required
@admin_required
def send_reminder():
    """管理员手动向指定逾期用户发送提醒通知"""
    data = request.json
    db = get_db()
    user_id = data.get('user_id')
    borrow_id = data.get('borrow_id')
    custom_msg = data.get('message', '').strip()

    if borrow_id:
        # 针对指定借用记录发送提醒
        record = db.execute(
            "SELECT br.*, u.username FROM borrow_records br JOIN users u ON br.user_id=u.id WHERE br.id=?",
            [borrow_id]
        ).fetchone()
        if not record:
            return jsonify({'error': '借用记录不存在'}), 404
        target_user_id = record['user_id']
        content = custom_msg or f'管理员提醒：您借用的设备「{record["equipment_name"]}」已逾期，请尽快归还！'
    elif user_id:
        # 向指定用户的所有逾期记录发送提醒
        target_user_id = user_id
        content = custom_msg or '管理员提醒：您有逾期未还的设备，请尽快归还！'
    else:
        # 向所有逾期用户批量发送提醒
        overdue_users = db.execute(
            "SELECT DISTINCT user_id FROM borrow_records WHERE status='overdue'"
        ).fetchall()
        if not overdue_users:
            return jsonify({'msg': '当前没有逾期用户', 'sent': 0})
        count = 0
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for u in overdue_users:
            db.execute('''INSERT INTO notifications (user_id, borrow_id, content, created_at)
                          VALUES (?, NULL, ?, ?)''',
                       [u['user_id'], custom_msg or '管理员提醒：您有逾期未还的设备，请尽快归还！', now])
            count += 1
        db.commit()
        return jsonify({'msg': f'已向 {count} 位逾期用户发送提醒', 'sent': count})

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db.execute('''INSERT INTO notifications (user_id, borrow_id, content, created_at)
                  VALUES (?, ?, ?, ?)''',
               [target_user_id, borrow_id, content, now])
    db.commit()
    return jsonify({'msg': '提醒已发送', 'sent': 1})

# ────────────────────────────────────────────────────────────
#  数据统计 API
# ────────────────────────────────────────────────────────────
@app.route('/api/statistics/equipment')
@login_required
@admin_required
def equipment_stats():
    db = get_db()
    rows = db.execute('''
        SELECT e.id, e.name, e.model, e.total_qty, e.available_qty,
               COUNT(br.id) as borrow_count
        FROM equipment e
        LEFT JOIN borrow_records br ON e.id=br.equipment_id
        GROUP BY e.id
        ORDER BY borrow_count DESC
    ''').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/statistics/users')
@login_required
@admin_required
def user_stats():
    db = get_db()
    rows = db.execute('''
        SELECT u.id, u.username, u.role,
               COUNT(br.id) as borrow_count,
               SUM(CASE WHEN br.status='overdue' THEN 1 ELSE 0 END) as overdue_count
        FROM users u
        LEFT JOIN borrow_records br ON u.id=br.user_id
        WHERE u.role='student'
        GROUP BY u.id
        ORDER BY borrow_count DESC
    ''').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/statistics/export')
@login_required
@admin_required
def export_stats():
    db = get_db()
    # 设备统计
    eq_rows = db.execute('''
        SELECT e.name AS 设备名称, e.model AS 型号, e.total_qty AS 总数量,
               e.available_qty AS 可用数量,
               COUNT(br.id) AS 借用次数
        FROM equipment e LEFT JOIN borrow_records br ON e.id=br.equipment_id
        GROUP BY e.id ORDER BY 借用次数 DESC
    ''').fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['设备名称','型号','总数量','可用数量','借用次数'])
    for r in eq_rows: writer.writerow(list(r))
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),
                     mimetype='text/csv', as_attachment=True,
                     download_name=f'设备统计_{datetime.now().strftime("%Y%m%d")}.csv')

# ────────────────────────────────────────────────────────────
#  首页路由
# ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return app.send_static_file('index.html')

# ── 调试：列出所有路由 ─────────────────────────────────────────
@app.route('/api/debug/routes')
def debug_routes():
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        routes.append(f"{','.join(rule.methods - {'HEAD','OPTIONS'})} {rule.rule}")
    return jsonify({'version': 'v2.0-check_overdue-SQL', 'routes': routes})

# ────────────────────────────────────────────────────────────
#  启动
# ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    import os
    port = int(os.environ.get('PORT', 5000))
    print("✅ 实验室设备借用管理系统已启动 → http://localhost:5000")
    print("   管理员账号: admin / admin123")
    print("   [v2.0] 逾期通知自动生成 + 管理员手动提醒已启用")
    app.run(debug=False, host='0.0.0.0', port=port)
