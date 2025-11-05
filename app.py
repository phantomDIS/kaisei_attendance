from flask import Flask, render_template, request, redirect, url_for, session
import json, os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secret_key"

DATA_FILE = "data.json"
ATTEND_FILE = "attendance.json"  # 点呼履歴（セッションごと）

# ============ ユーティリティ ============
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def now_hm():
    return datetime.now().strftime("%H:%M")

# ============ 予定データ（today/tomorrow） ============
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"today": [], "tomorrow": []}

    if not isinstance(data, dict):
        data = {"today": [], "tomorrow": []}
    data.setdefault("today", [])
    data.setdefault("tomorrow", [])
    return data

def save_data(data):
    data.setdefault("today", [])
    data.setdefault("tomorrow", [])
    for day in ["today", "tomorrow"]:
        try:
            data[day].sort(key=lambda x: x.get("start", ""))
        except Exception:
            pass
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============ 点呼データ（セッション履歴） ============
# 形式:
# {
#   "sessions": [
#       {
#         "started_at": "2025-11-04T19:10:00",
#         "entries": [ {"team":"1A","time":"2025-11-04T19:12:05"}, ... ]
#       },
#       ...
#   ]
# }
def load_attendance():
    try:
        with open(ATTEND_FILE, "r", encoding="utf-8") as f:
            att = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        att = {"sessions": []}

    if not isinstance(att, dict):
        att = {"sessions": []}
    att.setdefault("sessions", [])

    # セッションが1つも無ければ作成（自動開始）
    if not att["sessions"]:
        att["sessions"].append({"started_at": now_iso(), "entries": []})
        save_attendance(att)
    # entries の保証
    for s in att["sessions"]:
        s.setdefault("entries", [])
    return att

def save_attendance(att):
    with open(ATTEND_FILE, "w", encoding="utf-8") as f:
        json.dump(att, f, ensure_ascii=False, indent=2)

def latest_session(att):
    # 必ず一つ以上ある前提（load_attendanceが保証）
    return att["sessions"][-1]

def team_done_in_latest(att, team):
    ses = latest_session(att)
    for e in ses["entries"]:
        if e.get("team") == team:
            return e.get("time")
    return None

# ============ ログイン ============

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        team = request.form["team"].strip()
        password = request.form["password"].strip()

        if team == "admin" and password == "00":
            session["user"] = "admin"
            return redirect(url_for("admin"))
        elif password == "00":
            session["user"] = team
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="パスワードが違います。")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ============ 班ページ ============

@app.route("/dashboard")
def dashboard():
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    team = session["user"]
    data = load_data()
    att = load_attendance()
    done_time_iso = team_done_in_latest(att, team)  # None なら未点呼
    done_hm = None
    if done_time_iso:
        try:
            done_hm = datetime.fromisoformat(done_time_iso).strftime("%H:%M")
        except Exception:
            done_hm = done_time_iso  # 変換失敗時はそのまま表示

    return render_template(
        "dashboard.html",
        team=team,
        posts=data,
        attendance_done_time=done_hm
    )

# 予定の追加/編集/削除
@app.route("/add_post/<day>", methods=["POST"])
def add_post(day):
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))
    team = session["user"]

    start = request.form["start"]
    task = request.form["task"]

    data = load_data()
    data[day].append({"author": team, "start": start, "task": task, "comment": ""})
    save_data(data)
    return redirect(url_for("dashboard"))

@app.route("/edit_post/<day>/<int:index>", methods=["POST"])
def edit_post(day, index):
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    team = session["user"]
    data = load_data()
    if 0 <= index < len(data[day]) and data[day][index]["author"] == team:
        data[day][index]["start"] = request.form["start"]
        data[day][index]["task"] = request.form["task"]
        save_data(data)
    return redirect(url_for("dashboard"))

@app.route("/delete_post/<day>/<int:index>", methods=["POST"])
def delete_post(day, index):
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    team = session["user"]
    data = load_data()
    if 0 <= index < len(data[day]) and data[day][index]["author"] == team:
        data[day].pop(index)
        save_data(data)
    return redirect(url_for("dashboard"))

# ============ 点呼（履歴セッション） ============

@app.route("/attendance_mark", methods=["POST"])
def attendance_mark():
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))
    team = session["user"]

    att = load_attendance()
    ses = latest_session(att)
    # まだこのセッションで押していなければ登録
    if not any(e.get("team") == team for e in ses["entries"]):
        ses["entries"].append({"team": team, "time": now_iso()})
        # 時刻順で並べる
        ses["entries"].sort(key=lambda x: x.get("time", ""))
        save_attendance(att)

    return redirect(url_for("dashboard"))

@app.route("/attendance_reset", methods=["POST"])
def attendance_reset():
    # 管理者：新しい点呼セッションを開始（履歴は残す）
    if session.get("user") != "admin":
        return redirect(url_for("login"))
    att = load_attendance()
    att["sessions"].append({"started_at": now_iso(), "entries": []})
    save_attendance(att)
    return redirect(url_for("admin"))

# ============ 管理者ページ ============

@app.route("/admin")
def admin():
    if session.get("user") != "admin":
        return redirect(url_for("login"))
    data = load_data()
    att = load_attendance()
    latest = att["sessions"][-1]
    return render_template(
        "admin.html",
        data=data,
        attendance=att,     # 履歴全部
        latest=latest       # 直近セッション
    )

@app.route("/admin_comment/<day>/<int:index>", methods=["POST"])
def admin_comment(day, index):
    if session.get("user") != "admin":
        return redirect(url_for("login"))
    comment = request.form["comment"]
    data = load_data()
    if 0 <= index < len(data[day]):
        data[day][index]["comment"] = comment
        save_data(data)
    return redirect(url_for("admin"))

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

