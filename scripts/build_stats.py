"""GitHub stats cards for README.md, made from GitHub's own API.

Runs in .github/workflows/snake.yml ("Contribution animations") with the token GitHub gives every
workflow - no personal token and no third-party stats service that can go down or rate-limit - and
writes three pictures that are published to the `output` branch next to the snake:

  stats/overview.svg    stars, commits, pull requests, issues, public repos and followers
  stats/languages.svg   top languages across my public, non-fork repositories
  stats/streak.svg      total contributions, current streak and longest streak

Only public data is used (private repositories are never read). If GitHub's API fails, the script
writes nothing and the workflow keeps the previous cards. Uses only the Python standard library.

    GITHUB_TOKEN=... python scripts/build_stats.py --user DHURJATI-JS --out dist/stats
    python scripts/build_stats.py --sample --out /tmp/stats      # made-up numbers, no network
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
# Tokyo Night colours, like the rest of the README's cards
BG, TITLE, LABEL, VALUE, MUTED, ICON, ACCENT = "#1a1b27", "#70a5fd", "#a9b1d6", "#c0caf5", "#565f89", "#bf91f3", "#38bdae"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

REPOS_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    login name createdAt
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
      }
    }
  }
}"""

YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions totalPullRequestContributions totalIssueContributions
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
  }
}"""


# --------------------------------------------------------------------- data --
def graphql(query: str, variables: dict, token: str) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json", "User-Agent": "profile-stats-cards"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("errors"):
        raise RuntimeError("; ".join(str(e.get("message", "?")) for e in data["errors"])[:300])
    return data["data"]


def collect(login: str, token: str) -> dict:
    stars = forks = 0
    langs: dict[str, list] = {}  # name -> [bytes, colour]
    after = None
    while True:
        user = graphql(REPOS_QUERY, {"login": login, "after": after}, token)["user"]
        repos = user["repositories"]
        for repo in repos["nodes"]:
            stars += repo["stargazerCount"]
            forks += repo["forkCount"]
            for edge in repo["languages"]["edges"]:
                entry = langs.setdefault(edge["node"]["name"], [0, edge["node"]["color"] or "#8b949e"])
                entry[0] += edge["size"]
        if not repos["pageInfo"]["hasNextPage"]:
            break
        after = repos["pageInfo"]["endCursor"]

    now = datetime.now(timezone.utc)
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    totals = {"commits": 0, "prs": 0, "issues": 0, "contributions": 0}
    days: dict[str, int] = {}
    for year in range(created.year, now.year + 1):  # GitHub answers one year at a time
        start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        c = graphql(YEAR_QUERY, {"login": login, "from": start.isoformat(), "to": end.isoformat()},
                    token)["user"]["contributionsCollection"]
        totals["commits"] += c["totalCommitContributions"]
        totals["prs"] += c["totalPullRequestContributions"]
        totals["issues"] += c["totalIssueContributions"]
        totals["contributions"] += c["contributionCalendar"]["totalContributions"]
        for week in c["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = max(days.get(day["date"], 0), day["contributionCount"])
    return {"login": user["login"], "name": user["name"] or user["login"], "followers": user["followers"]["totalCount"],
            "repos": repos["totalCount"], "stars": stars, "forks": forks, "langs": langs, "days": days,
            "since": created.date().isoformat(), "today": now.date().isoformat(), **totals}


def streaks(days: dict[str, int], today: str) -> dict:
    """Current streak (today may still be empty) and longest streak, with their dates."""
    end = date.fromisoformat(today)
    active = {d for d, n in days.items() if n > 0}
    cursor = end if end.isoformat() in active else end - timedelta(days=1)
    current_end, current = cursor, 0
    while cursor.isoformat() in active:
        current += 1
        cursor -= timedelta(days=1)
    longest, best = 0, (None, None)
    run, run_start = 0, None
    for d in sorted(active):
        day = date.fromisoformat(d)
        if run and day == previous + timedelta(days=1):
            run += 1
        else:
            run, run_start = 1, day
        previous = day
        if run > longest:
            longest, best = run, (run_start, day)
    return {"current": current, "current_range": (current_end - timedelta(days=current - 1), current_end) if current else None,
            "longest": longest, "longest_range": best if longest else None}


def sample() -> dict:
    today = date(2026, 11, 28)
    days = {(today - timedelta(days=i)).isoformat(): (0 if i in (12, 13, 40) else 1 + i % 5) for i in range(120)}
    return {"login": "DHURJATI-JS", "name": "Dhurjati Sharma", "followers": 12, "repos": 31, "stars": 47, "forks": 6,
            "commits": 1834, "prs": 41, "issues": 17, "contributions": 2210, "since": "2021-03-02",
            "today": today.isoformat(), "days": days,
            "langs": {"Python": [910_000, "#3572A5"], "JavaScript": [420_000, "#f1e05a"], "HTML": [260_000, "#e34c26"],
                      "CSS": [130_000, "#663399"], "PowerShell": [40_000, "#012456"], "Shell": [20_000, "#89e051"],
                      "Dockerfile": [9_000, "#384d54"], "Jupyter Notebook": [5_000, "#DA5B0B"]}}


# ------------------------------------------------------------------ drawing --
def nice(n: int) -> str:
    return f"{n:,}"


def day_label(d: date | None) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}" if d else ""


def svg(width: int, height: int, title: str, body: str) -> str:
    label = escape(title, {'"': "&quot;"})
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="{label}">\n'
            f"<title>{escape(title)}</title>\n"
            f"<style>\n"
            f"  .t {{ font: 600 18px {FONT}; fill: {TITLE} }}\n"
            f"  .l {{ font: 600 14px {FONT}; fill: {LABEL} }}\n"
            f"  .v {{ font: 700 14px {FONT}; fill: {VALUE} }}\n"
            f"  .big {{ font: 700 28px {FONT}; fill: {VALUE} }}\n"
            f"  .s {{ font: 400 12px {FONT}; fill: {MUTED} }}\n"
            f"  .a {{ font: 700 14px {FONT}; fill: {ACCENT} }}\n"
            f"  .row {{ opacity: 0; animation: in .5s ease-out forwards }}\n"
            f"  @keyframes in {{ from {{ opacity: 0; transform: translateX(-6px) }} to {{ opacity: 1; transform: none }} }}\n"
            f"  @media (prefers-reduced-motion: reduce) {{ .row {{ animation: none; opacity: 1 }} }}\n"
            f"</style>\n"
            f'<rect x="0.5" y="0.5" rx="12" width="{width - 1}" height="{height - 1}" fill="{BG}"/>\n'
            f"{body}</svg>\n")


# Small hand-drawn icons (14 x 14), so the cards need no icon font or emoji support.
ICONS = {
    "star": '<path d="M7 0.8l1.9 3.9 4.3.6-3.1 3 .7 4.3L7 10.6l-3.8 2 .7-4.3-3.1-3 4.3-.6z"/>',
    "commit": '<circle cx="7" cy="7" r="3.2" fill="none" stroke-width="1.6"/><path d="M0 7h3.8M10.2 7H14" stroke-width="1.6"/>',
    "pr": '<circle cx="3" cy="2.6" r="2" fill="none" stroke-width="1.5"/><circle cx="3" cy="11.4" r="2" fill="none" stroke-width="1.5"/>'
          '<circle cx="11" cy="11.4" r="2" fill="none" stroke-width="1.5"/><path d="M3 4.6v4.8M11 9.4V5.5Q11 3 8.5 3H6.5" fill="none" stroke-width="1.5"/>',
    "issue": '<circle cx="7" cy="7" r="5.8" fill="none" stroke-width="1.6"/><circle cx="7" cy="7" r="1.6"/>',
    "repo": '<rect x="2" y="0.8" width="10" height="12.4" rx="1.6" fill="none" stroke-width="1.6"/><path d="M5 4h4M5 7h4" stroke-width="1.6"/>',
    "people": '<circle cx="5" cy="4" r="2.6"/><path d="M0.5 13c0-3 2-4.6 4.5-4.6S9.5 10 9.5 13z"/>'
              '<circle cx="10.5" cy="4.6" r="2.1" opacity=".7"/><path d="M10 8.6c2.4 0 3.8 1.5 3.8 4.4H10.8" opacity=".7"/>',
}


def icon(name: str, x: float, y: float) -> str:
    return (f'<g transform="translate({x} {y})" fill="{ICON}" stroke="{ICON}" stroke-linecap="round">'
            f"{ICONS[name]}</g>")


def overview_card(s: dict) -> str:
    rows = [("star", "Stars earned", s["stars"]), ("commit", "Commits", s["commits"]), ("pr", "Pull requests", s["prs"]),
            ("issue", "Issues", s["issues"]), ("repo", "Public repos", s["repos"]), ("people", "Followers", s["followers"])]
    body = [f'<text x="25" y="38" class="t">{escape(s["name"])} · GitHub stats</text>']
    for i, (ico, label, value) in enumerate(rows):
        x = 25 if i < 3 else 262
        y = 76 + (i % 3) * 30
        body.append(f'<g class="row" style="animation-delay:{i * 120}ms">{icon(ico, x, y - 12)}'
                    f'<text x="{x + 24}" y="{y}" class="l">{label}:</text>'
                    f'<text x="{x + 205}" y="{y}" class="v" text-anchor="end">{nice(value)}</text></g>')
    body.append(f'<text x="25" y="176" class="s">Counted since {escape(day_label(date.fromisoformat(s["since"])))}'
                f' · updated {escape(day_label(date.fromisoformat(s["today"])))}</text>')
    return svg(495, 195, f"{s['name']}: GitHub stats", "\n".join(body) + "\n")


def languages_card(s: dict, top: int = 6) -> str:
    items = sorted(s["langs"].items(), key=lambda kv: kv[1][0], reverse=True)
    total = sum(v[0] for _, v in items) or 1
    shown = [(name, size, colour) for name, (size, colour) in items[:top]]
    rest = sum(v[0] for _, v in items[top:])
    if rest:
        shown.append(("Other", rest, "#8b949e"))
    body = ['<text x="25" y="38" class="t">Top languages</text>']
    cx, cy, r = 82, 112, 44
    circumference = 2 * math.pi * r
    offset = 0.0
    if not shown:
        body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{MUTED}" stroke-width="18"/>')
    for name, size, colour in shown:
        length = circumference * size / total
        body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{escape(colour)}" stroke-width="18" '
                    f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" stroke-dashoffset="{-offset:.2f}" '
                    f'transform="rotate(-90 {cx} {cy})"/>')
        offset += length
    for i, (name, size, colour) in enumerate(shown):
        y = 66 + i * 18
        body.append(f'<g class="row" style="animation-delay:{i * 90}ms"><circle cx="160" cy="{y - 4}" r="5" fill="{escape(colour)}"/>'
                    f'<text x="172" y="{y}" class="s" style="fill:{LABEL}">{escape(name)}</text>'
                    f'<text x="325" y="{y}" class="s" text-anchor="end">{100 * size / total:.1f}%</text></g>')
    return svg(350, 195, "Top languages", "\n".join(body) + "\n")


def streak_card(s: dict) -> str:
    st = streaks(s["days"], s["today"])
    since = date.fromisoformat(s["since"])

    def span(rng) -> str:
        if not rng:
            return "No streak yet"
        a, b = rng
        if a == b:
            return day_label(a)
        if a.year == b.year:  # shorter: "17 Nov – 28 Nov 2026"
            return f"{a.day} {MONTHS[a.month - 1]} – {day_label(b)}"
        return f"{day_label(a)} – {day_label(b)}"

    columns = [
        (82, nice(s["contributions"]), "Total contributions", f"{day_label(since)} – now", False),
        (247, nice(st["current"]), "Current streak", span(st["current_range"]), True),
        (412, nice(st["longest"]), "Longest streak", span(st["longest_range"]), False),
    ]
    body = []
    for i, (x, value, label, sub, ring) in enumerate(columns):
        if ring:
            body.append(f'<circle cx="{x}" cy="72" r="40" fill="none" stroke="{ACCENT}" stroke-width="5" opacity=".85"/>')
        y_value = 84 if ring else 80
        body.append(f'<g class="row" style="animation-delay:{i * 150}ms">'
                    f'<text x="{x}" y="{y_value}" class="big" text-anchor="middle">{escape(value)}</text>'
                    f'<text x="{x}" y="{142}" class="{"a" if ring else "l"}" text-anchor="middle">{label}</text>'
                    f'<text x="{x}" y="{164}" class="s" text-anchor="middle">{escape(sub)}</text></g>')
    body.append(f'<path d="M165 30v135M330 30v135" stroke="{MUTED}" stroke-opacity=".5"/>')
    return svg(495, 195, f"{s['name']}: contribution streak", "\n".join(body) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default=os.environ.get("USERNAME") or "DHURJATI-JS")
    parser.add_argument("--out", default="dist/stats")
    parser.add_argument("--sample", action="store_true", help="draw made-up numbers (no network)")
    args = parser.parse_args()
    if args.sample:
        stats = sample()
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            print("No GITHUB_TOKEN (the workflow passes its own); stats cards left as they were.")
            return 0
        try:
            stats = collect(args.user, token)
        except Exception as exc:  # noqa: BLE001 - API hiccup: keep the previous cards
            print(f"Could not read GitHub's API ({type(exc).__name__}: {exc}); stats cards left as they were.")
            return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cards = {"overview.svg": overview_card(stats), "languages.svg": languages_card(stats), "streak.svg": streak_card(stats)}
    for name, text in cards.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"Stats cards written to {out}: {stats['contributions']} contributions, {stats['stars']} stars, "
          f"{len(stats['langs'])} languages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
