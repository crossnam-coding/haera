#!/usr/bin/env python3
"""Build the "every cover Haera has sung" list pages.

Why this page exists: measured 2026-08-03, the Google first page for queries
like "잔잔한 한국 인디 노래 추천" is made entirely of list-shaped content —
YouTube playlists, blog round-ups, editor picks, forum threads. Not one entry
is an artist's own site. An artist page answers "who is Haera"; it never
answers "what should I listen to". This page is the list-shaped content, on
our own domain, and every original artist named on it is a search entry point.

Data comes from the "커버해라" playlist through the YouTube Data API, so the
page never drifts from the channel and needs no hand maintenance.

Attribution rule: original artists are matched against the roster below, never
guessed from the title. Roughly a fifth of the titles put the song first
("송가 - 하현상", "Body - 다영"), so splitting on the dash would credit the
wrong name. A title that matches nothing is still listed — it just carries no
artist label. Inventing an attribution would be worse than omitting one.

Failure policy matches update_videos.py: on any API failure, exit non-zero
having written nothing, so the last good page stays live and the run goes red.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PLAYLIST_ID = "PLF5GEJxFsh_KoZZ4o6_fbfipXW_5FpMtx"
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"
API = "https://www.googleapis.com/youtube/v3/playlistItems"

# Videos the owner has hidden or removed still occupy a slot in the playlist's
# advertised count; the API hands them back with these placeholder titles.
# Measured 2026-08-03: the playlist header says 52, only 47 are watchable.
UNAVAILABLE = {"private video", "deleted video", "비공개 동영상", "삭제된 동영상"}

# Canonical name -> extra spellings that appear in her titles. The canonical
# form is what the page prints. Sourced from llms.txt's "음악적 이웃" roster.
ARTISTS = {
    "헤이즈 (Heize)": ["헤이즈", "heize", "hezie"],
    "백예린 (Yerin Baek)": ["백예린", "yerin baek"],
    "최유리": ["최유리"],
    "하현상": ["하현상"],
    "죠지 (George)": ["죠지"],
    "볼빨간사춘기 (Bolbbalgan4)": ["볼빨간사춘기", "볼빨간 사춘기"],
    "우효 (Oohyo)": ["우효"],
    "새소년 (SE SO NEON)": ["새소년"],
    "너드커넥션 (Nerd Connection)": ["너드커넥션"],
    "데이먼스 이어 (Damons Year)": ["데이먼스 이어"],
    "한로로": ["한로로"],
    "허회경": ["허회경"],
    "콜드 (Colde)": ["콜드", "colde"],
    "10cm": ["10cm", "십센치"],
    "윤마치": ["윤마치"],
    "서리 (Seori)": ["서리", "seori"],
    "SOLE (쏠)": ["sole", "쏠"],
    "아이유 (IU)": ["아이유", "iu"],
    "태연 (Taeyeon)": ["태연", "taeyeon"],
    "이하이 (Lee Hi)": ["이하이"],
    "르세라핌 (LE SSERAFIM)": ["르세라핌", "le sserafim"],
    "엔믹스 (NMIXX)": ["엔믹스", "nmixx"],
    "아이브 (IVE)": ["아이브", "ive"],
    "izna (이즈나)": ["izna", "이즈나"],
    "KiiiKiii (키키)": ["kiiikiii", "키키"],
    "하츠투하츠 (Hearts2Hearts)": ["하츠투하츠", "hearts2hearts"],
    "I.O.I (아이오아이)": ["아이오아이", "i.o.i", "ioi"],
    "자우림": ["자우림"],
    "김광석": ["김광석"],
    "김광진": ["김광진"],
    "다영 (Dayoung)": ["다영", "dayoung"],
}

COVER = re.compile(r"^(?P<song>.*?)\(\s*cover\s+by\s+해라\s*\)(?P<rest>.*)$", re.I | re.S)


def call(key, page=None, attempts=3):
    params = {
        "part": "snippet,status",
        "playlistId": PLAYLIST_ID,
        "maxResults": "50",
        "key": key,
    }
    if page:
        params["pageToken"] = page
    url = API + "?" + urllib.parse.urlencode(params)

    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = re.sub(r"AIza[0-9A-Za-z_-]{30,}", "<key>", e.read().decode("utf-8", "replace"))
            reason = re.search(r'"reason":\s*"([A-Za-z_]+)"', body)
            last = f"HTTP {e.code} ({reason.group(1) if reason else 'unknown'})"
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
        if i < attempts - 1:
            wait = 15 * (i + 1)
            print(f"  attempt {i+1} failed ({last}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"YouTube API unreadable after {attempts} attempts: {last}")


def fetch(key):
    """Every watchable item in the cover playlist, in playlist order."""
    out, page, slots = [], None, 0
    while True:
        data = call(key, page)
        for item in data.get("items", []):
            slots += 1
            snip = item.get("snippet", {})
            title = html.unescape(snip.get("title", "")).strip()
            vid = snip.get("resourceId", {}).get("videoId")
            privacy = item.get("status", {}).get("privacyStatus", "")
            # Two independent signals: the placeholder title, and the status
            # part. Either alone has been enough in testing, but a hidden video
            # that slipped through would publish a dead link.
            if not vid or title.lower() in UNAVAILABLE or privacy in ("private", "privacyStatusUnspecified"):
                continue
            out.append({"id": vid, "title": title})
        page = data.get("nextPageToken")
        if not page:
            break
    print(f"  playlist slots {slots} -> watchable {len(out)}", flush=True)
    if not out:
        raise SystemExit("cover playlist came back empty; refusing to publish a blank list")
    return out


STATS = "https://www.googleapis.com/youtube/v3/videos"


def by_reach(key, items):
    """Sort most-watched first.

    Playlist order is whatever the channel last dragged things into, which
    buries the covers that actually pull traffic — the rainy-day Heize cover
    is measured at 4,700 views against a 100-300 channel median. A reader who
    stops after five rows should be meeting those, not position 1.

    Ordering is a presentation nicety, so a statistics call that fails leaves
    playlist order in place and says so, rather than sinking the whole build.
    """
    views = {}
    for i in range(0, len(items), 50):
        chunk = items[i : i + 50]
        params = {"part": "statistics", "id": ",".join(x["id"] for x in chunk), "key": key}
        try:
            with urllib.request.urlopen(STATS + "?" + urllib.parse.urlencode(params), timeout=30) as r:
                for v in json.load(r).get("items", []):
                    views[v["id"]] = int(v.get("statistics", {}).get("viewCount", 0))
        except Exception as e:  # noqa: BLE001
            print(f"  view counts unavailable ({type(e).__name__}); keeping playlist order", flush=True)
            return items
    if not views:
        print("  view counts came back empty; keeping playlist order", flush=True)
        return items
    print(f"  ordering {len(views)} of {len(items)} by view count", flush=True)
    # Ties and any id the stats call skipped keep their playlist position.
    return sorted(items, key=lambda x: -views.get(x["id"], 0))


def split(title):
    """(artist, song) for a cover title. artist is None when nothing matches."""
    m = COVER.match(title)
    body = (m.group("song") if m else title)
    body = re.sub(r"#\S+", "", body).strip(" -–|·")

    def spans(text, alias):
        """Every occurrence of alias, ignoring ones glued inside a longer word."""
        low, out = text.lower(), []
        for mm in re.finditer(re.escape(alias.lower()), low):
            s, e = mm.span()
            before = low[s - 1] if s else " "
            after = low[e] if e < len(low) else " "
            # Only ASCII needs the guard: "ive" must not fire inside "give",
            # while Korean syllables carry their own boundaries.
            if (before.isalnum() and before.isascii()) or (after.isalnum() and after.isascii()):
                continue
            out.append((s, e))
        return out

    hit, best = None, 0
    for canon, aliases in ARTISTS.items():
        for alias in aliases:
            if spans(body, alias) and len(alias) > best:
                hit, best = canon, len(alias)
    if not hit:
        return None, body

    # Strip every spelling of the matched artist, not just the one that won:
    # titles routinely carry both ("헤이즈 (Heize) - 헤픈 우연"), and leaving
    # one behind puts the artist's name back into the song column.
    song = body
    for alias in sorted(ARTISTS[hit], key=len, reverse=True):
        for s, e in reversed(spans(song, alias)):
            song = song[:s] + "\0" + song[e:]
    song = song.replace("\0", " ")

    song = re.sub(r"\(\s*\)|（\s*）", " ", song)          # brackets left empty
    song = re.sub(r"\s*([-–|·,]\s*)+(?=[)\］])", "", song)  # separator hugging a bracket
    song = re.sub(r"(?<=[(\［])\s*([-–|·,]\s*)+", "", song)
    # A dash that only linked the name to a bracketed note now leads nowhere.
    song = re.sub(r"\s*([-–|·,]\s*)+(?=[(\［])", " ", song)
    song = re.sub(r"\s*\|\s*", " · ", song)
    song = re.sub(r"\s{2,}", " ", song)
    song = re.sub(r"^[\s\-–|·,]+|[\s\-–|·,]+$", "", song)
    # Drop a bracket whose partner was carried away with the artist name.
    if song.count("(") < song.count(")"):
        song = song.replace(")", "", song.count(")") - song.count("("))
    elif song.count("(") > song.count(")"):
        song = song + ")"
    song = re.sub(r"^[\s\-–|·,]+|[\s\-–|·,]+$", "", song).strip()
    return hit, (song or body)


def rows(items):
    out = []
    for it in items:
        artist, song = split(it["title"])
        out.append({"id": it["id"], "artist": artist, "song": song, "raw": it["title"]})
    return out


def jsonld(data, lang, count):
    items = [
        {
            "@type": "ListItem",
            "position": i,
            "url": f"https://www.youtube.com/watch?v={r['id']}",
            "name": (f"{r['artist']} - {r['song']}" if r["artist"] else r["song"]),
        }
        for i, r in enumerate(data, 1)
    ]
    name = (
        f"해라(Haera)가 부른 커버 {count}곡 전체 목록"
        if lang == "ko"
        else f"Every cover sung by Haera — all {count}"
    )
    desc = (
        "싱어송라이터 해라(Haera)가 유튜브 채널에서 부른 커버 곡 전체 목록입니다. 원곡자와 곡명, 영상 링크를 담았습니다."
        if lang == "ko"
        else "The complete list of songs Korean singer-songwriter Haera has covered on her YouTube channel, with the original artists and links."
    )
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": name,
            "description": desc,
            "numberOfItems": count,
            "itemListOrder": "https://schema.org/ItemListOrderDescending",
            "url": f"https://iamhaera.com/{'covers/' if lang == 'ko' else 'en/covers/'}",
            "itemListElement": items,
        },
        ensure_ascii=False,
        indent=2,
    )


TEXT = {
    "ko": {
        "lang": "ko",
        "title": "해라(Haera)가 부른 커버 {n}곡 전체 목록 — 원곡자별",
        "desc": "싱어송라이터 해라(Haera)가 부른 커버 {n}곡 전체 목록. 헤이즈, 백예린, 최유리, 아이유, 태연 등 원곡자와 영상 링크.",
        "canonical": "https://iamhaera.com/covers/",
        "alt": "/en/covers/",
        "altlabel": "EN",
        "home": "해라 공식 홈",
        "h1": "해라가 부른 커버 {n}곡",
        "lead": "싱어송라이터 해라(Haera)가 유튜브 채널 「커버해라」에서 부른 커버 전곡입니다. "
                "아래 원곡자를 좋아하는 분이라면 해라의 목소리도 맞을 수 있습니다.",
        "ownhead": "해라의 자작곡",
        "own": "커버가 아닌 해라 본인의 곡은 <a href=\"/\" style=\"color:var(--color-accent-700);\">공식 홈</a>에 있습니다 — "
               "‘Palette’(2026) · ‘별빛슈(Starry Choux)’(2025) · ‘겨울 그리고 봄’(2024) · ‘Midnight’(2021).",
        "artisthead": "커버한 원곡자 {a}팀",
        "listhead": "전체 목록",
        "col": ("#", "원곡자", "곡", "영상"),
        "watch": "보기 ↗",
        "playlist": "유튜브 재생목록에서 보기 ↗",
        "nomatch": "—",
        "updated": "이 목록은 유튜브 채널에서 자동으로 갱신됩니다.",
    },
    "en": {
        "lang": "en",
        "title": "Every cover sung by Haera — all {n}, by original artist",
        "desc": "The complete list of {n} songs Korean singer-songwriter Haera has covered, with original artists — Heize, Yerin Baek, IU, Taeyeon and more.",
        "canonical": "https://iamhaera.com/en/covers/",
        "alt": "/covers/",
        "altlabel": "KO",
        "home": "Haera official site",
        "h1": "Every cover Haera has sung — all {n}",
        "lead": "The complete set of covers Korean singer-songwriter Haera has performed on her YouTube playlist "
                "「커버해라」. If you like the original artists below, her voice may be for you.",
        "ownhead": "Her own songs",
        "own": "Haera's own releases are on the <a href=\"/en/\" style=\"color:var(--color-accent-700);\">official site</a> — "
               "‘Palette’ (2026) · ‘Starry Choux’ (2025) · ‘Winter and Spring’ (2024) · ‘Midnight’ (2021).",
        "artisthead": "{a} original artists covered",
        "listhead": "Full list",
        "col": ("#", "Original artist", "Song", "Video"),
        "watch": "Watch ↗",
        "playlist": "Open the YouTube playlist ↗",
        "nomatch": "—",
        "updated": "This list refreshes automatically from the YouTube channel.",
    },
}


def page(data, lang):
    t = TEXT[lang]
    n = len(data)
    artists = sorted({r["artist"] for r in data if r["artist"]})
    esc = html.escape

    chips = "\n      ".join(
        '<span style="display:inline-block; border:2px solid var(--color-text); padding:5px 11px; '
        'font-size:12px; line-height:1.2; margin:0 7px 7px 0;">' + esc(a) + "</span>"
        for a in artists
    )

    trs = []
    for i, r in enumerate(data, 1):
        artist = esc(r["artist"]) if r["artist"] else t["nomatch"]
        trs.append(
            '<tr style="border-bottom:1px solid color-mix(in srgb,var(--color-text) 20%,transparent);">'
            f'<td style="padding:11px 12px 11px 0; font-family:var(--font-heading); font-weight:800; '
            f'font-size:12px; color:color-mix(in srgb,var(--color-text) 45%,transparent); white-space:nowrap;">{i:02d}</td>'
            f'<td style="padding:11px 14px 11px 0; font-size:14px; white-space:nowrap;">{artist}</td>'
            f'<td style="padding:11px 14px 11px 0; font-size:14px; line-height:1.5;">{esc(r["song"])}</td>'
            f'<td style="padding:11px 0; white-space:nowrap;">'
            f'<a href="https://www.youtube.com/watch?v={r["id"]}" target="_blank" rel="noopener" '
            f'style="font-family:var(--font-heading); font-weight:800; font-size:11px; letter-spacing:0.08em; '
            f'color:var(--color-accent-700); text-decoration:none;">{t["watch"]}</a></td></tr>'
        )
    body = "\n        ".join(trs)

    return f"""<!DOCTYPE html>
