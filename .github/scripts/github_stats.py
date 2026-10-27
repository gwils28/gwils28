"""Render the GitHub cards of the profile README.

Draws, in light and dark, the activity card (assets/stats-*.svg) and the
recent repositories block (assets/recent-*.svg, assets/repo-N-*.svg), with the
same palette and fonts as the other cards (Mousse scheme from gwils28.github.io).
The README block between the recent-repos markers is rewritten so each card
links to its repository. Data comes from the GraphQL API; fonts are subset by
Google Fonts and inlined, because GitHub renders README images without loading
any external resource.

Standard library only, so the workflow needs no install step.
    GITHUB_TOKEN=... python .github/scripts/github_stats.py
"""

import base64
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("STATS_USER", "gwils28")
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets"
README = ROOT / "README.md"
MARKERS = ("<!-- recent-repos:start -->", "<!-- recent-repos:end -->")

# The profile and the website repos are already linked everywhere else.
REPO_IGNORE = {USER, f"{USER}.github.io"}
REPO_COUNT = 6
LANG_LABEL = {"Jupyter Notebook": "Notebook"}

# Notebooks store outputs and base64 images: counted at full weight they
# would bury every other language under bytes that are not code.
LANG_WEIGHT = {"Jupyter Notebook": 0.1}
LANG_IGNORE = {"Makefile", "Dockerfile", "Procfile"}

THEMES = {
    "light": {
        "bg": "#FFFFFF", "border": "#D7DDD5", "tile": "#F7F8F6",
        "text": "#0F110D", "body": "#3B4338", "muted": "#687463", "kicker": "#9B5E0D",
        "accent": "#2E6218", "arrow_bg": "#E4F2DE", "tag_bg": "#FDF0D3", "tag_fg": "#9B5E0D",
        "langs": ["#2E6218", "#54A630", "#9B5E0D", "#EC9C13", "#9FD18A", "#919C8B"],
    },
    "dark": {
        "bg": "#181D16", "border": "#272D25", "tile": "#0F110D",
        "text": "#F7F8F6", "body": "#B5BEB1", "muted": "#919C8B", "kicker": "#F3B73F",
        "accent": "#73C251", "arrow_bg": "#1B390E", "tag_bg": "#5C330A", "tag_fg": "#F3B73F",
        "langs": ["#73C251", "#418523", "#F3B73F", "#C57D11", "#C9E5BD", "#687463"],
    },
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    recent: repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 10,
                         orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { name url description pushedAt primaryLanguage { name } }
    }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

W, PAD = 1200, 48
INNER = W - 2 * PAD
MONO_ADV = 0.6  # IBM Plex Mono advance width, in em
# Rough average advances, in em, to wrap and fit proportional text.
ADV = {"mono": MONO_ADV, "heading": 0.6, "sans": 0.52}
CARD_W, CARD_H = 612, 252


def graphql(token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def font_face(name, family, weight, text):
    """Inline a Google Fonts subset holding only the glyphs of `text`."""
    query = urllib.parse.urlencode({"family": f"{family}:wght@{weight}", "text": "".join(sorted(set(text)))})
    ua = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
    with urllib.request.urlopen(urllib.request.Request(f"https://fonts.googleapis.com/css2?{query}", headers=ua)) as r:
        css = r.read().decode()
    url = re.search(r"src:\s*url\(([^)]+)\)", css).group(1)
    with urllib.request.urlopen(urllib.request.Request(url, headers=ua)) as r:
        b64 = base64.b64encode(r.read()).decode()
    return f"@font-face{{font-family:'{name}';src:url(data:font/woff2;base64,{b64}) format('woff2');}}"


def streaks(days):
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] else 0
        longest = max(longest, run)
    # Today still counts as "in progress": a streak only breaks on a past day.
    tail = days[:-1] if days and not days[-1]["contributionCount"] else days
    current = 0
    for d in reversed(tail):
        if not d["contributionCount"]:
            break
        current += 1
    return current, longest


def languages(repos):
    sizes = Counter()
    for repo in repos:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            if name not in LANG_IGNORE:
                sizes[name] += e["size"] * LANG_WEIGHT.get(name, 1)
    total = sum(sizes.values()) or 1
    top = sizes.most_common(5)
    rest = total - sum(s for _, s in top)
    rows = [(n, s / total) for n, s in top]
    if rest / total >= 0.005:
        rows.append(("Other", rest / total))
    return rows


