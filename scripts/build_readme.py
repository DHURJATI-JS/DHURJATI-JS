"""Rebuild the auto-updating parts of README.md from my portfolio site.

Reads https://my-website-three-mu-29.vercel.app/api/projects (the site already AI-analyses
every public repo) and /api/research, and rewrites three marked regions of README.md:

  <!-- RESEARCH:START --> ... <!-- RESEARCH:END -->   research-grade projects: one big card each,
                                                      validators first. Empty (nothing shown at
                                                      all) while the site's research section is
                                                      OFF or has no cards.
  <!-- PROJECTS:START --> ... <!-- PROJECTS:END -->   project cards, grouped like the site, with
                                                      the "Other" group always last
  <!-- STACK:START -->    ... <!-- STACK:END -->      tools used in projects that the
                                                      hand-written tech stack doesn't list yet

Projects listed in readme/overrides.json keep their hand-written name, emoji, text and badges.
New public projects get a card from the site's AI summary, at the top of their group.
Hidden and private projects never appear (the site only publishes public, visible repos).
Uses only the Python standard library.

    python scripts/build_readme.py                  # update README.md in place
    python scripts/build_readme.py --source x.json  # use a saved /api/projects response
    python scripts/build_readme.py --research-source r.json   # use a saved /api/research response
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OVERRIDES = ROOT / "readme" / "overrides.json"
SITE = "https://my-website-three-mu-29.vercel.app"
API = f"{SITE}/api/projects"
RESEARCH_API = f"{SITE}/api/research"
OWNER = "DHURJATI-JS"

# canonical key -> (label, colour, simple-icons logo or "")
BADGES: dict[str, tuple[str, str, str]] = {
    "python": ("Python", "3776AB", "python"),
    "javascript": ("JavaScript", "F7DF1E", "javascript"),
    "html": ("HTML", "E34F26", "html5"),
    "css": ("CSS", "1572B6", "css3"),
    "bash": ("Bash", "4EAA25", "gnubash"),
    "powershell": ("PowerShell", "5391FE", "powershell"),
    "fastapi": ("FastAPI", "009688", "fastapi"),
    "flask": ("Flask", "000000", "flask"),
    "postgresql": ("PostgreSQL", "4169E1", "postgresql"),
    "postgresql+pgvector": ("PostgreSQL + pgvector", "336791", "postgresql"),
    "pgvector": ("pgvector", "336791", "postgresql"),
    "redis": ("Redis", "DC382D", "redis"),
    "docker": ("Docker", "2496ED", "docker"),
    "nginx": ("Nginx", "009639", "nginx"),
    "tailwind": ("Tailwind CSS", "06B6D4", "tailwindcss"),
    "bootstrap": ("Bootstrap", "7952B3", "bootstrap"),
    "jinja2": ("Jinja2", "B41717", "jinja"),
    "sqlalchemy": ("SQLAlchemy", "D71F00", "sqlalchemy"),
    "socketio": ("Socket.IO", "010101", "socketdotio"),
    "sse": ("Server-Sent Events", "1a1b27", ""),
    "gemma": ("Gemma", "4285F4", "google"),
    "gemma3": ("Gemma 3", "4285F4", "google"),
    "llamacpp": ("llama.cpp", "1a1b27", ""),
    "vllm": ("vLLM", "30A2FF", ""),
    "ollama": ("Ollama", "000000", "ollama"),
    "claude": ("Claude", "D97757", "claude"),
    "openai": ("OpenAI API", "412991", "openai"),
    "whisper": ("Whisper", "412991", "openai"),
    "opencv": ("OpenCV", "5C3EE8", "opencv"),
    "mediapipe": ("MediaPipe", "0097A7", ""),
    "tesseract": ("Tesseract", "3c3c3c", ""),
    "applevision": ("Apple Vision", "000000", "apple"),
    "kokoro": ("Kokoro TTS", "6A5ACD", ""),
    "locust": ("Locust", "2E7D32", ""),
    "cloudflare": ("Cloudflare", "F38020", "cloudflare"),
    "vercel": ("Vercel", "000000", "vercel"),
    "githubapi": ("GitHub API", "181717", "github"),
    "windows": ("Windows", "0078D6", "windows"),
    "linux": ("Linux", "FCC624", "linux"),
    "macos": ("macOS", "000000", "apple"),
}

# how the site's AI may spell a tool -> canonical key (keys are lower-cased, no spaces/dots/dashes)
ALIASES = {
    "py": "python", "js": "javascript", "html5": "html", "css3": "css", "shell": "bash",
    "postgres": "postgresql", "postgresqlpgvector": "postgresql+pgvector", "tailwindcss": "tailwind",
    "mdbootstrap": "bootstrap", "mdbootstrap9": "bootstrap", "jinja": "jinja2", "socketio": "socketio",
    "serversentevents": "sse", "gemma3": "gemma3", "gemma312b": "gemma3", "llamacpp": "llamacpp",
    "openaiapi": "openai", "whisperv3turbo": "whisper", "ocrtesseract": "tesseract", "tesserocr": "tesseract",
    "tesseractocr": "tesseract", "applevisionocr": "applevision", "kokorotts": "kokoro", "githubrestapi": "githubapi",
    "claudeapi": "claude", "anthropic": "claude", "chatgpt": "openai",
}

# Not worth a badge (too generic, or concepts rather than tools).
IGNORE = {"oop", "json", "http", "https", "firewall", "batch", "api", "rest", "restapi", "webcam", "ai", "llm"}

# Already shown in the hand-written tech stack (so they don't go into the auto "also used" row).
IN_STACK = {
    "python", "javascript", "html", "css", "bash", "powershell", "fastapi", "flask", "postgresql",
    "postgresql+pgvector", "pgvector", "redis", "nginx", "tailwind", "bootstrap", "sqlalchemy", "jinja2",
    "socketio", "sse", "gemma", "gemma3", "llamacpp", "vllm", "ollama", "claude", "openai", "whisper",
    "opencv", "mediapipe", "tesseract", "applevision", "kokoro", "linux", "macos", "windows", "docker",
    "cloudflare", "vercel", "githubapi", "locust",
}

AI_TOOLS = {"gemma", "gemma3", "llamacpp", "vllm", "ollama", "claude", "openai", "whisper", "mediapipe",
            "tesseract", "opencv", "applevision", "kokoro"}
AI_WORDS = re.compile(r"\b(AI|LLMs?|machine learning|neural|GPT|Gemma|RAG)\b")

GROUPS = [("industry", "🚀 Industry & startup", 2, "✨"), ("social", "💚 Social impact", 3, "💡")]
# Projects moved to "Other" in the site's /admin (the AI never puts anything there). Always the LAST group.
OTHER_GROUP = ("other", "🧩 Other", 3, "🔹")

# Same validator types as the site's /admin research form.
VALIDATOR_KINDS = {
    "professor": "Professor / academic", "researcher": "Researcher", "industry": "Industry expert",
    "organisation": "Organisation / company", "institution": "University / institute",
    "government": "Government body", "peer_review": "Peer review", "user_study": "User study / field trial",
    "mentor": "Mentor / supervisor", "other": "Other",
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def canon(name: str) -> str:
    key = re.sub(r"[\s.\-_/()]", "", name.lower())
    return ALIASES.get(key, key)


def badge(key: str, style: str = "flat-square", fallback_label: str = "") -> str:
    label, colour, logo = BADGES.get(key, (fallback_label or key, "1a1b27", ""))
    text = label.replace("-", "--").replace("_", "__").replace(" ", "%20").replace("+", "%2B")
    logo_part = f"&logo={logo}&logoColor=white" if logo else ""
    return (f'<img src="https://img.shields.io/badge/{text}-{colour}?style={style}{logo_part}" '
            f'alt="{html.escape(label)}">')


def card_tech(project: dict) -> list[tuple[str, str]]:
    """Up to 4 (key, original name) badges for a card, most specific first."""
    out, seen = [], set()
    for name in project.get("tech") or []:
        key = canon(str(name))
        if key in IGNORE or key in seen or key in {"python", "html", "css", "javascript"}:
            continue
        seen.add(key)
        out.append((key, str(name)))
    return out[:4]


def first_sentences(text: str, limit: int = 230) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        if out and len(out) + 1 + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return out if out else text[:limit]


def is_ai(project: dict) -> bool:
    if any(canon(str(t)) in AI_TOOLS for t in project.get("tech") or []):
        return True
    blob = " ".join(str(project.get(k) or "") for k in ("title", "summary", "description"))
    return bool(AI_WORDS.search(blob))


def short_title(project: dict) -> str:
    title = (project.get("title") or project["name"]).strip()
    return title.split(":", 1)[0].strip() if ":" in title else title


def render_card(project: dict, override: dict | None, width: int) -> str:
    url = project.get("html_url") or f"https://github.com/{OWNER}/{project['name']}"
    if override:
        emoji = override.get("emoji", "")
        name = html.escape(override.get("name") or short_title(project))
        blurb = override.get("blurb", "")  # trusted, may contain simple HTML
        badges = " ".join(badge(k) for k in override.get("tech", []))
    else:
        emoji = project["_emoji"]
        name = html.escape(short_title(project))
        blurb = html.escape(first_sentences(project.get("summary") or project.get("description") or ""))
        badges = " ".join(badge(k, fallback_label=orig) for k, orig in card_tech(project))
    return (f'<td width="{width}%" valign="top">\n'
            f'<h3><a href="{html.escape(url)}">{emoji} {name}</a></h3>\n'
            f'{blurb}<br><br>\n{badges}\n</td>')


def render_group(members: list[dict], group: tuple, overrides: dict, known: list[str]) -> tuple[str, int]:
    key, heading, cols, default_emoji = group
    if not members:
        return "", 0
    new = sorted((p for p in members if p["name"].lower() not in known),
                 key=lambda p: p.get("created_at") or "", reverse=True)
    listed = sorted((p for p in members if p["name"].lower() in known),
                    key=lambda p: known.index(p["name"].lower()))
    width = 100 // cols
    cells = []
    for p in new + listed:
        p["_emoji"] = default_emoji
        cells.append(render_card(p, overrides.get(p["name"].lower()), width))
    rows = ["<tr>\n" + "\n".join(cells[i:i + cols]) + "\n</tr>" for i in range(0, len(cells), cols)]
    return f"### {heading}\n\n<table>\n" + "\n".join(rows) + "\n</table>", len(cells)


def render_projects(projects: list[dict], cfg: dict) -> tuple[str, int]:
    skip = {s.lower() for s in cfg.get("skip", [])}
    overrides = {k.lower(): v for k, v in cfg.get("projects", {}).items()}
    order = {g: [n.lower() for n in names] for g, names in cfg.get("order", {}).items()}

    ai, more, misc = [], [], []
    for p in projects:
        if p["name"].lower() in skip or p.get("archived"):
            continue
        if (p.get("category") or "industry") == OTHER_GROUP[0]:
            misc.append(p)  # chosen by hand in the site's /admin: always the last group
        elif p["name"].lower() in overrides or is_ai(p):
            ai.append(p)
        else:
            more.append(p)

    parts, count = [], 0
    for group in GROUPS:
        members = [p for p in ai if (p.get("category") or "industry") == group[0]]
        block, n = render_group(members, group, overrides, order.get(group[0], []))
        if block:
            parts.append(block)
            count += n

    if more:
        lines = []
        for p in sorted(more, key=lambda p: p.get("created_at") or "", reverse=True):
            url = p.get("html_url") or f"https://github.com/{OWNER}/{p['name']}"
            text = first_sentences(p.get("summary") or p.get("description") or "", 140)
            lines.append(f"- [**{short_title(p)}**]({url}) · {text}".rstrip(" ·"))
        parts.append("### 🧰 More projects\n\n" + "\n".join(lines))
        count += len(more)

    block, n = render_group(misc, OTHER_GROUP, overrides, order.get(OTHER_GROUP[0], []))
    if block:
        parts.append(block)  # "Other" is always the last group
        count += n
    return "\n\n".join(parts), count


def nice_date(value: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        return html.escape(value or "")
    return f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def safe_link(url: str) -> str:
    url = (url or "").strip()
    return html.escape(url, quote=True) if re.match(r"^https?://", url, re.I) else ""


def render_research(items: list[dict], public_names: set[str], cfg: dict) -> str:
    """One big full-width card per research-grade project, validators first. "" = show nothing."""
    overrides = {k.lower(): v for k, v in cfg.get("projects", {}).items()}
    cards = []
    for item in items:
        name = str(item.get("name") or "")
        if not name or name.lower() not in public_names:
            continue  # only repos the site publishes (public + visible): never private ones
        validators = [v for v in item.get("validators") or [] if isinstance(v, dict) and v.get("name")]
        if not validators:
            continue
        override = overrides.get(name.lower()) or {}
        title = html.escape(override.get("name") or short_title(item))
        url = safe_link(item.get("html_url")) or f"https://github.com/{OWNER}/{html.escape(name)}"
        lines = [f'<td width="100%" valign="top">',
                 f'<h3><a href="{url}">🔬 {title}</a> '
                 f'<img src="https://img.shields.io/badge/Research--grade-validated-0f766e?style=flat-square" '
                 f'alt="Research-grade, validated"></h3>']
        if item.get("topic"):
            lines.append(f'<b>Research topic:</b> {html.escape(item["topic"])}<br><br>')
        lines.append(f"✅ <b>Validated by ({len(validators)})</b>")
        lines.append("<ul>")
        for v in validators:
            bits = [f"<b>{html.escape(v['name'])}</b>", html.escape(VALIDATOR_KINDS.get(v.get("kind"), "Other"))]
            if v.get("organisation"):
                bits.append(html.escape(v["organisation"]))
            link = safe_link(v.get("link"))
            if link:
                bits.append(f'<a href="{link}">proof</a>')
            lines.append("<li>" + " · ".join(bits) + "</li>")
        lines.append("</ul>")
        if item.get("usage"):
            usage = "<br>".join(html.escape(line) for line in str(item["usage"]).splitlines() if line.strip())
            lines.append(f"🧪 <b>How it was used:</b> {usage}<br>")
        facts = []
        if item.get("where"):
            facts.append(f"📍 <b>Where:</b> {html.escape(item['where'])}")
        if item.get("when"):
            facts.append(f"🗓️ <b>When:</b> {nice_date(item['when'])}")
        if facts:
            lines.append(" &nbsp;·&nbsp; ".join(facts) + "<br>")
        lines.append("</td>")
        cards.append("<table>\n<tr>\n" + "\n".join(lines) + "\n</tr>\n</table>")
    if not cards:
        return ""
    return ("## 🔬 Research-grade projects\n\n"
            "<sub>Independently validated and used in real settings. Shown first.</sub>\n\n"
            + "\n\n".join(cards) + "\n\n---")


def render_stack_extras(projects: list[dict]) -> str:
    extra: dict[str, str] = {}
    for p in projects:
        for name in p.get("tech") or []:
            key = canon(str(name))
            if key and key not in IGNORE and key not in IN_STACK and key not in extra:
                extra[key] = str(name)
    if not extra:
        return ""
    badges = " ".join(badge(k, "for-the-badge", fallback_label=orig) for k, orig in sorted(extra.items()))
    return f"**Also used in my projects**\n\n{badges}"


def replace_region(text: str, name: str, body: str) -> str:
    pattern = re.compile(rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"README.md has no <!-- {name}:START --> / <!-- {name}:END --> markers")
    inner = f"\n{body}\n" if body else "\n"
    return pattern.sub(lambda m: m.group(1) + inner + m.group(3), text, count=1)


def load_research(source: str | None) -> list[dict]:
    """The site's research-grade projects ([] while its research section is OFF)."""
    if source:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        req = urllib.request.Request(RESEARCH_API, headers={"User-Agent": "profile-readme-builder", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    items = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("unexpected /api/research response")
    return [i for i in items if isinstance(i, dict)] if data.get("enabled") else []


def load_projects(source: str | None) -> list[dict]:
    if source:
        data = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        req = urllib.request.Request(API, headers={"User-Agent": "profile-readme-builder", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, list):
        raise ValueError("unexpected /api/projects response")
    return [p for p in projects if isinstance(p, dict) and p.get("name")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", help="read projects from this JSON file instead of the live site")
    parser.add_argument("--research-source", help="read research projects from this JSON file instead of the live site")
    args = parser.parse_args()

    try:
        projects = load_projects(args.source)
    except Exception as exc:  # noqa: BLE001 - site down: keep the README as it is
        print(f"Could not load projects ({exc}); README left unchanged.")
        return 0

    cfg = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    text = README.read_text(encoding="utf-8")
    previous = len(re.findall(r'<td width="\d+%" valign="top">', text.split("<!-- PROJECTS:START -->")[-1]
                              .split("<!-- PROJECTS:END -->")[0]))
    body, count = render_projects(projects, cfg)
    if previous and count < previous // 2:
        print(f"Only {count} projects (README has {previous}); the site may be mid-sync. Left unchanged.")
        return 0

    new_text = replace_region(text, "PROJECTS", body)
    new_text = replace_region(new_text, "STACK", render_stack_extras(projects))
    try:
        research = load_research(args.research_source)
    except Exception as exc:  # noqa: BLE001 - site down or older deploy: keep that part as it is
        print(f"Could not load research projects ({exc}); research section left unchanged.")
    else:
        public_names = {p["name"].lower() for p in projects}
        new_text = replace_region(new_text, "RESEARCH", render_research(research, public_names, cfg))
    if new_text == text:
        print("README already up to date.")
    else:
        README.write_text(new_text, encoding="utf-8")
        print(f"README updated: {count} project entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
