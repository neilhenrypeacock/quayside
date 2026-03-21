"""Flask application factory — registers blueprints and app-level middleware.

Run with: python -m quayside.web.app
"""

from __future__ import annotations

import logging
import os
import secrets

from flask import Flask, jsonify, render_template, request, session

from quayside.db import close_db, get_latest_rich_date, init_db, seed_demo_data, seed_demo_port_data
from quayside.ports import seed_ports
from quayside.report import build_landing_data
from quayside.species import KEY_SPECIES

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    from pathlib import Path

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
    )
    _secret = os.environ.get("QUAYSIDE_SECRET_KEY", "")
    if not _secret:
        if os.environ.get("GUNICORN_CMD_ARGS") or os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn"):
            raise RuntimeError(
                "QUAYSIDE_SECRET_KEY must be set in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        _secret = "dev-secret-change-me"
        logger.warning("Using insecure dev SECRET_KEY — set QUAYSIDE_SECRET_KEY for production")
    app.secret_key = _secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = not app.debug
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit

    # ── CSRF protection ──
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

    _csrf_serializer = URLSafeTimedSerializer(app.secret_key, salt="csrf-token")

    def _generate_csrf_token() -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return _csrf_serializer.dumps(session["csrf_token"])

    def _validate_csrf_token() -> bool:
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not token:
            return False
        try:
            data = _csrf_serializer.loads(token, max_age=7200)  # 2-hour expiry
            return data == session.get("csrf_token")
        except (BadSignature, SignatureExpired):
            return False

    # Make csrf_token() available in all templates
    app.jinja_env.globals["csrf_token"] = _generate_csrf_token

    # Routes that skip CSRF (JSON APIs with their own auth)
    _CSRF_EXEMPT = {"/api/v1/ingest", "/api/v1/export/csv"}

    @app.before_request
    def _check_csrf():
        if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
            return
        if request.path in _CSRF_EXEMPT:
            return
        if request.is_json:
            return
        if not _validate_csrf_token():
            return "CSRF token missing or invalid.", 403

    @app.after_request
    def _set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # ── Request-scoped DB connection teardown ──
    app.teardown_appcontext(close_db)

    # ── Auth ──
    from quayside.web.auth import auth_bp, setup_login_manager

    setup_login_manager(app)
    app.register_blueprint(auth_bp)

    # ── Blueprints ──
    from quayside.web.api_views import api_bp
    from quayside.web.digest import digest_bp
    from quayside.web.ops_views import ops_bp
    from quayside.web.port_views import port_bp
    from quayside.web.public import public_bp
    from quayside.web.trade_views import trade_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(digest_bp)
    app.register_blueprint(port_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(trade_bp)
    app.register_blueprint(api_bp)

    # ── Database init ──
    with app.app_context():
        init_db()
        seed_ports()
        seed_demo_data()
        seed_demo_port_data()

    # ── Context processor: ticker data for base.html ──
    @app.context_processor
    def inject_ticker():
        date = get_latest_rich_date()
        if date:
            ld = build_landing_data(date)
            all_items = ld.get("ticker_items", []) if ld else []
            key_items = [i for i in all_items if i.get("species") in KEY_SPECIES]
            return {"_ticker_items": key_items if len(key_items) >= 3 else all_items}
        return {"_ticker_items": []}

    # ── Context processor: stat strip data for base.html ──
    @app.context_processor
    def inject_stats():
        from quayside.web.helpers import build_stat_strip_data

        date = get_latest_rich_date()
        if date:
            try:
                stats = build_stat_strip_data(date)
                return {"stats": stats}
            except Exception:
                logger.exception("Failed to build stat strip data")
                return {"stats": {}}
        return {"stats": {}}

    # ── Error handlers ──
    @app.errorhandler(404)
    def _not_found(e):
        if request.is_json:
            return jsonify({"error": "Not found"}), 404
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def _server_error(e):
        logger.exception("Internal server error: %s", request.path)
        if request.is_json:
            return jsonify({"error": "Internal server error"}), 500
        return render_template("error.html", code=500, message="Something went wrong"), 500

    # ── Scheduler ──
    from quayside.scheduler import start_scheduler

    start_scheduler(app)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
