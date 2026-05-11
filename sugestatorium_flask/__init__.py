from __future__ import annotations

from pathlib import Path

from .store import initialize_storage


def create_app():
    from flask import Flask

    from .views import bp

    root_path = Path(__file__).resolve().parents[1]
    app = Flask(
        __name__,
        template_folder=str(root_path / "templates"),
        static_folder=str(root_path / "static"),
        static_url_path="/static",
    )
    app.config.update(
        SECRET_KEY="sugestatorium-dev-key",
        ROOT_PATH=root_path,
    )

    initialize_storage(root_path)

    app.jinja_env.filters["title_label"] = _title_label
    app.jinja_env.filters["format_datetime"] = _format_datetime
    app.jinja_env.filters["format_short_date"] = _format_short_date
    app.jinja_env.filters["score_label"] = _score_label

    app.register_blueprint(bp)
    return app


def _title_label(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-"))


def _format_datetime(value: str) -> str:
    from datetime import datetime

    return datetime.fromisoformat(value).strftime("%b %d, %Y %H:%M")


def _format_short_date(value: str) -> str:
    from datetime import datetime

    return datetime.fromisoformat(value).strftime("%b %d")


def _score_label(value: float | int | None) -> str:
    if value is None:
        return "--"
    return f"{float(value):.1f}" if isinstance(value, float) else str(value)
