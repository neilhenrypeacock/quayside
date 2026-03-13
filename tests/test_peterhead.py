"""Tests for the Peterhead landings HTML scraper."""

from __future__ import annotations

from pathlib import Path

from quayside.scrapers.peterhead import scrape_landings

FIXTURES = Path(__file__).parent / "fixtures"


def test_scrape_landings_from_fixture():
    html = (FIXTURES / "peterhead_sample.html").read_text()
    records = scrape_landings(html)

    assert len(records) > 0, "Should parse at least one landing record"

    # Check date format
    for r in records:
        assert len(r.date) == 10 and r.date[4] == "-", f"Bad date: {r.date}"
        assert r.port == "Peterhead"

    # Check we got multiple vessels
    vessels = {r.vessel_name for r in records}
    assert len(vessels) >= 2, f"Expected multiple vessels, got {vessels}"

    # Check vessel codes are parsed
    coded = [r for r in records if r.vessel_code]
    assert len(coded) > 0, "Should have vessel codes"

    # Check species are non-empty strings
    for r in records:
        assert r.species, "Species should not be empty"
        assert r.boxes >= 0
        assert r.boxes_msc >= 0


def test_scrape_landings_vessel_parsing():
    html = (FIXTURES / "peterhead_sample.html").read_text()
    records = scrape_landings(html)

    # Find a known vessel from the fixture
    vessel_names = {r.vessel_name for r in records}
    # At least one vessel should have a code like BF/PD/INS etc.
    codes = {r.vessel_code for r in records if r.vessel_code}
    assert len(codes) > 0, "Should parse vessel registration codes"


def test_scrape_landings_species_coverage():
    html = (FIXTURES / "peterhead_sample.html").read_text()
    records = scrape_landings(html)

    species = {r.species for r in records}
    # Should have at least a few common species
    assert len(species) >= 3, f"Expected >= 3 species, got {species}"


def test_scrape_landings_no_zero_only():
    """Records with 0 boxes and 0 MSC boxes should not be created."""
    html = (FIXTURES / "peterhead_sample.html").read_text()
    records = scrape_landings(html)

    for r in records:
        assert r.boxes > 0 or r.boxes_msc > 0, \
            f"Record {r.vessel_name}/{r.species} has 0 boxes and 0 MSC"
