"""Tests for the SWFPA price XLS scraper."""

from __future__ import annotations

from pathlib import Path

from quayside.scrapers.swfpa import scrape_prices

FIXTURES = Path(__file__).parent / "fixtures"


def test_scrape_prices_from_fixture():
    xls_bytes = (FIXTURES / "peterhead_prices_sample.xls").read_bytes()
    records = scrape_prices(xls_bytes=xls_bytes)

    assert len(records) > 0, "Should parse at least one price record"

    for r in records:
        assert len(r.date) == 10 and r.date[4] == "-", f"Bad date: {r.date}"
        assert r.port == "Peterhead"
        assert r.species, "Species should not be empty"
        assert r.grade, "Grade should not be empty"


def test_scrape_prices_has_grades():
    xls_bytes = (FIXTURES / "peterhead_prices_sample.xls").read_bytes()
    records = scrape_prices(xls_bytes=xls_bytes)

    grades = {r.grade for r in records}
    # Should have at least A1 and A2
    assert "A1" in grades, f"Expected A1 in grades, got {grades}"
    assert "A2" in grades, f"Expected A2 in grades, got {grades}"


def test_scrape_prices_species_coverage():
    xls_bytes = (FIXTURES / "peterhead_prices_sample.xls").read_bytes()
    records = scrape_prices(xls_bytes=xls_bytes)

    species = {r.species for r in records}
    assert len(species) >= 5, f"Expected >= 5 species, got {species}"


def test_scrape_prices_values():
    xls_bytes = (FIXTURES / "peterhead_prices_sample.xls").read_bytes()
    records = scrape_prices(xls_bytes=xls_bytes)

    # At least some records should have actual price values
    has_low = any(r.price_low is not None for r in records)
    has_high = any(r.price_high is not None for r in records)
    has_avg = any(r.price_avg is not None for r in records)

    assert has_low, "Should have at least one record with price_low"
    assert has_high, "Should have at least one record with price_high"
    assert has_avg, "Should have at least one record with price_avg"

    # Prices should be positive
    for r in records:
        if r.price_low is not None:
            assert r.price_low > 0, f"price_low should be positive: {r}"
        if r.price_high is not None:
            assert r.price_high > 0, f"price_high should be positive: {r}"
        if r.price_avg is not None:
            assert r.price_avg > 0, f"price_avg should be positive: {r}"


def test_scrape_prices_single_row_species():
    """Some species (Brill, Turbot, etc.) have a single row with ALL grade."""
    xls_bytes = (FIXTURES / "peterhead_prices_sample.xls").read_bytes()
    records = scrape_prices(xls_bytes=xls_bytes)

    all_grade = [r for r in records if r.grade == "ALL"]
    assert len(all_grade) > 0, "Should have some single-row species with ALL grade"
