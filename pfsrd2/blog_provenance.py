"""Paizo blog image provenance crawler (Community Use Policy groundwork).

Pass 1 (this module): crawl the Paizo blog post by post, cache HTML in
pfsrd2-web, download every content image, and write one JSON provenance
sidecar per image into pfsrd2-data/blog_images/<year>/<post-slug>/.

Pass 2 (later): classify each image — what it depicts, and whether it is
CUP-eligible (photographs are excluded from the policy).

The blog is a Nuxt SSR app: year archives paginate via ?page=N and post
bodies live in <article id="open-blog-article">. Publish dates only exist
in the obfuscated NUXT state blob, so we record the archive year plus any
ISO date candidates found in the page for pass 2 to refine.
"""

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

BLOG_ROOT = "https://paizo.com/blog"
USER_AGENT = (
    "pfsrd2-provenance-crawler/1.0 (CUP compliance research; " "contact: devon.jones@gmail.com)"
)
CRAWL_DELAY_S = 1.5
FIRST_YEAR = 2004

# Site chrome / non-content imagery, never provenance-worthy.
_SKIP_IMAGE_PAT = re.compile(r"/image/navigation/|/image/site/|favicon|paizo-?logo", re.I)
_ISO_DATE_PAT = re.compile(r'"(\d{4}-\d{2}-\d{2}T[0-9:.]+Z?)"')
_SLUG_PAT = re.compile(r'href="/blog/([a-z0-9][a-z0-9-]*)"')
_NON_POST_SLUGS = {"tags"}


def _get(url, binary=False, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "")
                return (data, ctype) if binary else (data.decode("utf-8", "replace"), ctype)
        except Exception as exc:  # noqa: BLE001 — retried, then surfaced
            last = exc
            time.sleep(CRAWL_DELAY_S * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last}")


def _polite_sleep():
    time.sleep(CRAWL_DELAY_S)


def enumerate_posts(state, log=print):
    """Walk every year archive, recording slug -> year in state["posts"].

    Stops a year when a page adds no new slugs (the archive tail repeats
    recent global posts, so absence of NEW slugs is the only reliable end).
    """
    posts = state.setdefault("posts", {})
    done_years = set(state.setdefault("enumerated_years", []))
    current_year = datetime.now(UTC).year
    for year in range(FIRST_YEAR, current_year + 1):
        # Re-enumerate the current year every run; finished years are stable.
        if year in done_years and year != current_year:
            continue
        page = 1
        year_slugs = set()
        while True:
            url = f"{BLOG_ROOT}/{year}" + (f"?page={page}" if page > 1 else "")
            html, _ = _get(url)
            _polite_sleep()
            found = {
                s for s in _SLUG_PAT.findall(html) if s not in _NON_POST_SLUGS and not s.isdigit()
            }
            new = found - year_slugs - set(posts)
            year_slugs |= found
            for slug in new:
                posts[slug] = year
            log(f"  {year} page {page}: +{len(new)} (year total {len(year_slugs)})")
            if not new:
                break
            page += 1
        if year != current_year:
            done_years.add(year)
            state["enumerated_years"] = sorted(done_years)
    return posts


def fetch_post(slug, cache_dir):
    """Fetch (or reuse) a post's HTML; returns the cached path."""
    path = Path(cache_dir) / f"{slug}.html"
    if path.exists() and path.stat().st_size > 0:
        return path, False
    html, _ = _get(f"{BLOG_ROOT}/{slug}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    _polite_sleep()
    return path, True


def _canonical_image_url(src):
    """Strip size/crop params; force https; drop :443."""
    src = src.replace("cdn.paizo.com:443", "cdn.paizo.com")
    parts = urllib.parse.urlsplit(src)
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def extract_post(html):
    """Pull title, tags, content images, and date candidates from post HTML."""
    soup = BeautifulSoup(html, "html.parser")
    out = {"title": None, "tags": [], "images": [], "dates_seen": []}

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        out["title"] = re.sub(r"\s*\|\s*Paizo Blog\s*$", "", og["content"]).strip()

    article = soup.find("article", id="open-blog-article")
    if article is None:
        return out

    for a in article.select('a[href^="/blog/tags/"]'):
        tag = a["href"].rsplit("/", 1)[-1]
        if tag and tag not in out["tags"]:
            out["tags"].append(tag)

    for img in article.find_all("img"):
        src = img.get("src") or ""
        if not src or _SKIP_IMAGE_PAT.search(src):
            continue
        if src.startswith("data:"):
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = "https://paizo.com" + src
        # figure/caption context if present
        caption = None
        fig = img.find_parent("figure")
        if fig:
            fc = fig.find("figcaption")
            if fc:
                caption = fc.get_text(" ", strip=True)
        out["images"].append(
            {
                "url": _canonical_image_url(src),
                "raw_src": src,
                "alt": (img.get("alt") or "").strip() or None,
                "caption": caption,
            }
        )

    out["dates_seen"] = sorted(set(_ISO_DATE_PAT.findall(html)))[:10]
    return out


def _safe_basename(url):
    name = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "image"
    return name


def harvest_post(slug, year, cache_dir, data_dir, state, log=print):
    """Extract + download a post's images and write provenance sidecars."""
    path, _fetched = fetch_post(slug, cache_dir)
    info = extract_post(path.read_text())
    seen_names = set()
    written = 0
    for im in info["images"]:
        base = _safe_basename(im["url"])
        # Same basename twice in one post: qualify with a short URL hash.
        if base in seen_names:
            h = hashlib.sha256(im["url"].encode()).hexdigest()[:8]
            stem, dot, ext = base.rpartition(".")
            base = f"{stem or ext}-{h}{dot}{ext if stem else ''}"
        seen_names.add(base)

        out_dir = Path(data_dir) / "blog_images" / str(year) / slug
        img_path = out_dir / base
        sidecar = out_dir / (base + ".json")
        if sidecar.exists():
            continue

        try:
            data, ctype = _get(im["url"], binary=True)
        except RuntimeError as exc:
            log(f"  WARN image fetch failed: {im['url']}: {exc}")
            state.setdefault("image_failures", []).append(
                {"post": slug, "url": im["url"], "error": str(exc)}
            )
            continue
        _polite_sleep()

        out_dir.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(data)
        sidecar_obj = {
            "type": "blog_image",
            "name": base,
            "image": base,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "content_type": ctype.split(";")[0].strip() or None,
            "provenance": {
                "post_slug": slug,
                "post_url": f"{BLOG_ROOT}/{slug}",
                "post_title": info["title"],
                "post_year": year,
                "post_tags": info["tags"],
                "image_url": im["url"],
                "raw_src": im["raw_src"],
                "alt": im["alt"],
                "caption": im["caption"],
                "dates_seen": info["dates_seen"],
            },
            "license": {
                "policy": "Paizo Community Use Policy",
                "policy_url": "https://paizo.com/licenses/communityuse",
                "notes": (
                    "Blog-published artwork is CUP-eligible; photographs are "
                    "not. Eligibility classification pending (pass 2)."
                ),
            },
            "subject": None,
            "crawled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        sidecar.write_text(json.dumps(sidecar_obj, indent=1, ensure_ascii=False) + "\n")
        written += 1
    return written, len(info["images"])
