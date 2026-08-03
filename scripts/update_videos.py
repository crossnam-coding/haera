#!/usr/bin/env python3
"""Refresh the "latest videos" strip on iamhaera.com from the YouTube feed.

Haera posts the same clips to Instagram and YouTube, so YouTube alone covers
both. Instagram is deliberately not touched: pulling posts from it needs
scraping, which is a banned technique on this account (see the global rules).

Reads through the YouTube Data API rather than the RSS feed. Measured
2026-08-03: the RSS endpoint answers 404/500 from GitHub's data-centre IPs
(it serves fine from a home connection), so a scheduled run could never use it.
The API works from anywhere with a key, and returns the whole upload history
instead of the last 15 items, so covers are far easier to find.

The key lives in the YOUTUBE_API_KEY secret. It only reads public data, so it
does not need to belong to the channel owner.

Failure policy: if the API cannot be read, exit non-zero WITHOUT touching any
file, so the last good markup stays live and the scheduled run reports red.
A silent pass that quietly blanks the strip would be worse than no automation.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CHANNEL = "UCLiDANnccVee5j5qJJKKoog"
# Every channel's uploads live in a playlist whose id is the channel id with
# the leading "UC" swapped for "UU".
UPLOADS = "UU" + CHANNEL[2:]
API = "https://www.googleapis.com/youtube/v3/playlistItems"
PLAYLIST = "https://www.youtube.com/playlist?list=PLF5GEJxFsh_KoZZ4o6_fbfipXW_5FpMtx"
MAX_ITEMS = 3
# Covers are a minority of the uploads (most are shorts), so scan a couple of
# pages before giving up rather than only the newest handful.
MAX_SCAN = 100

# The strip lives between these markers; everything else on the page is authored
# by hand and must survive untouched.
START = "<!-- AUTO:latest:start -->"
END = "<!-- AUTO:latest:end -->"

PAGES = [
    ("index.html", "최근 영상", "유튜브에서 더 보기 ↗"),
    ("en/index.html", "LATEST", "MORE ON YOUTUBE ↗"),
]


def call(key, page=None, attempts=3):
    """One page of uploads, retrying with backoff. Raises if all attempts fail."""
    params = {
        "part": "snippet",
        "playlistId": UPLOADS,
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
            # Never let the key reach the log.
            body = re.sub(r"AIza[0-9A-Za-z_-]{30,}", "<key>", e.read().decode("utf-8", "replace"))
            reason = re.search(r'"reason":\s*"([A-Za-z_]+)"', body)
            last = f"HTTP {e.code} ({reason.group(1) if reason else 'unknown'})"
        except Exception as e:  # noqa: BLE001 - report whatever the network did
            last = type(e).__name__
        if i < attempts - 1:
            wait = 15 * (i + 1)
            print(f"  attempt {i+1} failed ({last}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"YouTube API unreadable after {attempts} attempts: {last}")


def fetch(key):
    """Walk the uploads playlist until enough covers turn up."""
    videos, scanned, page = [], 0, None
    while scanned < MAX_SCAN:
        data = call(key, page)
        items = data.get("items", [])
        if not items:
            break
        scanned += len(items)
        videos.extend(items)
        found = pick(videos)
        if len(found) >= MAX_ITEMS:
            return found
        page = data.get("nextPageToken")
        if not page:
            break
    found = pick(videos)
    if not found:
        raise SystemExit(f"no cover uploads found in the newest {scanned} videos")
    return found


# Cover uploads are titled "<song> (cover by 해라)", sometimes followed by
# " | <mood>" — a mood line Haera writes herself. Anchoring on the marker is
# what makes the split reliable: some titles carry their own pipe *before* it
# ("Seori - Full moon | 이두나 ost (cover by 해라)"), so splitting on the first
# pipe would mistake the OST note for a mood.
COVER = re.compile(r"^(?P<song>.*?)\(\s*cover\s+by\s+해라\s*\)(?P<rest>.*)$", re.I | re.S)


def pick(items):
    """Return the newest cover uploads as (video_id, song, mood).

    Only covers are shown: they are the sit-down performances the site is meant
    to surface, and restricting to them also filters out vertical clips, which
    letterbox badly in the 16:9 cards and do not always carry a #shorts tag.
    """
    out = []
    for item in items:
        snip = item.get("snippet", {})
        title = html.unescape(snip.get("title", "")).strip()
        vid = snip.get("resourceId", {}).get("videoId")
        if not vid:
            continue

        if re.search(r"#shorts?\b", title, re.I):
            continue
        m = COVER.match(title)
        if not m:
            continue

        song = re.sub(r"#\S+", "", m.group("song")).strip(" -–|·")
        # A leftover pipe inside the song name ("Full moon | 이두나 ost") is a
        # separator she typed, not a mood boundary; render it as a middle dot.
        song = re.sub(r"\s*\|\s*", " · ", song).strip(" ·")
        mood = re.sub(r"#\S+", "", m.group("rest")).strip(" -–|·")
        if not song:
            continue
        out.append((vid, song, mood))
        if len(out) == MAX_ITEMS:
            break
    return out


def card(vid, title, mood):
    """One video card. The accent line is only drawn when a mood line exists —
    repeating the song title in both slots reads as a rendering bug."""
    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    caption = html.escape(title)
    accent = (
        '<span style="display:block; margin-top:10px; font-family:var(--font-heading); '
        'font-weight:800; font-size:11px; letter-spacing:0.1em; color:var(--color-accent-700);">'
        f'{html.escape(mood)}</span>'
        if mood
        else ""
    )
    gap = "4px" if mood else "10px"
    return (
        f'<a data-vid href="https://www.youtube.com/watch?v={vid}" target="_blank" rel="noopener" '
        'style="text-decoration:none; color:var(--color-text);">'
        '<span style="position:relative; display:block; overflow:hidden; '
        'border:2px solid var(--color-text); aspect-ratio:16/9;">'
        f'<img data-photo src="{thumb}" alt="{caption}" '
        'style="width:100%; height:100%; object-fit:cover; filter:grayscale(1) contrast(1.05); '
        'transition:filter .6s ease, transform .6s ease;"></span>'
        f'{accent}'
        f'<span style="display:block; margin-top:{gap}; font-size:13px; line-height:1.6; '
        'color:color-mix(in srgb,var(--color-text) 70%,transparent);">'
        f'{caption}</span></a>'
    )


def block(videos, heading, more):
    cards = "\n        ".join(card(*v) for v in videos)
    return f"""{START}
    <div style="margin-top:clamp(28px,4vw,44px);">
      <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:16px;">
        <h3 style="font-family:var(--font-heading); font-weight:800; font-size:12px; letter-spacing:0.12em; color:var(--color-accent-700); margin:0;">{heading}</h3>
        <a href="{PLAYLIST}" target="_blank" rel="noopener" style="font-family:var(--font-heading); font-weight:800; font-size:11px; letter-spacing:0.1em; color:color-mix(in srgb,var(--color-text) 55%,transparent); text-decoration:none;">{more}</a>
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:16px;">
        {cards}
      </div>
    </div>
    {END}"""


def main():
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise SystemExit("YOUTUBE_API_KEY is not set (repo secret of the same name)")

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"reading uploads playlist {UPLOADS} via the YouTube Data API", flush=True)
    videos = fetch(key)
    for vid, title, mood in videos:
        print(f"  {vid}  {title}" + (f"  [{mood}]" if mood else ""), flush=True)

    changed = []
    for name, heading, more in PAGES:
        path = os.path.join(root, name)
        page = open(path, encoding="utf-8").read()
        if START not in page or END not in page:
            raise SystemExit(f"{name}: markers missing; refusing to guess where the strip goes")
        new = re.sub(
            re.escape(START) + r".*?" + re.escape(END),
            lambda _m: block(videos, heading, more),
            page,
            flags=re.S,
        )
        if new != page:
            open(path, "w", encoding="utf-8").write(new)
            changed.append(name)

    print("updated: " + (", ".join(changed) if changed else "nothing (already current)"))
    # Signal to the workflow whether a commit is needed.
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    sys.exit(main())
