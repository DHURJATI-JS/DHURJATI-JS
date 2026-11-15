"""Rebuild the auto-updating parts of README.md from my portfolio site.

Reads https://my-website-three-mu-29.vercel.app/api/projects (the site already AI-analyses
every public repo) and rewrites two marked regions of README.md:

  <!-- PROJECTS:START --> ... <!-- PROJECTS:END -->   project cards, grouped like the site
  <!-- STACK:START -->    ... <!-- STACK:END -->      tools used in projects that the
                                                      hand-written tech stack doesn't list yet

Projects listed in readme/overrides.json keep their hand-written name, emoji, text and badges.
New public projects get a card from the site's AI summary, at the top of their group.
Hidden projects (site /admin) never appear. Uses only the Python standard library.

    python scripts/build_readme.py                  # update README.md in place
    python scripts/build_readme.py --source x.json  # use a saved /api/projects response
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
API = "https://my-website-three-mu-29.vercel.app/api/projects"
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


def render_projects(projects: list[dict], cfg: dict) -> tuple[str, int]:
    skip = {s.lower() for s in cfg.get("skip", [])}
    overrides = {k.lower(): v for k, v in cfg.get("projects", {}).items()}
    order = {g: [n.lower() for n in names] for g, names in cfg.get("order", {}).items()}

    ai, other = [], []
    for p in projects:
        if p["name"].lower() in skip or p.get("archived"):
            continue
        (ai if (p["name"].lower() in overrides or is_ai(p)) else other).append(p)

    parts, count = [], 0
    for key, heading, cols, default_emoji in GROUPS:
        members = [p for p in ai if (p.get("category") or "industry") == key]
        if not members:
            continue
        known = order.get(key, [])
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
        parts.append(f"### {heading}\n\n<table>\n" + "\n".join(rows) + "\n</table>")
        count += len(cells)

    if other:
        lines = []
        for p in sorted(other, key=lambda p: p.get("created_at") or "", reverse=True):
            url = p.get("html_url") or f"https://github.com/{OWNER}/{p['name']}"
            text = first_sentences(p.get("summary") or p.get("description") or "", 140)
            lines.append(f"- [**{short_title(p)}**]({url}) · {text}".rstrip(" ·"))
        parts.append("### 🧰 More projects\n\n" + "\n".join(lines))
        count += len(other)
    return "\n\n".join(parts), count


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
    if new_text == text:
        print("README already up to date.")
    else:
        README.write_text(new_text, encoding="utf-8")
        print(f"README updated: {count} project entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
