#!/usr/bin/env python3
"""Build a real, repository-owned contribution dashboard from git history."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


REPOS = {
    "Tennisd": {"slug": "tennisd", "url": "https://github.com/Snowstormme/tennisd"},
    "Movie Finder": {"slug": "movie-finder", "url": "https://github.com/Snowstormme/movie-finder"},
    "Lotus": {"slug": "lotus", "url": "https://github.com/Snowstormme/lotus"},
}


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.DEVNULL)


def read_version(repo: Path) -> str:
    for relative in ("VERSION", "campus-app/VERSION"):
        candidate = repo / relative
        if candidate.exists():
            value = candidate.read_text(encoding="utf-8").strip()
            if value:
                return value
    package = repo / "campus-app/package.json"
    if package.exists():
        try:
            value = json.loads(package.read_text(encoding="utf-8")).get("version")
            if value:
                return str(value)
        except json.JSONDecodeError:
            pass
    return "unversioned"


def commits(repo: Path, start: date, end: date) -> list[dict[str, str]]:
    raw = run(
        "git", "log", "--all", f"--since={start.isoformat()}T00:00:00Z",
        f"--until={end.isoformat()}T23:59:59Z", "--format=%aI%x09%H%x09%s", cwd=repo,
    )
    rows = []
    for line in raw.splitlines():
        stamp, commit_hash, subject = line.split("\t", 2)
        committed = datetime.fromisoformat(stamp).astimezone(timezone.utc).date()
        rows.append({"date": committed.isoformat(), "sha": commit_hash, "subject": subject})
    return rows


def esc(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def level(total: int, maximum: int) -> int:
    if not total or not maximum:
        return 0
    ratio = total / maximum
    return 1 if ratio <= .25 else 2 if ratio <= .5 else 3 if ratio <= .75 else 4


def build_svg(data: dict, output: Path) -> None:
    start = date.fromisoformat(data["start"])
    end = date.fromisoformat(data["end"])
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    by_date = data["days"]
    maximum = max((row["total"] for row in by_date.values()), default=0)
    colors = ["#17251f", "#1f513d", "#2f7a55", "#c28b2c", "#d34b5f"]
    width, height = 1180, 360
    left, top, cell, gap = 42, 126, 13, 4
    grid_x = left + 38
    grid_y = top
    # Align the first column to Sunday, like GitHub's native calendar.
    first = days[0] - timedelta(days=(days[0].weekday() + 1) % 7)
    weeks = ((end - first).days // 7) + 1
    summary = f'{data["total_commits"]} commits' if data["total_commits"] else "No commits"
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        '<title>Snowstormme contribution cockpit</title>',
        '<desc>Real commit activity from Tennisd, Movie Finder and Lotus. Hover a cell for the date and commits.</desc>',
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#07111f"/><stop offset="1" stop-color="#111827"/></linearGradient></defs>',
        f'<rect width="{width}" height="{height}" rx="22" fill="url(#bg)"/>',
        '<text x="34" y="42" fill="#f8fafc" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="23" font-weight="700">Contribution cockpit</text>',
        f'<text x="34" y="68" fill="#94a3b8" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="13">{esc(summary)} · {esc(data["start"])} — {esc(data["end"])} · hover cells for details</text>',
        '<rect x="34" y="88" width="1112" height="238" rx="17" fill="#0f172a" stroke="#263449"/>',
    ]
    for index, label in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
        svg.append(f'<text x="{left}" y="{grid_y + index * (cell + gap) + 10}" fill="#64748b" font-family="sans-serif" font-size="10">{label}</text>')
    month_seen = set()
    for offset in range((weeks * 7)):
        day = first + timedelta(days=offset)
        if day < start or day > end:
            continue
        week = (day - first).days // 7
        row = (day.weekday() + 1) % 7
        x = grid_x + week * (cell + gap)
        y = grid_y + row * (cell + gap)
        details = by_date[day.isoformat()]
        title = f'{day.isoformat()} — {details["total"]} commit' + ("s" if details["total"] != 1 else "")
        if details["repos"]:
            title += " · " + ", ".join(f'{name}: {count}' for name, count in details["repos"].items())
        svg.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{colors[level(details["total"], maximum)]}"><title>{esc(title)}</title></rect>')
        month_key = (day.year, day.month)
        if day.day <= 7 and month_key not in month_seen:
            svg.append(f'<text x="{x}" y="{grid_y - 10}" fill="#64748b" font-family="sans-serif" font-size="10">{day.strftime("%b")}</text>')
            month_seen.add(month_key)
    legend_x = 1000
    svg.append('<text x="34" y="309" fill="#b8c6bd" font-family="sans-serif" font-size="11">Less</text>')
    for index, color in enumerate(colors):
        svg.append(f'<rect x="{legend_x + index * 19}" y="299" width="12" height="12" rx="3" fill="{color}"/>')
    svg.append('<text x="1100" y="309" fill="#b8c6bd" font-family="sans-serif" font-size="11">More</text>')
    svg.append('</svg>')
    output.write_text("\n".join(svg), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True, help="directory containing checked out source repositories")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=args.days - 1)
    all_commits: list[dict[str, str]] = []
    repo_data = []
    daily = { (start + timedelta(days=i)).isoformat(): {"total": 0, "repos": {}} for i in range(args.days) }
    for name, meta in REPOS.items():
        repo = args.sources / meta["slug"]
        rows = commits(repo, start, end)
        for row in rows:
            daily[row["date"]]["total"] += 1
            daily[row["date"]]["repos"][name] = daily[row["date"]]["repos"].get(name, 0) + 1
        latest = rows[0] if rows else {"date": None, "subject": None, "sha": None}
        repo_data.append({"name": name, "slug": meta["slug"], "url": meta["url"], "version": read_version(repo), "commits": len(rows), "latest": latest})
        all_commits.extend(rows)
    data = {"generated_at": datetime.now(timezone.utc).isoformat(), "start": start.isoformat(), "end": end.isoformat(), "total_commits": len(all_commits), "repositories": repo_data, "days": daily}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "activity-data.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    build_svg(data, args.output / "contribution-graph.svg")
    print(json.dumps({"total_commits": len(all_commits), "start": start.isoformat(), "end": end.isoformat(), "repositories": repo_data}, ensure_ascii=False))


if __name__ == "__main__":
    main()
