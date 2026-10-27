"""Render the GitHub activity card of the profile README.

Draws assets/stats-light.svg and assets/stats-dark.svg with the same palette
and fonts as the other cards (Mousse scheme from gwils28.github.io). Data comes
from the GraphQL API; fonts are subset by Google Fonts and inlined, because
GitHub renders README images without loading any external resource.

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
OUT = Path(__file__).resolve().parents[2] / "assets"

# Notebooks store outputs and base64 images: counted at full weight they
# would bury every other language under bytes that are not code.
LANG_WEIGHT = {"Jupyter Notebook": 0.1}
LANG_IGNORE = {"Makefile", "Dockerfile", "Procfile"}

THEMES = {
    "light": {
        "bg": "#FFFFFF", "border": "#D7DDD5", "tile": "#F7F8F6",
        "text": "#0F110D", "muted": "#687463", "kicker": "#9B5E0D",
        "accent": "#2E6218", "tag_bg": "#FDF0D3", "tag_fg": "#9B5E0D",
        "langs": ["#2E6218", "#54A630", "#9B5E0D", "#EC9C13", "#9FD18A", "#919C8B"],
    },
    "dark": {
        "bg": "#181D16", "border": "#272D25", "tile": "#0F110D",
        "text": "#F7F8F6", "muted": "#919C8B", "kicker": "#F3B73F",
        "accent": "#73C251", "tag_bg": "#5C330A", "tag_fg": "#F3B73F",
        "langs": ["#73C251", "#418523", "#F3B73F", "#C57D11", "#C9E5BD", "#687463"],
    },
}

QUERY = """
query($login: String!) {
  user(login: $login) {
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
    }


def text(x, y, s, font, size, fill, anchor="start", spacing=None):
    ls = f' letter-spacing="{spacing}"' if spacing is not None else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}"{ls}>{escape(s)}</text>')


def render(data, t, fonts):
    out = []
    used = {"heading": "", "mono": ""}

    def put(x, y, s, font, size, fill, anchor="start", spacing=None):
        used[font] += s
        out.append(text(x, y, s, font, size, fill, anchor, spacing))

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
    style = "".join(fonts(name, chars) for name, chars in used.items())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height:.0f}" width="{W}" height="{height:.0f}" role="img">'
            f"<title>{escape(title)}</title><style>{style}</style>"
            f'<rect x="1" y="1" width="{W - 2}" height="{height - 2:.0f}" rx="24" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="2"/>'
            + "".join(out) + "</svg>")


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    data = collect(graphql(token))
    families = {"heading": ("Archivo", 800), "mono": ("IBM Plex Mono", 400)}
    # Both themes share one subset per font, so the files differ only in colours.
    chars = {"heading": "", "mono": ""}
    for theme in THEMES:
        render(data, THEMES[theme], lambda n, c: chars.__setitem__(n, chars[n] + c) or "")
    faces = {n: font_face(n, *families[n], chars[n]) for n in families}
    for theme in THEMES:
        (OUT / f"stats-{theme}.svg").write_text(render(data, THEMES[theme], lambda n, c: faces[n]), encoding="utf-8")
    print(f"wrote stats-light.svg, stats-dark.svg ({data['kpis'][0][0]} contributions)")


if __name__ == "__main__":
    main()
