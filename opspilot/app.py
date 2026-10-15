"""Flask application factory."""

from __future__ import annotations

import logging
from datetime import date, datetime

from flask import Flask, current_app
from flask.json.provider import DefaultJSONProvider
from sqlalchemy.engine import Engine

from opspilot.config import Config
from opspilot.db import init_schema, make_engine
from opspilot.triage.llm import AnthropicClient, LLMClient


class IsoJSONProvider(DefaultJSONProvider):
    """Serialise datetimes as ISO-8601 instead of Flask's RFC 822 default."""

    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, datetime | date):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def create_app(config: Config | None = None, *, llm: LLMClient | None = None) -> Flask:
    config = config or Config()
    app = Flask(__name__)
    app.json_provider_class = IsoJSONProvider
    app.json = IsoJSONProvider(app)
    app.config.update(config.as_flask_config())

    engine = make_engine(config.DATABASE_URL)
    init_schema(engine)
    app.extensions["opspilot.engine"] = engine

    if llm is None and config.LLM_API_KEY:
        llm = AnthropicClient(config.LLM_API_KEY, config.LLM_MODEL, config.LLM_TIMEOUT_SECONDS)
    app.extensions["opspilot.llm"] = llm

    from opspilot.api import api_bp
    from opspilot.cli import register_cli
    from opspilot.web import web_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)
    register_cli(app)

    if not app.debug and not app.testing:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    return app


def get_engine() -> Engine:
    return current_app.extensions["opspilot.engine"]


def get_llm() -> LLMClient | None:
    return current_app.extensions.get("opspilot.llm")
