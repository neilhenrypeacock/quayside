"""Authentication blueprint — login, register, logout, admin guard."""

from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

from quayside.db import create_user, get_all_ports, get_user_by_email, get_user_by_id

auth_bp = Blueprint("auth", __name__)


class User(UserMixin):
    def __init__(self, row: dict):
        self.id = row["id"]
        self.email = row["email"]
        self.role = row["role"]
        self.port_slug = row["port_slug"]


def setup_login_manager(app):
    """Configure flask-login on the app. Call from create_app()."""
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to access this page."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        row = get_user_by_id(int(user_id))
        return User(row) if row else None


def _post_login_url(user) -> str:
    if user.role == "port" and user.port_slug:
        return url_for("ports.port_dashboard", slug=user.port_slug)
    if user.role == "admin":
        return url_for("ops.ops_dashboard")
    return url_for("trade.trade_dashboard")


def require_admin():
    """Return an error response if the current user is not an admin, else None."""
    if not current_user.is_authenticated:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("auth.login", next=request.path))
    if current_user.role != "admin":
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": "Admin access required"}), 403
        return "Admin access required", 403
    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_post_login_url(current_user))
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        row = get_user_by_email(email)
        if row and check_password_hash(row["password_hash"], password):
            user = User(row)
            login_user(user)
            next_url = request.args.get("next", "")
            # Only allow relative redirects (prevent open redirect)
            if not next_url or next_url.startswith("//") or "://" in next_url:
                next_url = _post_login_url(user)
            return redirect(next_url)
        flash("Incorrect email or password.")
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(_post_login_url(current_user))
    ports = get_all_ports(status="active")
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        role = request.form.get("role", "trade")
        port_slug = request.form.get("port_slug") or None

        if not email or not password:
            flash("Email and password are required.")
        elif password != confirm:
            flash("Passwords do not match.")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.")
        elif get_user_by_email(email):
            flash("An account with that email already exists.")
        else:
            if role not in ("port", "trade"):
                role = "trade"
            if role == "port" and not port_slug:
                flash("Please select your port.")
            else:
                pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
                user_id = create_user(email, pw_hash, role, port_slug if role == "port" else None)
                row = get_user_by_id(user_id)
                user = User(row)
                login_user(user)
                return redirect(_post_login_url(user))
    return render_template("register.html", ports=ports)


@auth_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("public.landing"))
