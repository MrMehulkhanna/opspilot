import re
from pathlib import Path

import pytest

from opspilot.triage.runbook_loader import load_directory

SPIKE = "\n".join(
    f"2026-10-01T09:00:{i:02d}Z ERROR payments-api gateway timeout from provider" for i in range(30)
)


def _csrf(client, path="/"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def seeded(app, client):
    with app.extensions["opspilot.engine"].begin() as conn:
        load_directory(conn, Path(__file__).resolve().parent.parent / "runbooks")
    client.post("/api/v1/engineers", json={"name": "Neha Iyer", "email": "neha@example.com"})
    res = client.post("/api/v1/logs/analyze", data=SPIKE)
    return res.get_json()["incidents_opened"][0]


@pytest.mark.parametrize("path", ["/", "/reports", "/ingest", "/runbooks"])
def test_pages_render(client, seeded, path):
    res = client.get(path)
    assert res.status_code == 200
    assert "OpsPilot" in res.get_data(as_text=True)


def test_post_without_csrf_rejected(client, seeded):
    assert (
        client.post(f"/incidents/{seeded}/transition", data={"status": "acknowledged"}).status_code
        == 400
    )


def test_engineer_reviews_suggestion_through_dashboard(client, seeded):
    token = _csrf(client)
    client.post("/act-as", data={"csrf": token, "engineer_id": "1"})
    client.post(f"/incidents/{seeded}/transition", data={"csrf": token, "status": "acknowledged"})
    client.post(f"/incidents/{seeded}/suggest", data={"csrf": token})
    page = client.get(f"/incidents/{seeded}").get_data(as_text=True)
    assert "Payment gateway timeouts" in page  # retrieved runbook is cited
    suggestion_id = re.search(r"/suggestions/(\d+)/review", page).group(1)

    res = client.post(
        f"/suggestions/{suggestion_id}/review",
        data={
            "csrf": token,
            "decision": "edit",
            "steps": "Fail over to backup provider\nWatch error rate",
        },
        follow_redirects=True,
    )
    html = res.get_data(as_text=True)
    assert "Suggestion edited." in html
    assert "Fail over to backup provider" in html
    assert "Neha Iyer" in html


def test_domain_errors_are_flashed(client, seeded):
    token = _csrf(client)
    res = client.post(
        f"/incidents/{seeded}/transition",
        data={"csrf": token, "status": "closed"},
        follow_redirects=True,
    )
    assert "cannot move incident" in res.get_data(as_text=True)


def test_upload_log_file_from_dashboard(client):
    import io

    token = _csrf(client, "/ingest")
    res = client.post(
        "/ingest",
        data={"csrf": token, "file": (io.BytesIO(SPIKE.encode()), "app.log")},
        content_type="multipart/form-data",
    )
    html = res.get_data(as_text=True)
    assert "1 spike</b>" in html and "app.log" in html
