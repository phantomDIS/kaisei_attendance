from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secret_key")

# ============ DB設定 ============
db_url = os.environ.get("DATABASE_URL", "")

# Renderのpostgres:// を SQLAlchemy用に変換
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# ローカル用フォールバック
if not db_url:
    db_url = "sqlite:///local.db"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ============ モデル定義 ============

class Schedule(db.Model):
    """
    予定（today / tomorrow）、班ごと
    """
    __tablename__ = "schedules"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False)         # "today" or "tomorrow"
    team = db.Column(db.String(50), nullable=False)        # 班名（例: "1A"）
    start = db.Column(db.String(5), nullable=False)        # "HH:MM"
    task = db.Column(db.String(255), nullable=False)
    comment = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)


class AttendanceSession(db.Model):
    """
    点呼セッション（管理者がリセットするたびに1つ増える）
    """
    __tablename__ = "attendance_sessions"

    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    entries = db.relationship(
        "AttendanceEntry",
        backref="session",
        lazy=True,
        cascade="all, delete-orphan"
    )


class AttendanceEntry(db.Model):
    """
    セッション内の各班の点呼記録
    """
    __tablename__ = "attendance_entries"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("attendance_sessions.id"),
                           nullable=False)
    team = db.Column(db.String(50), nullable=False)
    time = db.Column(db.DateTime, default=datetime.utcnow)


# ============ ユーティリティ ============

def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def now_hm(dt: datetime | None):
    if not dt:
        return None
    return dt.strftime("%H:%M")


def get_latest_session(create_if_missing=True) -> AttendanceSession | None:
    ses = AttendanceSession.query.order_by(AttendanceSession.id.desc()).first()
    if not ses and create_if_missing:
        ses = AttendanceSession(started_at=datetime.utcnow())
        db.session.add(ses)
        db.session.commit()
    return ses


def team_done_time_in_latest(team: str) -> datetime | None:
    ses = get_latest_session(create_if_missing=False)
    if not ses:
        return None
    entry = (
        AttendanceEntry.query
        .filter_by(session_id=ses.id, team=team)
        .order_by(AttendanceEntry.time.desc())
        .first()
    )
    return entry.time if entry else None


def get_posts_by_day():
    """
    テンプレ互換用:
    { "today": [ {author, start, task, comment}, ... ],
      "tomorrow": [ ... ] }
    をDBから生成
    """
    result = {"today": [], "tomorrow": []}
    for day in ("today", "tomorrow"):
        rows = (
            Schedule.query
            .filter_by(day=day)
            .order_by(Schedule.start.asc(), Schedule.id.asc())
            .all()
        )
        for s in rows:
            result[day].append({
                "id": s.id,
                "author": s.team,
                "start": s.start,
                "task": s.task,
                "comment": s.comment or "",
            })
    return result


def get_attendance_struct():
    """
    テンプレ互換用:
    {
      "sessions": [
        {
          "started_at": "...",
          "entries": [ {"team": "...", "time": "..."}, ... ]
        },
        ...
      ]
    }
    """
    data = {"sessions": []}
    sessions = AttendanceSession.query.order_by(AttendanceSession.id.asc()).all()
    for s in sessions:
        ses_dict = {
            "started_at": s.started_at.isoformat(timespec="seconds")
            if s.started_at else "",
            "entries": []
        }
        entries = sorted(s.entries, key=lambda e: e.time)
        for e in entries:
            ses_dict["entries"].append({
                "team": e.team,
                "time": e.time.isoformat(timespec="seconds")
            })
        data["sessions"].append(ses_dict)
    return data


def get_schedule_row_by_index(day: str, index: int):
    """
    day＋インデックスから Schedule を取得。
    テンプレで使っている index0 と揃えるため、
    一覧と同じ順序 (start, id) で並べて該当要素を返す。
    """
    rows = (
        Schedule.query
        .filter_by(day=day)
        .order_by(Schedule.start.asc(), Schedule.id.asc())
        .all()
    )
    if 0 <= index < len(rows):
        return rows[index]
    return None


# ============ DB初期化用（1回だけ叩く） ============

@app.route("/initdb")
def initdb():
    db.create_all()
    # 初回アクセス時にセッション1つ作っておく
    get_latest_session(create_if_missing=True)
    return "Database initialized."


