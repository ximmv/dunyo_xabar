import os
import sqlite3
import re
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, g, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "yangiliklar.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-uchun-maxfiy-kalit-buni-ozgartiring")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin123"))
)

CATEGORIES = [
    {"slug": "dunyo", "name": "Dunyo"},
    {"slug": "ozbekiston", "name": "O'zbekiston"},
    {"slug": "iqtisodiyot", "name": "Iqtisodiyot"},
    {"slug": "sport", "name": "Sport"},
    {"slug": "texnologiya", "name": "Texnologiya"},
    {"slug": "jamiyat", "name": "Jamiyat"},
]
CATEGORY_MAP = {c["slug"]: c["name"] for c in CATEGORIES}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            summary TEXT NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT,
            category TEXT NOT NULL,
            is_breaking INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()


def slugify(text):
    text = text.lower().strip()
    replacements = {
        "o'": "o", "'": "", "‘": "", "’": "",
        " ": "-", "ʻ": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9\-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "maqola"


def unique_slug(db, title, exclude_id=None):
    base = slugify(title)
    slug = base
    i = 2
    while True:
        if exclude_id:
            row = db.execute(
                "SELECT id FROM articles WHERE slug = ? AND id != ?", (slug, exclude_id)
            ).fetchone()
        else:
            row = db.execute("SELECT id FROM articles WHERE slug = ?", (slug,)).fetchone()
        if not row:
            return slug
        slug = f"{base}-{i}"
        i += 1


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    filename = secure_filename(file_storage.filename)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{stamp}-{filename}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return f"uploads/{filename}"


def format_date(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        oylar = ["", "yanvar", "fevral", "mart", "aprel", "may", "iyun",
                 "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]
        return f"{dt.day} {oylar[dt.month]}, {dt.strftime('%H:%M')}"
    except Exception:
        return iso_str


app.jinja_env.filters["chiroyli_sana"] = format_date
app.jinja_env.globals["categories"] = CATEGORIES


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def home():
    db = get_db()
    breaking = db.execute(
        "SELECT * FROM articles WHERE is_breaking = 1 ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    hero = db.execute("SELECT * FROM articles ORDER BY created_at DESC LIMIT 1").fetchone()
    latest = db.execute(
        "SELECT * FROM articles ORDER BY created_at DESC LIMIT 13 OFFSET 1"
    ).fetchall()
    return render_template("index.html", hero=hero, latest=latest, breaking=breaking)


@app.route("/bolim/<slug>")
def category(slug):
    if slug not in CATEGORY_MAP:
        abort(404)
    db = get_db()
    articles = db.execute(
        "SELECT * FROM articles WHERE category = ? ORDER BY created_at DESC", (slug,)
    ).fetchall()
    return render_template(
        "category.html", articles=articles, slug=slug, name=CATEGORY_MAP[slug]
    )


@app.route("/maqola/<slug>")
def article(slug):
    db = get_db()
    art = db.execute("SELECT * FROM articles WHERE slug = ?", (slug,)).fetchone()
    if not art:
        abort(404)
    related = db.execute(
        "SELECT * FROM articles WHERE category = ? AND id != ? ORDER BY created_at DESC LIMIT 4",
        (art["category"], art["id"]),
    ).fetchall()
    return render_template("article.html", art=art, related=related, cat_name=CATEGORY_MAP.get(art["category"], art["category"]))


@app.route("/qidiruv")
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        db = get_db()
        results = db.execute(
            "SELECT * FROM articles WHERE title LIKE ? OR summary LIKE ? ORDER BY created_at DESC",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    return render_template("search.html", q=q, results=results)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["is_admin"] = True
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        flash("Login yoki parol noto'g'ri.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))


@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    articles = db.execute("SELECT * FROM articles ORDER BY created_at DESC").fetchall()
    return render_template("admin_dashboard.html", articles=articles)


@app.route("/admin/yangi", methods=["GET", "POST"])
@login_required
def admin_new():
    if request.method == "POST":
        return _save_article(None)
    return render_template("admin_form.html", art=None)


@app.route("/admin/tahrirlash/<int:article_id>", methods=["GET", "POST"])
@login_required
def admin_edit(article_id):
    db = get_db()
    art = db.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not art:
        abort(404)
    if request.method == "POST":
        return _save_article(article_id)
    return render_template("admin_form.html", art=art)


def _save_article(article_id):
    db = get_db()
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    content = request.form.get("content", "").strip()
    cat = request.form.get("category", "")
    is_breaking = 1 if request.form.get("is_breaking") == "on" else 0
    now = datetime.now().isoformat(timespec="seconds")

    if not title or not summary or not content or cat not in CATEGORY_MAP:
        flash("Iltimos barcha maydonlarni to'ldiring.")
        art = db.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone() if article_id else None
        return render_template("admin_form.html", art=art), 400

    image_url = save_image(request.files.get("image"))

    if article_id:
        art = db.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        slug = unique_slug(db, title, exclude_id=article_id)
        db.execute(
            """UPDATE articles SET title=?, slug=?, summary=?, content=?, category=?,
               is_breaking=?, image_url=COALESCE(?, image_url), updated_at=? WHERE id=?""",
            (title, slug, summary, content, cat, is_breaking, image_url, now, article_id),
        )
    else:
        slug = unique_slug(db, title)
        db.execute(
            """INSERT INTO articles (title, slug, summary, content, image_url, category,
               is_breaking, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (title, slug, summary, content, image_url, cat, is_breaking, now, now),
        )
    db.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/ochirish/<int:article_id>", methods=["POST"])
@login_required
def admin_delete(article_id):
    db = get_db()
    db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    db.commit()
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
else:
    init_db()