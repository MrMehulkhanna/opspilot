from pathlib import Path

SAMPLE_LOG = Path(__file__).resolve().parent.parent / "sample_logs" / "app.log"


def test_cli_init_load_and_analyze(app):
    runner = app.test_cli_runner()
    assert "schema ready" in runner.invoke(args=["init-db"]).output
    assert "loaded 9 runbooks" in runner.invoke(args=["load-runbooks"]).output

    result = runner.invoke(args=["analyze", str(SAMPLE_LOG)])
    assert result.exit_code == 0, result.output
    assert "spikes_detected: 4" in result.output

    client = app.test_client()
    services = {i["service_name"] for i in client.get("/api/v1/incidents").get_json()["incidents"]}
    assert services == {"payments-api", "orders-db", "auth", "notifications"}
