#!/usr/bin/env python3
"""Refresh the "latest videos" strip on iamhaera.com from the YouTube feed.

Haera posts the same clips to Instagram and YouTube, so YouTube alone covers
both. Instagram is deliberately not touched: pulling posts from it needs
scraping, which is a banned technique on this account (see the global rules).

Two things about the feed, both measured on 2026-08-03:
  * Sending a browser User-Agent gets a 404 and `curl/8.x` gets a 500. Sending
    nothing, or a plain library UA, gets a 200. Do not "fix" the UA.
  * The feed rate-limits by IP and starts answering 404 after repeated calls.
    That is why a failure here must never rewrite the page — see below.

Failure policy: if the feed cannot be read, exit non-zero WITHOUT touching any
file, so the last good markup stays live and the scheduled run reports red.
A silent pass that quietly blanks the strip would be worse than no automation.
"""

import html
import os
import re
import sys
import time
import urllib.error
import urllib.request

FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCLiDANnccVee5j5qJJKKoog"
PLAYLIST = "https://www.youtube.com/playlist?list=PLF5GEJxFsh_KoZZ4o6_fbfipXW_5FpMtx"
MAX_ITEMS = 3

# The strip lives between these markers; everything else on the page is authored
# by hand and must survive untouched.
START = "<!-- AUTO:latest:start -->"
END = "<!-- AUTO:latest:end -->"

PAGES = [
    ("index.html", "최근 영상", "유튜브에서 더 보기 ↗"),
    ("en/index.html", "LATEST", "MORE ON YOUTUBE ↗"),
]


def fetch(url, attempts=4):
    """Read the feed, retrying with backoff. Raises if every attempt fails."""
    last = None
    for i in range(attempts):
        try:
            # A plain library UA is what the feed actually accepts.
            req = urllib.request.Request(url, headers={"User-Agent": "python-urllib/3"})
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
            if "<entry>" in body:
                return body
            last = f"200 but no <entry> (len {len(body)})"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001 - report whatever the network did
            last = repr(e)
        if i < attempts - 1:
            wait = 20 * (i + 1)
            print(f"  attempt {i+1} failed ({last}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"feed unreadable after {attempts} attempts: {last}")


# Cover uploads are titled "<song> (cover by 해라)", sometimes followed by
# " | <mood>" — a mood line Haera writes herself. Anchoring on the marker is
# what makes the split reliable: some titles carry their own pipe *before* it
# ("Seori - Full moon | 이두나 ost (cover by 해라)"), so splitting on the first
# pipe would mistake the OST note for a mood.
COVER = re.compile(r"^(?P<song>.*?)\(\s*cover\s+by\s+해라\s*\)(?P<rest>.*)$", re.I | re.S)


def parse(feed):
    """Return the newest cover uploads as (video_id, song, mood).

    Only covers are shown: they are the sit-down performances the site is meant
    to surface, and restricting to them also filters out vertical clips, which
    letterbox badly in the 16:9 cards and do not always carry a #shorts tag.
    """
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", feed, re.S):
        title = html.unescape(re.search(r"<title>(.*?)</title>", entry, re.S).group(1)).strip()
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry).group(1)

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
    if not out:
        raise SystemExit("feed had no cover uploads to show")
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
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"reading {FEED}", flush=True)
    videos = parse(fetch(FEED))
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