def collect(user):
    cc = user["contributionsCollection"]
    weeks = cc["contributionCalendar"]["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    current, longest = streaks(days)
    return {
        "kpis": [
            (f"{cc['contributionCalendar']['totalContributions']:,}", "contributions"),
            (f"{cc['totalCommitContributions']:,}", "commits"),
            (f"{cc['totalPullRequestContributions'] + cc['totalPullRequestReviewContributions']:,}", "pull requests & reviews"),
            (f"{longest} d", f"longest streak · now {current} d"),
        ],
        "langs": languages(user["repositories"]["nodes"]),
        "updated": dt.date.fromisoformat(days[-1]["date"]),
        "repos": [r for r in user["recent"]["nodes"] if r["name"] not in REPO_IGNORE][:REPO_COUNT],
    }


def wrap(s, font, size, width, lines):
    """Greedy word wrap on estimated widths; the last kept line ends with an ellipsis."""
    per_line = int(width / (size * ADV[font]))
    out, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > per_line:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: per_line - 1].rstrip(" ,.:;") + "…"
    return out


def text(x, y, s, font, size, fill, anchor="start", spacing=None):
    ls = f' letter-spacing="{spacing}"' if spacing is not None else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}"{ls}>{escape(s)}</text>')


def svg(w, h, title, used, fonts, body):
    style = "".join(fonts(name, chars) for name, chars in used.items() if chars)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h:.0f}" width="{w}" height="{h:.0f}" role="img">'
            f"<title>{escape(title)}</title><style>{style}</style>" + "".join(body) + "</svg>")


def canvas():
    """A list of SVG elements plus the characters drawn in each font, for subsetting."""
    out, used = [], {"heading": "", "mono": "", "sans": ""}

    def put(x, y, s, font, size, fill, anchor="start", spacing=None):
        used[font] += s
        out.append(text(x, y, s, font, size, fill, anchor, spacing))

    return out, used, put


def render_recent_header(data, t, fonts):
    """Slim section title above the repository cards."""
    out, used, put = canvas()
    h = 96
    out.append(f'<rect x="1" y="1" width="{W - 2}" height="{h - 2}" rx="24" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="2"/>')
    put(PAD, 60, "Recent repositories", "heading", 34, t["text"], spacing=-0.5)
    tag = "LAST PUSHED FIRST · UPDATED DAILY"
    tag_w = len(tag) * (14 * MONO_ADV + 1.2) + 28
    out.append(f'<rect x="{W - PAD - tag_w:.1f}" y="33" width="{tag_w:.1f}" height="30" rx="15" fill="{t["tag_bg"]}"/>')
    put(W - PAD - tag_w + 14, 53, tag, "mono", 14, t["tag_fg"], spacing=1.2)
    return svg(W, h, "Recent repositories, last pushed first, updated daily", used, fonts, out)


