"""Ops blueprint — internal dashboard, pipeline triggers, quality reports."""

from __future__ import annotations

import io
import sqlite3
from collections import OrderedDict, defaultdict
from datetime import date as _date_type
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, send_file

from quayside.db import get_quality_issues, get_quality_summary

ops_bp = Blueprint("ops", __name__)


@ops_bp.route("/ops")
def ops_dashboard():
    """Internal ops dashboard — scraper health, port status, data coverage."""
    conn = __import__("quayside.db", fromlist=["get_connection"]).get_connection()
    conn.row_factory = sqlite3.Row
    all_ports = [dict(r) for r in conn.execute("SELECT * FROM ports ORDER BY region, name").fetchall()]

    _REGION_ORDER = [
        "Scotland — North & Islands",
        "Scotland — North East",
        "Scotland — South East",
        "England — North East",
        "England — North West",
        "England — East",
        "England — South West",
        "Wales",
        "Northern Ireland",
    ]
    _region_rank = {r: i for i, r in enumerate(_REGION_ORDER)}

    live_ports = [p for p in all_ports if p["status"] == "active" and p.get("data_method") != "demo"]
    pipeline_ports = [p for p in all_ports if p["status"] in ("outreach", "future")]
    _status_rank = {"outreach": 0, "future": 1}
    pipeline_ports.sort(key=lambda p: (
        _status_rank.get(p["status"], 99),
        _region_rank.get(p["region"], 99),
        p["name"],
    ))

    live_by_region: dict[str, list[dict]] = OrderedDict()
    for p in sorted(live_ports, key=lambda p: (_region_rank.get(p["region"], 99), p["name"])):
        live_by_region.setdefault(p["region"], []).append(p)

    ports_by_region: dict[str, list[dict]] = OrderedDict()
    for p in sorted(all_ports, key=lambda p: (_region_rank.get(p["region"], 99), p["name"])):
        ports_by_region.setdefault(p["region"], []).append(p)

    daily_data = conn.execute(
        """SELECT date, port, COUNT(DISTINCT species) as species_count,
                  COUNT(*) as record_count, MIN(scraped_at) as first_scraped
           FROM prices
           WHERE date >= date('now', '-21 days')
           GROUP BY date, port
           ORDER BY date DESC, port"""
    ).fetchall()

    port_coverage: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in daily_data:
        port_coverage[row["port"]][row["date"]] = {
            "species": row["species_count"],
            "records": row["record_count"],
            "scraped_at": row["first_scraped"],
        }

    port_data_timing: dict[str, dict] = {}
    for _pt_port, _pt_date_map in port_coverage.items():
        _pt_minutes: list[int] = []
        for _pt_info in _pt_date_map.values():
            _raw = _pt_info.get("scraped_at")
            if not _raw:
                continue
            try:
                _ts = datetime.fromisoformat(_raw)
                _pt_minutes.append(_ts.hour * 60 + _ts.minute)
            except Exception:
                pass
        if len(_pt_minutes) >= 3:
            _pt_minutes.sort()
            _mid = len(_pt_minutes) // 2
            port_data_timing[_pt_port] = {
                "median": f"{_pt_minutes[_mid] // 60:02d}:{_pt_minutes[_mid] % 60:02d}",
                "earliest": f"{min(_pt_minutes) // 60:02d}:{min(_pt_minutes) % 60:02d}",
                "latest": f"{max(_pt_minutes) // 60:02d}:{max(_pt_minutes) % 60:02d}",
                "sample_days": len(_pt_minutes),
            }

    today = datetime.now()
    current_monday = today - timedelta(days=today.weekday())
    weeks = []
    for week_offset in range(3):
        monday = current_monday - timedelta(weeks=week_offset)
        week_dates = []
        for day_offset in range(7):
            d = monday + timedelta(days=day_offset)
            week_dates.append({
                "date_str": d.strftime("%Y-%m-%d"),
                "dow_name": d.strftime("%a"),
                "day_num": d.strftime("%d"),
                "is_today": d.date() == today.date(),
                "is_weekend": d.weekday() >= 5,
                "is_future": d > today,
            })
        if week_dates:
            label = f"w/c {monday.strftime('%d %b')}"
            weeks.append({"label": label, "dates": week_dates})

    all_coverage_dates = []
    for week in weeks:
        for dd in week["dates"]:
            all_coverage_dates.append(dd["date_str"])

    species_per_port = {}
    for row in conn.execute(
        "SELECT port, COUNT(DISTINCT species) as species_count FROM prices GROUP BY port"
    ).fetchall():
        species_per_port[row["port"]] = row["species_count"]

    first_data_per_port = {}
    for row in conn.execute(
        "SELECT port, MIN(date) as first_date FROM prices GROUP BY port"
    ).fetchall():
        first_data_per_port[row["port"]] = row["first_date"]

    success_days_per_port = {}
    for row in conn.execute(
        "SELECT port, COUNT(DISTINCT date) as success_days FROM prices GROUP BY port"
    ).fetchall():
        success_days_per_port[row["port"]] = row["success_days"]

    today_date = today.date()
    fails_per_port = {}
    for port_name, first_date_str in first_data_per_port.items():
        start = _date_type.fromisoformat(first_date_str)
        weekday_count = 0
        d_iter = start
        while d_iter <= today_date:
            if d_iter.weekday() < 5:
                weekday_count += 1
            d_iter += timedelta(days=1)
        fails_per_port[port_name] = max(0, weekday_count - success_days_per_port.get(port_name, 0))

    port_records = {}
    for row in conn.execute(
        "SELECT port, COUNT(*) as record_count FROM prices GROUP BY port"
    ).fetchall():
        port_records[row["port"]] = row["record_count"]

    port_value_30d = {}
    for row in conn.execute(
        """SELECT port, SUM(weight_kg * price_avg) as total_value
           FROM prices
           WHERE date >= date('now', '-30 days')
             AND weight_kg IS NOT NULL AND weight_kg > 0
             AND price_avg IS NOT NULL
           GROUP BY port"""
    ).fetchall():
        if row["total_value"]:
            port_value_30d[row["port"]] = row["total_value"]

    port_records_30d = {}
    for row in conn.execute(
        """SELECT port, COUNT(*) as record_count
           FROM prices
           WHERE date >= date('now', '-30 days')
           GROUP BY port"""
    ).fetchall():
        port_records_30d[row["port"]] = row["record_count"]

    totals = conn.execute(
        "SELECT COUNT(*) as total, COUNT(DISTINCT date) as dates FROM prices"
    ).fetchone()

    active_port_names = [p["name"] for p in all_ports if p["status"] == "active" and p.get("data_method") != "demo"]

    expected_auction_days = {
        "Peterhead": {0, 1, 2, 3, 4},
        "Brixham": {0, 1, 2, 3, 4},
        "Newlyn": {0, 1, 2, 3, 4},
        "Scrabster": {0, 1, 2, 3, 4},
        "Lerwick": {0, 1, 2, 3, 4},
    }

    scrape_alerts = []
    check_start = current_monday - timedelta(weeks=1)
    d = check_start
    while d <= today:
        date_str = d.strftime("%Y-%m-%d")
        dow = d.weekday()
        is_today_flag = d.date() == today.date()

        for port_name in active_port_names:
            expected_days = expected_auction_days.get(port_name, {0, 1, 2, 3, 4})
            has_data = date_str in port_coverage.get(port_name, {})

            if dow >= 5:
                continue

            if not has_data and dow in expected_days:
                if port_name not in first_data_per_port:
                    continue
                if date_str < first_data_per_port[port_name]:
                    continue
                if is_today_flag:
                    any_port_today = any(
                        date_str in port_coverage.get(pn, {})
                        for pn in active_port_names
                    )
                    if any_port_today:
                        reason = "Scrape returned empty"
                    else:
                        reason = "Not yet scraped today"
                else:
                    any_port_that_day = any(
                        date_str in port_coverage.get(pn, {})
                        for pn in active_port_names
                    )
                    if not any_port_that_day:
                        reason = "Public holiday — no auctions"
                    else:
                        reason = "No data published"
                scrape_alerts.append({
                    "port": port_name,
                    "date": date_str,
                    "dow": d.strftime("%a"),
                    "reason": reason,
                    "is_today": is_today_flag,
                })
        d += timedelta(days=1)

    scrape_alerts.sort(key=lambda a: (not a["is_today"], a["date"]), reverse=False)
    scrape_alerts.sort(key=lambda a: a["date"], reverse=True)

    dow_data = conn.execute(
        """SELECT port,
                  CASE CAST(strftime('%w', date) AS INTEGER)
                    WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
                    WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri'
                    WHEN 6 THEN 'Sat' END as dow,
                  COUNT(DISTINCT date) as count
           FROM prices
           WHERE date >= date('now', '-90 days')
           GROUP BY port, strftime('%w', date)
           ORDER BY port, strftime('%w', date)"""
    ).fetchall()

    port_frequency: dict[str, dict[str, int]] = defaultdict(dict)
    for row in dow_data:
        port_frequency[row["port"]][row["dow"]] = row["count"]

    known_schedules = {
        "Peterhead": "Mon-Fri, morning auction via SWFPA",
        "Brixham": "Mon-Fri, electronic auction",
        "Newlyn": "Mon-Fri, morning market",
        "Scrabster": "Mon-Fri, consignment sales",
        "Lerwick": "Mon-Fri, varies with landings",
    }

    def classify_frequency(dow_counts: dict[str, int]) -> str:
        active_days = [d for d, c in dow_counts.items() if c >= 3]
        if len(active_days) >= 4:
            return "Daily (Mon-Fri)"
        elif len(active_days) == 3:
            return f"3x/week ({', '.join(sorted(active_days))})"
        elif len(active_days) == 2:
            return f"2x/week ({', '.join(sorted(active_days))})"
        elif len(active_days) == 1:
            return f"Weekly ({active_days[0]})"
        return "Irregular"

    gaps = []
    weekdays_checked = 0
    d = today
    while weekdays_checked < 10:
        if d.weekday() < 5:
            date_str = d.strftime("%Y-%m-%d")
            for port_name in active_port_names:
                if date_str not in port_coverage.get(port_name, {}):
                    if date_str < first_data_per_port.get(port_name, "0000-00-00"):
                        continue
                    gaps.append({"port": port_name, "date": date_str, "type": "missing"})
            weekdays_checked += 1
        d -= timedelta(days=1)

    upload_stats = conn.execute(
        "SELECT status, COUNT(*) as count FROM uploads GROUP BY status"
    ).fetchall()
    upload_summary = {row["status"]: row["count"] for row in upload_stats}

    correction_count = conn.execute(
        "SELECT COUNT(*) FROM extraction_corrections"
    ).fetchone()[0]

    scrape_log_rows = []
    try:
        scrape_log_rows = conn.execute(
            """SELECT port, ran_at, success, record_count, error_type, error_msg
               FROM scrape_log
               WHERE ran_at >= datetime('now', '-7 days')
               ORDER BY ran_at DESC"""
        ).fetchall()
    except Exception:
        pass

    last_scrape_info: dict[str, dict] = {}
    for row in scrape_log_rows:
        port_name = row["port"]
        if row["success"] and port_name not in last_scrape_info:
            ran_at_str = row["ran_at"]
            try:
                ts = datetime.fromisoformat(ran_at_str)
                last_scrape_info[port_name] = {
                    "date": ts.strftime("%Y-%m-%d"),
                    "day": ts.strftime("%a"),
                }
            except Exception:
                pass

    fallback_rows = conn.execute(
        "SELECT port, MAX(scraped_at) as last_scraped FROM prices GROUP BY port"
    ).fetchall()
    for row in fallback_rows:
        if row["port"] not in last_scrape_info and row["last_scraped"]:
            try:
                ts = datetime.fromisoformat(row["last_scraped"])
                last_scrape_info[row["port"]] = {
                    "date": ts.strftime("%Y-%m-%d"),
                    "day": ts.strftime("%a"),
                }
            except Exception:
                pass

    today_str_for_log = today.strftime("%Y-%m-%d")
    _SCRAPE_SLOTS = [f"{h:02d}:{m:02d}" for h in range(7, 17) for m in (0, 30)]
    today_timeline: dict[str, dict[str, dict]] = {}
    for row in scrape_log_rows:
        if not row["ran_at"].startswith(today_str_for_log):
            continue
        port_name = row["port"]
        try:
            ts = datetime.fromisoformat(row["ran_at"])
            slot_min = 0 if ts.minute < 30 else 30
            slot = f"{ts.hour:02d}:{slot_min:02d}"
            if port_name not in today_timeline:
                today_timeline[port_name] = {}
            today_timeline[port_name][slot] = {
                "attempted": True,
                "success": bool(row["success"]),
                "record_count": row["record_count"],
                "error_type": row["error_type"],
            }
        except Exception:
            pass

    last_attempt_per_port: dict[str, str] = {}
    for row in scrape_log_rows:
        if not row["ran_at"].startswith(today_str_for_log):
            continue
        port_name = row["port"]
        if port_name not in last_attempt_per_port:
            try:
                ts = datetime.fromisoformat(row["ran_at"])
                last_attempt_per_port[port_name] = ts.strftime("%H:%M")
            except Exception:
                pass

    today_scrape_summary: dict[str, dict] = {}
    for row in reversed(scrape_log_rows):
        if not row["ran_at"].startswith(today_str_for_log):
            continue
        port_name = row["port"]
        try:
            ts = datetime.fromisoformat(row["ran_at"])
            time_str = ts.strftime("%H:%M")
            if port_name not in today_scrape_summary:
                today_scrape_summary[port_name] = {
                    "first_attempt": time_str,
                    "first_success": None,
                    "last_success": None,
                    "success_count": 0,
                    "success_times": [],
                    "status": "failed",
                    "record_count": 0,
                    "error_type": None,
                }
            if row["success"]:
                if today_scrape_summary[port_name]["first_success"] is None:
                    today_scrape_summary[port_name]["first_success"] = time_str
                today_scrape_summary[port_name]["last_success"] = time_str
                today_scrape_summary[port_name]["success_count"] += 1
                today_scrape_summary[port_name]["success_times"].append(time_str)
                today_scrape_summary[port_name]["status"] = "success"
                today_scrape_summary[port_name]["record_count"] = row["record_count"]
            elif today_scrape_summary[port_name]["status"] != "success":
                today_scrape_summary[port_name]["error_type"] = row["error_type"]
        except Exception:
            pass

    latest_data_date_rows = conn.execute(
        "SELECT port, MAX(date) as last_data_date FROM prices GROUP BY port"
    ).fetchall()
    latest_data_date = {row["port"]: row["last_data_date"] for row in latest_data_date_rows}

    for _pname, _s in today_scrape_summary.items():
        _s["last_attempt"] = last_attempt_per_port.get(_pname)

    for _pname, _s in today_scrape_summary.items():
        if _s["status"] == "failed" and not _s["error_type"]:
            _s["status"] = "empty"
            _s["last_data_date"] = latest_data_date.get(_pname)

    conn.close()

    today_str = today.strftime("%Y-%m-%d")
    today_is_weekday = today.weekday() < 5

    for port_name, summary in today_scrape_summary.items():
        if summary["status"] == "success":
            last_date = latest_data_date.get(port_name)
            if last_date and last_date < today_str:
                summary["status"] = "stale"
                summary["last_data_date"] = last_date
                summary["last_data_date_display"] = datetime.strptime(last_date, "%Y-%m-%d").strftime("%-d %b")

    today_succeeded = [p for p in today_scrape_summary.values() if p["status"] == "success"]
    today_attempted_count = len(today_scrape_summary)
    today_succeeded_count = len(today_succeeded)
    all_attempt_times = [v["first_attempt"] for v in today_scrape_summary.values() if v.get("first_attempt")]
    today_first_run = min(all_attempt_times) if all_attempt_times else None
    _now = today
    next_scrape_str: str | None = None
    if 7 <= _now.hour < 17:
        _next_min = ((_now.minute // 10) + 1) * 10
        _next_hour = _now.hour
        if _next_min >= 60:
            _next_min = 0
            _next_hour += 1
        if _next_hour < 17:
            next_scrape_str = f"{_next_hour:02d}:{_next_min:02d}"
    today_alerts = [a for a in scrape_alerts if a["is_today"]]
    historical_alerts = [a for a in scrape_alerts if not a["is_today"]]

    quality_issues = get_quality_issues(days=7)
    quality_summary = get_quality_summary()

    latest_quality_by_port: dict[str, dict] = {}
    if quality_summary.get("last_checked_at"):
        latest_at = quality_summary["last_checked_at"]
        for issue in quality_issues:
            if issue["checked_at"] != latest_at:
                continue
            port = issue["port"]
            if port not in latest_quality_by_port:
                latest_quality_by_port[port] = {"errors": 0, "warns": 0}
            if issue["severity"] == "error":
                latest_quality_by_port[port]["errors"] += 1
            else:
                latest_quality_by_port[port]["warns"] += 1

    return render_template(
        "ops.html",
        ports=all_ports,
        ports_by_region=ports_by_region,
        live_ports=live_ports,
        live_by_region=live_by_region,
        pipeline_ports=pipeline_ports,
        port_coverage=dict(port_coverage),
        weeks=weeks,
        species_per_port=species_per_port,
        total_records=totals["total"],
        total_dates=totals["dates"],
        active_port_names=active_port_names,
        port_frequency=dict(port_frequency),
        known_schedules=known_schedules,
        classify_frequency=classify_frequency,
        scrape_alerts=scrape_alerts,
        gaps=gaps[:20],
        upload_summary=upload_summary,
        correction_count=correction_count,
        first_data_per_port=first_data_per_port,
        success_days_per_port=success_days_per_port,
        fails_per_port=fails_per_port,
        port_records=port_records,
        port_value_30d=port_value_30d,
        port_records_30d=port_records_30d,
        last_scrape_info=last_scrape_info,
        today_timeline=today_timeline,
        scrape_slots=_SCRAPE_SLOTS,
        today_str=today_str,
        today_is_weekday=today_is_weekday,
        today_scrape_summary=today_scrape_summary,
        today_attempted_count=today_attempted_count,
        today_succeeded_count=today_succeeded_count,
        today_first_run=today_first_run,
        next_scrape_str=next_scrape_str,
        today_alerts=today_alerts,
        historical_alerts=historical_alerts,
        quality_issues=quality_issues,
        quality_summary=quality_summary,
        latest_quality_by_port=latest_quality_by_port,
        port_data_timing=port_data_timing,
    )


@ops_bp.route("/ops/run-pipeline", methods=["POST"])
def ops_run_pipeline():
    """Trigger the full scrape -> store -> report pipeline and return JSON result."""
    import subprocess
    import sys

    from flask import current_app

    try:
        result = subprocess.run(
            [sys.executable, "-m", "quayside"],
            capture_output=True, text=True, timeout=300,
            cwd=current_app.config.get("PROJECT_ROOT", ".")
        )
        return jsonify({
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-3000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Pipeline timed out after 5 minutes"}), 504
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@ops_bp.route("/ops/run-quality-check", methods=["POST"])
def ops_run_quality_check():
    """Run quality checks now and return JSON summary."""
    from quayside.quality import run_quality_checks

    summary = run_quality_checks()
    return jsonify({"ok": True, "errors": summary["errors"], "warns": summary["warns"]})


@ops_bp.route("/ops/quality/clear/<int:issue_id>", methods=["POST"])
def ops_clear_quality_issue(issue_id):
    """Mark a quality issue as cleared (acknowledged)."""
    from quayside.db import clear_quality_issue

    clear_quality_issue(issue_id)
    return jsonify({"ok": True})


@ops_bp.route("/ops/quality/clear-all", methods=["POST"])
def ops_clear_all_quality_issues():
    """Mark all open quality issues as cleared."""
    from quayside.db import clear_all_quality_issues

    count = clear_all_quality_issues()
    return jsonify({"ok": True, "cleared": count})


@ops_bp.route("/ops/quality-report")
def ops_quality_report():
    """Comprehensive quality report — port dashboards, digest preview, ops health."""
    from quayside.quality import build_comprehensive_report

    date_param = request.args.get("date") or _date_type.today().isoformat()
    report = build_comprehensive_report(date_param)
    return render_template("quality_report.html", report=report, date=date_param)


@ops_bp.route("/ops/quality-report/download")
def ops_quality_report_download():
    """Download the comprehensive quality report as a Markdown file."""
    from quayside.quality import build_comprehensive_report

    date_param = request.args.get("date") or _date_type.today().isoformat()
    report = build_comprehensive_report(date_param)

    lines = []
    lines.append(f"# Quayside Quality Report — {report['date']}")
    lines.append(f"\nGenerated: {report['generated_at'][:16].replace('T', ' ')} UTC")
    lines.append("Site: https://quaysidedata.duckdns.org\n")

    lines.append("## Port Dashboards\n")
    lines.append(f"What each port dashboard displays for {report['date']}.\n")
    for p in report["port_dashboards"]:
        status = "DATA" if p["has_today_data"] else "NO DATA"
        lines.append(f"### {p['port']} [{status}]")
        lines.append(f"- Records today: {p['record_count']}")
        lines.append(f"- Today avg price: {'£{:.2f}/kg'.format(p['today_avg']) if p['today_avg'] else '—'}")
        if p["vs_last_week_pct"] is not None:
            lines.append(f"- vs last week: {p['vs_last_week_pct']:+.1f}% (was £{p['last_week_price']:.2f}/kg)")
        else:
            exp = "expected" if p["hero_null_expected"] else "UNEXPECTED"
            lines.append(f"- vs last week: — ({exp}, {p['history_days']} days history)")
        if p["vs_market_pct"] is not None:
            lines.append(f"- vs market: {p['vs_market_pct']:+.1f}%")
        else:
            lines.append("- vs market: — (no benchmark)")
        lines.append(f"- This week avg: {'£{:.2f}/kg'.format(p['this_week_avg']) if p['this_week_avg'] else '—'}")
        lines.append(f"- This month avg: {'£{:.2f}/kg'.format(p['this_month_avg']) if p['this_month_avg'] else '—'}")
        if p["hero_nulls"] and not p["hero_null_expected"]:
            lines.append(f"- ⚠ Unexpected null hero stats: {', '.join(p['hero_nulls'])}")
        if p["species_no_benchmark"]:
            lines.append(f"- Species with no market benchmark: {', '.join(p['species_no_benchmark'])}")
        lines.append("")

    dp = report["digest_preview"]
    lines.append("## Today's Digest\n")
    if dp.get("error"):
        lines.append(f"**Error building digest preview:** {dp['error']}\n")
    else:
        lines.append(f"- Ports reporting: {', '.join(dp['ports_reporting']) or 'none'}")
        if dp["missing_from_digest"]:
            lines.append(f"- Missing from digest: {', '.join(dp['missing_from_digest'])}")
        lines.append(f"- Total species: {dp['total_species']}")
        lines.append(f"- Benchmark species: {dp['benchmark_species_available']}/10")
        if dp["benchmark_species_missing"]:
            lines.append(f"- Benchmark species missing: {', '.join(dp['benchmark_species_missing'])}")
        lines.append(f"- Price movers: {dp['movers_count']}")
        if dp["top_mover"]:
            tm = dp["top_mover"]
            lines.append(f"- Top mover: {tm['species']} @ {tm['port']} ({tm['change_pct']:+.1f}%)")
        lines.append(f"- Digest generated: {'Yes' if dp['digest_already_generated'] else 'No'}")
    lines.append("")

    oh = report["ops_health"]
    lines.append("## Ops Health\n")
    lines.append(f"- Ports scraped today: {', '.join(oh['ports_succeeded']) or 'none'}")
    if oh["ports_failed"]:
        lines.append(f"- Scrape failures: {', '.join(oh['ports_failed'])}")
    if oh["ports_not_attempted"]:
        lines.append(f"- Not attempted: {', '.join(oh['ports_not_attempted'])}")
    lines.append(f"- Historical gaps (14d): {oh['historical_gap_count']}")
    if oh["coverage_holes"]:
        for h in oh["coverage_holes"]:
            lines.append(f"- Coverage hole: {h['port']} — {h['days_in_recent']} days in recent window")
    lines.append(f"- Quality errors (7d): {oh['quality_issues_7d']['errors']}")
    lines.append(f"- Quality warnings (7d): {oh['quality_issues_7d']['warns']}")
    lines.append("")

    lines.append("## Quality Issues (last 7 days)\n")
    issues = report["quality_issues"]
    if not issues:
        lines.append("No quality issues in the last 7 days.\n")
    else:
        lines.append(f"{len(issues)} issue(s) found:\n")
        lines.append("| Severity | Port | Date | Check | Species | Value | Expected | Message |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for issue in issues:
            sev = issue["severity"].upper()
            species = f"{issue['species']} ({issue['grade']})" if issue.get("species") else ""
            val = f"{issue['value']:.2f}" if issue.get("value") is not None else ""
            exp = f"{issue['expected']:.2f}" if issue.get("expected") is not None else ""
            msg = issue["message"].replace("|", "\\|")
            lines.append(f"| {sev} | {issue['port']} | {issue['date']} | {issue['check_type']} | {species} | {val} | {exp} | {msg} |")
        lines.append("")

    md_content = "\n".join(lines)
    filename = f"quayside-quality-{date_param}.md"
    return send_file(
        io.BytesIO(md_content.encode("utf-8")),
        mimetype="text/markdown",
        as_attachment=True,
        download_name=filename,
    )


# ── Error dashboard routes ──────────────────────────────────────────────────


def _next_scan_time() -> str | None:
    """Calculate the next scheduled error scan time (Mon-Fri 8am-5pm UTC, on the hour)."""
    now = datetime.utcnow()
    # Weekend — next scan is Monday 8am
    if now.weekday() >= 5:
        days_until_monday = 7 - now.weekday()
        next_monday = now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
        return next_monday.strftime("%Y-%m-%d %H:%M UTC")
    # Before 8am — next scan is 8am today
    if now.hour < 8:
        return now.replace(hour=8, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M UTC")
    # After 5pm — next scan is 8am next weekday
    if now.hour >= 17:
        next_day = now + timedelta(days=1)
        if next_day.weekday() >= 5:
            next_day += timedelta(days=7 - next_day.weekday())
        return next_day.replace(hour=8, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M UTC")
    # During hours — next scan is next hour
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_hour.strftime("%Y-%m-%d %H:%M UTC")


@ops_bp.route("/ops/errors")
def ops_errors():
    """Error dashboard — quality check results with plain-English explanations."""
    from quayside.db import get_error_log, get_last_scan_time
    from quayside.error_actions import FIX_ACTIONS, PLAIN_ENGLISH

    errors = get_error_log()
    last_scan = get_last_scan_time()
    next_scan = _next_scan_time()

    open_errors = [e for e in errors if e["status"] == "open"]
    resolved_errors = [e for e in errors if e["status"] == "resolved"]
    error_count = sum(1 for e in open_errors if e["severity"] == "error")
    warning_count = sum(1 for e in open_errors if e["severity"] == "warning")
    resolved_count = len(resolved_errors)

    return render_template(
        "errors.html",
        errors=open_errors,
        resolved_errors=resolved_errors,
        last_scan=last_scan,
        next_scan=next_scan,
        error_count=error_count,
        warning_count=warning_count,
        resolved_count=resolved_count,
        plain_english=PLAIN_ENGLISH,
        fix_actions=FIX_ACTIONS,
    )


@ops_bp.route("/ops/errors/scan", methods=["POST"])
def ops_errors_scan():
    """Run a quality scan now and redirect back to the error dashboard."""
    from flask import flash, redirect, url_for

    from quayside.scheduler import run_and_log_quality_check

    run_and_log_quality_check()
    flash("Scan complete")
    return redirect(url_for("ops.ops_errors"))


@ops_bp.route("/ops/errors/fix/<int:error_id>", methods=["POST"])
def ops_errors_fix(error_id):
    """Fix a single error by applying the appropriate fix action."""
    from quayside.db import get_error_log, resolve_error
    from quayside.error_actions import FIX_ACTIONS, apply_fix

    # Find the error
    all_errors = get_error_log()
    error = next((e for e in all_errors if e["id"] == error_id), None)
    if not error:
        return jsonify({"status": "error", "message": "Error not found"}), 404

    check_name = error["check_name"]
    if FIX_ACTIONS.get(check_name) == "download_only":
        return jsonify({"status": "error", "message": "This error requires manual investigation — download the report to review."}), 400

    try:
        resolution = apply_fix(error)
        resolve_error(error_id, resolution)
        return jsonify({"status": "ok", "message": resolution})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@ops_bp.route("/ops/errors/fix-all", methods=["POST"])
def ops_errors_fix_all():
    """Fix all auto-fixable errors. Skips download_only errors."""
    from quayside.db import get_error_log, resolve_error
    from quayside.error_actions import FIX_ACTIONS, apply_fix

    all_errors = get_error_log()
    open_errors = [e for e in all_errors if e["status"] == "open"]

    fixed = 0
    skipped = 0
    for error in open_errors:
        if FIX_ACTIONS.get(error["check_name"]) == "download_only":
            skipped += 1
            continue
        try:
            resolution = apply_fix(error)
            resolve_error(error["id"], resolution)
            fixed += 1
        except Exception:
            skipped += 1

    return jsonify({"status": "ok", "fixed": fixed, "skipped": skipped})


@ops_bp.route("/ops/errors/download")
def ops_errors_download():
    """Download error report as markdown."""
    from quayside.db import get_error_log
    from quayside.error_actions import generate_error_markdown

    errors = get_error_log()
    date_str = _date_type.today().isoformat()
    md_content = generate_error_markdown(errors, date_str)
    filename = f"quayside-errors-{date_str}.md"

    return send_file(
        io.BytesIO(md_content.encode("utf-8")),
        mimetype="text/markdown",
        as_attachment=True,
        download_name=filename,
    )
