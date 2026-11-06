from flask import Flask, jsonify

from .db import close_db, init_db, setting
from .routes import api_bp, ui_bp


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True, template_folder="../templates", static_folder="../static")
    app.config.from_mapping(
        SECRET_KEY="phantom-local-session-key",
        DATABASE_PATH=None,
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    app.register_blueprint(ui_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"ok": True, "service": "phantom-trade-copier", "mode": setting("mode", "SIMULATION")}

    @app.get("/manus-routes.json")
    def route_manifest():
        return jsonify({"routes": [{"path": "/", "title": "Phantom Trade Copier"}]})

    return app