# ============ ログイン ============

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        team = request.form["team"].strip()
        password = request.form["password"].strip()

        # 管理者
        if team == "admin" and password == "00":
            session["user"] = "admin"
            return redirect(url_for("admin"))

        # 班（全員パスワード00）
        if password == "00" and team:
            session["user"] = team
            return redirect(url_for("dashboard"))

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

    posts = get_posts_by_day()
    done_dt = team_done_time_in_latest(team)
    done_hm_str = now_hm(done_dt) if done_dt else None

    return render_template(
        "dashboard.html",
        team=team,
        posts=posts,
        attendance_done_time=done_hm_str
    )


# ============ 予定の追加/編集/削除 ============

@app.route("/add_post/<day>", methods=["POST"])
def add_post(day):
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    if day not in ("today", "tomorrow"):
        return redirect(url_for("dashboard"))

    team = session["user"]
    start = request.form.get("start", "").strip()
    task = request.form.get("task", "").strip()

    if not start or not task:
        return redirect(url_for("dashboard"))

    new_row = Schedule(
        day=day,
        team=team,
        start=start,
        task=task,
        comment=""
    )
    db.session.add(new_row)
    db.session.commit()
    return redirect(url_for("dashboard"))


@app.route("/edit_post/<day>/<int:index>", methods=["POST"])
def edit_post(day, index):
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    row = get_schedule_row_by_index(day, index)
    if row and row.team == session["user"]:
        row.start = request.form.get("start", row.start).strip()
        row.task = request.form.get("task", row.task).strip()
        db.session.commit()

    return redirect(url_for("dashboard"))


@app.route("/delete_post/<day>/<int:index>", methods=["POST"])
def delete_post(day, index):
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    row = get_schedule_row_by_index(day, index)
    if row and row.team == session["user"]:
        db.session.delete(row)
        db.session.commit()

    return redirect(url_for("dashboard"))


# ============ 点呼（履歴セッション） ============

@app.route("/attendance_mark", methods=["POST"])
def attendance_mark():
    if "user" not in session or session["user"] == "admin":
        return redirect(url_for("login"))

    team = session["user"]
    ses = get_latest_session(create_if_missing=True)

    # そのセッションで未登録なら追加
    exists = (
        AttendanceEntry.query
        .filter_by(session_id=ses.id, team=team)
        .first()
    )
    if not exists:
        entry = AttendanceEntry(session_id=ses.id, team=team, time=datetime.utcnow())
        db.session.add(entry)
        db.session.commit()

    return redirect(url_for("dashboard"))


@app.route("/attendance_reset", methods=["POST"])
def attendance_reset():
    # 管理者のみ：新しい点呼セッションを追加
    if session.get("user") != "admin":
        return redirect(url_for("login"))

    ses = AttendanceSession(started_at=datetime.utcnow())
    db.session.add(ses)
    db.session.commit()
    return redirect(url_for("admin"))


# ============ 管理者ページ ============

@app.route("/admin")
def admin():
    if session.get("user") != "admin":
        return redirect(url_for("login"))

    data = get_posts_by_day()
    attendance = get_attendance_struct()
    latest = attendance["sessions"][-1] if attendance["sessions"] else {
        "started_at": "",
        "entries": []
    }

    return render_template(
        "admin.html",
        data=data,
        attendance=attendance,
        latest=latest
    )


@app.route("/admin_comment/<day>/<int:index>", methods=["POST"])
def admin_comment(day, index):
    if session.get("user") != "admin":
        return redirect(url_for("login"))

    comment = request.form.get("comment", "")

    row = get_schedule_row_by_index(day, index)
    if row:
        row.comment = comment
        db.session.commit()

    return redirect(url_for("admin"))

@app.route("/admin_reset_all", methods=["POST"])
def admin_reset_all():
    # 管理者だけ
    if session.get("user") != "admin":
        return redirect(url_for("login"))

    # 消す順番が大事（外部キーの関係）
    AttendanceEntry.query.delete()
    AttendanceSession.query.delete()
    Schedule.query.delete()
    db.session.commit()

    # 新しい点呼セッションを1つ作っておく
    get_latest_session(create_if_missing=True)

    return redirect(url_for("admin"))



# ============ サーバー起動 ============

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
