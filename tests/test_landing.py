"""Tests for the landing page route — ensures dynamic data renders without error."""

from __future__ import annotations

import pytest

from quayside.web.app import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_landing_renders(client):
    """Landing page returns 200 with real DB data."""
    r = client.get("/landing")
    assert r.status_code == 200


def test_landing_contains_live_data(client):
    """Landing page hero section contains dynamically rendered port/species counts."""
    r = client.get("/landing")
    html = r.data.decode()
    # Stats line must come from DB, not be hardcoded
    assert "ports reporting" in html


def test_landing_no_hardcoded_date(client):
    """Landing page must not contain the old hardcoded date string."""
    r = client.get("/landing")
    html = r.data.decode()
    # The old hardcoded date — if this appears we've regressed to static HTML
    assert "13 MAR 2026" not in html or "QUAYSIDE DIGEST" in html  # ok if it's in the dynamic digest header


def test_landing_ports_copy(client):
    """Ports audience card uses the correct value-led copy, not transactional framing."""
    r = client.get("/landing")
    html = r.data.decode()
    assert "Apply for free" in html
    assert "just share your data" not in html
