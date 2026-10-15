"""Flask CLI commands: `flask --app opspilot.wsgi <command>`."""

from __future__ import annotations

from pathlib import Path

import click
from flask import Flask, current_app

from opspilot.db import drop_all, init_schema

DEFAULT_RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    @click.option("--reset", is_flag=True, help="Drop all tables first (destroys data).")
    def init_db_command(reset: bool):
        """Create tables and indexes."""
        engine = current_app.extensions["opspilot.engine"]
        if reset:
            drop_all(engine)
        init_schema(engine)
        click.echo(f"schema ready on {engine.dialect.name}")

    @app.cli.command("load-runbooks")
    @click.argument("directory", required=False, type=click.Path(exists=True, file_okay=False))
    def load_runbooks_command(directory: str | None):
        """Load Markdown runbooks into the database (upsert by file name)."""
        from opspilot.triage.runbook_loader import load_directory

        engine = current_app.extensions["opspilot.engine"]
        with engine.begin() as conn:
            count = load_directory(conn, Path(directory) if directory else DEFAULT_RUNBOOK_DIR)
        click.echo(f"loaded {count} runbooks")

    @app.cli.command("analyze")
    @click.argument("logfile", type=click.File("r", encoding="utf-8", errors="replace"))
    def analyze_command(logfile):
        """Analyze a log file and open incidents for error spikes."""
        from opspilot.analyzer.ingest import analyze_logs

        engine = current_app.extensions["opspilot.engine"]
        cfg = current_app.config
        with engine.begin() as conn:
            result = analyze_logs(
                conn,
                logfile,
                source=Path(logfile.name).name,
                window_seconds=cfg["SPIKE_WINDOW_SECONDS"],
                threshold=cfg["SPIKE_THRESHOLD"],
            )
        for key, value in result.as_dict().items():
            click.echo(f"{key:>18}: {value}")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Load runbooks, demo engineers and a sample log so the dashboard has data."""
        from opspilot.seed import seed_demo

        summary = seed_demo(current_app.extensions["opspilot.engine"], DEFAULT_RUNBOOK_DIR)
        click.echo(summary)