<html lang="{t['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(t['title'].format(n=n))} | 해라 (Haera)</title>
<meta name="description" content="{esc(t['desc'].format(n=n))}">
<link rel="canonical" href="{t['canonical']}">
<link rel="alternate" hreflang="ko" href="https://iamhaera.com/covers/">
<link rel="alternate" hreflang="en" href="https://iamhaera.com/en/covers/">
<link rel="alternate" hreflang="x-default" href="https://iamhaera.com/covers/">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(t['title'].format(n=n))}">
<meta property="og:description" content="{esc(t['desc'].format(n=n))}">
<meta property="og:url" content="{t['canonical']}">
<meta property="og:image" content="https://iamhaera.com/img/haera-hero.jpg">
<meta property="og:site_name" content="해라 (Haera) 공식 사이트">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">
{jsonld(data, lang, n)}
</script>
<link rel="stylesheet" href="/modernist.css">
<style>
  body {{ margin:0; background:var(--color-bg); color:var(--color-text); font-family:var(--font-body); }}
  a {{ color:inherit; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:clamp(28px,6vw,72px) clamp(20px,5vw,48px) 64px; }}
  table {{ width:100%; border-collapse:collapse; }}
  @media (max-width:560px) {{
    td:nth-child(2) {{ white-space:normal !important; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <div style="display:flex; align-items:baseline; gap:20px; margin-bottom:clamp(24px,5vw,44px);">
    <a href="{'/' if lang == 'ko' else '/en/'}" style="font-family:var(--font-heading); font-weight:800; font-size:19px; letter-spacing:-0.01em; text-decoration:none;">HAERA</a>
    <a href="{'/' if lang == 'ko' else '/en/'}" style="font-size:13px; text-decoration:none; color:color-mix(in srgb,var(--color-text) 60%,transparent);">{esc(t['home'])}</a>
    <a href="{t['alt']}" hreflang="{'en' if lang == 'ko' else 'ko'}" style="margin-left:auto; font-size:13px; font-weight:600; text-decoration:none;">{t['altlabel']}</a>
  </div>

  <h1 style="font-family:var(--font-heading); font-weight:800; font-size:clamp(30px,6vw,60px); letter-spacing:-0.02em; line-height:1.05; margin:0 0 18px;">{esc(t['h1'].format(n=n))}</h1>
  <p style="max-width:62ch; font-size:15px; line-height:1.75; color:color-mix(in srgb,var(--color-text) 78%,transparent); margin:0 0 10px;">{t['lead']}</p>
  <p style="max-width:62ch; font-size:14px; line-height:1.7; color:color-mix(in srgb,var(--color-text) 62%,transparent); margin:0 0 34px;">{t['own']}</p>

  <h2 style="font-family:var(--font-heading); font-weight:800; font-size:12px; letter-spacing:0.12em; color:var(--color-accent-700); margin:0 0 14px;">{esc(t['artisthead'].format(a=len(artists)))}</h2>
  <div style="margin-bottom:38px;">
      {chips}
  </div>

  <h2 style="font-family:var(--font-heading); font-weight:800; font-size:12px; letter-spacing:0.12em; color:var(--color-accent-700); margin:0 0 8px;">{esc(t['listhead'])}</h2>
  <table>
    <thead>
      <tr style="border-bottom:2px solid var(--color-text);">
        <th style="text-align:left; padding:8px 12px 8px 0; font-family:var(--font-heading); font-weight:800; font-size:11px; letter-spacing:0.1em;">{esc(t['col'][0])}</th>
        <th style="text-align:left; padding:8px 14px 8px 0; font-family:var(--font-heading); font-weight:800; font-size:11px; letter-spacing:0.1em;">{esc(t['col'][1])}</th>
        <th style="text-align:left; padding:8px 14px 8px 0; font-family:var(--font-heading); font-weight:800; font-size:11px; letter-spacing:0.1em;">{esc(t['col'][2])}</th>
        <th style="text-align:left; padding:8px 0; font-family:var(--font-heading); font-weight:800; font-size:11px; letter-spacing:0.1em;">{esc(t['col'][3])}</th>
      </tr>
    </thead>
    <tbody>
        {body}
    </tbody>
  </table>

  <p style="margin:30px 0 0;">
    <a href="{PLAYLIST_URL}" target="_blank" rel="noopener" style="font-family:var(--font-heading); font-weight:800; font-size:12px; letter-spacing:0.1em; color:var(--color-accent-700); text-decoration:none;">{esc(t['playlist'])}</a>
  </p>
  <p style="margin:14px 0 0; font-size:12px; color:color-mix(in srgb,var(--color-text) 45%,transparent);">{esc(t['updated'])}</p>

</div>
</body>
</html>
"""


# The cover count also appears in prose elsewhere; keep those in step so the
# number can never contradict the list itself. llms.txt is read by machines as
# plain text, so the count is anchored on the surrounding sentence rather than
# wrapped in markers — a comment delimiter would just be noise mid-sentence.
COUNT_ANCHORS = [
    ("llms.txt", re.compile(r'(재생목록 "커버해라", 공개 )\d+(곡)')),
    ("llms.txt", re.compile(r'(playlist "커버해라", )\d+( public videos)')),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="render from a saved item dump instead of the API")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.from_json:
        raw = json.load(open(args.from_json, encoding="utf-8"))
        items = [{"id": r["id"], "title": r["title"]} for r in raw]
        print(f"rendering from {args.from_json}: {len(items)} items", flush=True)
    else:
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not key:
            raise SystemExit("YOUTUBE_API_KEY is not set (repo secret of the same name)")
        print(f"reading cover playlist {PLAYLIST_ID} via the YouTube Data API", flush=True)
        items = by_reach(key, fetch(key))

    data = rows(items)
    unmatched = [r for r in data if not r["artist"]]
    print(f"  {len(data)} covers, {len({r['artist'] for r in data if r['artist']})} artists, "
          f"{len(unmatched)} without an artist label", flush=True)
    for r in unmatched:
        print(f"    unlabelled: {r['raw']}", flush=True)

    # Check the prose anchors before writing anything. A silently frozen count
    # is the exact bug this page was built to end, so a missing anchor stops
    # the run while the site is still consistent.
    for name, pattern in COUNT_ANCHORS:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            raise SystemExit(f"{name} is missing; refusing to publish a count nothing can check")
        if not pattern.search(open(path, encoding="utf-8").read()):
            raise SystemExit(
                f"{name}: no text matches {pattern.pattern!r}, so the cover count would go stale. "
                "Update the pattern to match the new wording."
            )

    changed = []
    for lang, rel in (("ko", "covers/index.html"), ("en", "en/covers/index.html")):
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = page(data, lang)
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if new != old:
            open(path, "w", encoding="utf-8").write(new)
            changed.append(rel)

    for name, pattern in COUNT_ANCHORS:
        path = os.path.join(root, name)
        text = open(path, encoding="utf-8").read()
        new = pattern.sub(lambda m: f"{m.group(1)}{len(data)}{m.group(2)}", text)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            if name not in changed:
                changed.append(name)

    print("updated: " + (", ".join(changed) if changed else "nothing (already current)"))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    sys.exit(main())