def render_repo(repo, t, fonts):
    """One repository, drawn like the navigation cards: tag, name, description, arrow."""
    out, used, put = canvas()
    out.append('<g transform="translate(6 6)">')
    out.append(f'<rect x="1" y="1" width="{CARD_W - 14}" height="{CARD_H - 14}" rx="20" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="2"/>')
    lang = (repo["primaryLanguage"] or {}).get("name")
    pushed = dt.date.fromisoformat(repo["pushedAt"][:10])
    tag = " · ".join(filter(None, [LANG_LABEL.get(lang, lang), pushed.strftime("%d %b %Y")])).upper()
    tag_w = len(tag) * (14 * MONO_ADV + 1.2) + 28
    out.append(f'<rect x="36" y="34" width="{tag_w:.1f}" height="30" rx="15.0" fill="{t["tag_bg"]}"/>')
    put(50, 54, tag, "mono", 14, t["tag_fg"], spacing=1.2)

    # Long snake_case names shrink to fit rather than wrap.
    width = CARD_W - 12 - 72
    size = min(36, width / (len(repo["name"]) * ADV["heading"]))
    put(36, 118, repo["name"], "heading", round(size, 1), t["text"], spacing=-0.5)
    desc = repo["description"] or "No description yet."
    for i, line in enumerate(wrap(desc, "sans", 18, width, 3)):
        put(36, 158 + i * 26, line, "sans", 18, t["body"] if repo["description"] else t["muted"])

    out.append(f'<circle cx="542" cy="58" r="26" fill="{t["arrow_bg"]}"/>')
    out.append(f'<path d="M531 58h22M545 49l9 9-9 9" fill="none" stroke="{t["accent"]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    out.append("</g>")
    return svg(CARD_W, CARD_H, f"{repo['name']}: {desc}", used, fonts, out)


def readme_block(repos):
    lines = [MARKERS[0], "<p>"]
    lines.append('  <picture><source media="(prefers-color-scheme: dark)" srcset="assets/recent-dark.svg">'
                 '<img src="assets/recent-light.svg" width="100%" alt="Recent repositories, last pushed first, updated daily"></picture>')
    for i, r in enumerate(repos, 1):
        alt = escape(f"{r['name']}: {r['description'] or 'no description yet'}", {'"': "&quot;"})
        lines.append(f'  <a href="{r["url"]}"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/repo-{i}-dark.svg">'
                     f'<img src="assets/repo-{i}-light.svg" width="49%" alt="{alt}"></picture></a>')
    lines += ["</p>", MARKERS[1]]
    return "\n".join(lines)


def render(data, t, fonts):
    out, used, put = canvas()

    # Header: title on the left, refresh date as an amber tag on the right.
    put(PAD, 66, "GitHub activity", "heading", 34, t["text"], spacing=-0.5)
    tag = f"UPDATED {data['updated'].strftime('%d %b %Y').upper()}"
    tag_w = len(tag) * (14 * MONO_ADV + 1.2) + 28
    out.append(f'<rect x="{W - PAD - tag_w:.1f}" y="40" width="{tag_w:.1f}" height="30" rx="15" fill="{t["tag_bg"]}"/>')
    put(W - PAD - tag_w + 14, 60, tag, "mono", 14, t["tag_fg"], spacing=1.2)

    # KPI tiles
    gap, y0, h = 16, 100, 104
    tw = (INNER - 3 * gap) / 4
    for i, (value, label) in enumerate(data["kpis"]):
        x = PAD + i * (tw + gap)
        out.append(f'<rect x="{x:.1f}" y="{y0}" width="{tw:.1f}" height="{h}" rx="14" fill="{t["tile"]}" stroke="{t["border"]}" stroke-width="1.5"/>')
        put(x + 22, y0 + 54, value, "heading", 40, t["accent"])
        put(x + 22, y0 + 84, label, "mono", 16, t["muted"])

    # Languages: one stacked bar, then a mono legend that wraps.
    y = 262
    put(PAD, y, "LANGUAGES · PUBLIC REPOS", "mono", 15, t["kicker"], spacing=1.2)
    y += 22
    out.append(f'<clipPath id="bar"><rect x="{PAD}" y="{y}" width="{INNER}" height="14" rx="7"/></clipPath><g clip-path="url(#bar)">')
    x = PAD
    for (name, share), color in zip(data["langs"], t["langs"]):
        out.append(f'<rect x="{x:.1f}" y="{y}" width="{INNER * share + 1:.1f}" height="14" fill="{color}"/>')
        x += INNER * share
    out.append("</g>")
    x, y = PAD, y + 48
    for (name, share), color in zip(data["langs"], t["langs"]):
        label = f"{name} {share * 100:.0f}%" if share >= 0.01 else f"{name} <1%"
        width = 22 + len(label) * 17 * MONO_ADV
        if x + width > W - PAD:
            x, y = PAD, y + 32
        out.append(f'<circle cx="{x + 6}" cy="{y - 5}" r="6" fill="{color}"/>')
        put(x + 20, y, label, "mono", 17, t["text"])
        x += width + 32

    height = y + 40
    title = "GitHub activity: " + ", ".join(f"{v} {l}" for v, l in data["kpis"]) + "; languages: " + \
        ", ".join(f"{n} {s * 100:.0f}%" for n, s in data["langs"])
    frame = f'<rect x="1" y="1" width="{W - 2}" height="{height - 2:.0f}" rx="24" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="2"/>'
    return svg(W, height, title, used, fonts, [frame] + out)


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    data = collect(graphql(token))
    families = {"heading": ("Archivo", 800), "mono": ("IBM Plex Mono", 400), "sans": ("IBM Plex Sans", 400)}
    cards = {"stats": lambda t, f: render(data, t, f), "recent": lambda t, f: render_recent_header(data, t, f)}
    for i, repo in enumerate(data["repos"], 1):
        cards[f"repo-{i}"] = lambda t, f, repo=repo: render_repo(repo, t, f)

    # All cards share one subset per font, so the files differ only in colours.
    chars = {n: "" for n in families}
    for draw in cards.values():
        draw(THEMES["light"], lambda n, c: chars.__setitem__(n, chars[n] + c) or "")
    faces = {n: font_face(n, *families[n], c) for n, c in chars.items() if c}
    for name, draw in cards.items():
        for theme in THEMES:
            (OUT / f"{name}-{theme}.svg").write_text(draw(THEMES[theme], lambda n, c: faces[n]), encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    start, end = readme.index(MARKERS[0]), readme.index(MARKERS[1]) + len(MARKERS[1])
    README.write_text(readme[:start] + readme_block(data["repos"]) + readme[end:], encoding="utf-8")
    print(f"wrote {len(cards)} cards ({data['kpis'][0][0]} contributions, "
          f"repos: {', '.join(r['name'] for r in data['repos'])})")


if __name__ == "__main__":
    main()
