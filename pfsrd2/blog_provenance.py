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


# ---------------------------------------------------------------------------
# CMS-enriched path (Kontent delivery API)
#
# The blog is a Kontent (Kentico Cloud) app. Its delivery API exposes far
# richer provenance than the rendered HTML: real post dates, taxonomy tags,
# author, and — crucially — per-asset descriptions carrying artist
# attribution and a visual description ("Aleth, artist Sandra Posada : An
# image of Aleth ... human woman with dark skin ..."), plus inline
# creature/spell/item/feat references identifying what a post is about.
#
# Only a preview delivery key works (secure access is on); it ships in the
# site's JS bundle. We fetch it live at run time so no secret is committed,
# and filter to published posts (post_date <= now) to skip drafts/scheduled.
# ---------------------------------------------------------------------------

KONTENT_PROJECT_ID = "a7d62ac8-7f03-00ef-f1f0-83fb8bf332e2"
KONTENT_HOST = "https://preview-deliver.kontent.ai"
_TOKEN_PAT = re.compile(r'"(eyJ[A-Za-z0-9._-]{80,})"')
_NUXT_JS_PAT = re.compile(r'src="(/_nuxt/[a-z0-9]+\.js)"')


def fetch_delivery_token(log=print):
    """Scrape the preview delivery JWT from the live site JS bundle."""
    html, _ = _get(f"{BLOG_ROOT}/2020")
    for js in dict.fromkeys(_NUXT_JS_PAT.findall(html)):
        body, _ = _get(f"https://paizo.com{js}")
        for tok in _TOKEN_PAT.findall(body):
            # the delivery JWT decodes to an aud of *.deliver.kentico*
            if "deliver" in _jwt_aud(tok):
                log(f"  delivery token from {js}")
                return tok
    raise RuntimeError("could not locate Kontent delivery token in site bundle")


def _jwt_aud(token):
    import base64

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims.get("aud", "")
    except Exception:  # noqa: BLE001 — malformed candidate, just skip
        return ""


def _kontent_get(path_qs, token):
    url = f"{KONTENT_HOST}/{KONTENT_PROJECT_ID}/{path_qs}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — retried, then surfaced
            time.sleep(CRAWL_DELAY_S * (attempt + 2))
            last = exc
    raise RuntimeError(f"Kontent GET {url} failed: {last}")


def kontent_iter_posts(token, log=print):
    """Yield published blog_entry item dicts (with resolved modular_content).

    Paginates by skip/limit (no fragile server ordering); each yielded value
    is (item, modular_content). Filters to post_date <= now.
    """
    now = datetime.now(UTC)
    skip = 0
    limit = 20
    while True:
        data = _kontent_get(
            f"items?system.type=blog_entry&depth=3&limit={limit}&skip={skip}",
            token,
        )
        items = data.get("items") or []
        if not items:
            break
        mods = data.get("modular_content") or {}
        for it in items:
            pd = (it.get("elements", {}).get("post_date", {}) or {}).get("value")
            if pd:
                try:
                    when = datetime.fromisoformat(pd.replace("Z", "+00:00"))
                    if when > now:
                        continue  # scheduled/unpublished
                except ValueError:
                    pass
            yield it, mods
        skip += limit
        _polite_sleep()


_OBJECT_CODENAME_PAT = re.compile(r'data-codename="([^"]+)"')


def _referenced_codenames(elements):
    """Component codenames referenced by a set of elements.

    Modular-content elements list codenames directly; rich_text elements embed
    them as <object ... data-codename="X">.
    """
    names = set()
    for v in elements.values():
        t = v.get("type")
        if t == "modular_content":
            names.update(v.get("value") or [])
        elif t == "rich_text":
            names.update(_OBJECT_CODENAME_PAT.findall(v.get("value") or ""))
    return names


def _post_components(item, mods):
    """Resolve ONLY the components this post references (transitively).

    A batch response shares one modular_content map across every post in the
    page, so a post must be restricted to the components reachable from its
    own element references — otherwise it inherits sibling posts' images.
    """
    wanted = _referenced_codenames(item.get("elements", {}))
    resolved = {}
    frontier = list(wanted)
    while frontier:
        code = frontier.pop()
        if code in resolved or code not in mods:
            continue
        comp = mods[code]
        resolved[code] = comp
        frontier.extend(_referenced_codenames(comp.get("elements", {})))
    return resolved


def _asset_records(item, components):
    """Every distinct image asset in a post: url, name, description, ctype.

    Scans the post's own asset elements (thumbnail) plus only the components
    this post actually references.
    """
    seen = {}

    def add_assets(elements):
        for v in elements.values():
            if v.get("type") != "asset":
                continue
            for a in v.get("value") or []:
                url = _canonical_image_url(a["url"])
                ctype = a.get("type") or ""
                if url in seen or not ctype.startswith("image/"):
                    continue
                seen[url] = {
                    "url": url,
                    "name": a.get("name"),
                    "description": a.get("description"),
                    "content_type": ctype,
                }

    add_assets(item.get("elements", {}))
    for c in components.values():
        add_assets(c.get("elements", {}))
    return list(seen.values())


def _component_title(comp):
    """A readable title for an entity component, if it carries one."""
    for key in ("title", "name", "display_name", "creature_name"):
        v = comp.get("elements", {}).get(key)
        if v and isinstance(v.get("value"), str) and v["value"].strip():
            return v["value"].strip()
    return None


def _entity_refs(components):
    """Creature/spell/item/feat references among this post's components."""
    refs = []
    for c in components.values():
        t = c["system"]["type"]
        if any(k in t for k in ("creature", "spell", "item", "feat")):
            refs.append(
                {
                    "kind": t.split("___")[-1],
                    "title": _component_title(c),
                    "codename": c["system"]["codename"],
                }
            )
    return refs


def harvest_cms_post(item, mods, data_dir, state, log=print):
    """Download a post's CMS image assets and write enriched sidecars."""
    el = item["elements"]
    slug = el["url_slug"]["value"]
    post_date = (el.get("post_date", {}) or {}).get("value")
    year = int(post_date[:4]) if post_date else 0
    tags = [t["name"] for t in (el.get("tags", {}) or {}).get("value", [])]
    author_codes = [a for a in (el.get("author", {}) or {}).get("value", [])]
    title = item["system"]["name"]
    components = _post_components(item, mods)
    refs = _entity_refs(components)

    written = 0
    assets = _asset_records(item, components)
    for a in assets:
        base = _safe_basename(a["url"])
        out_dir = Path(data_dir) / "blog_images" / str(year or "undated") / slug
        sidecar = out_dir / (base + ".json")
        if sidecar.exists():
            continue
        try:
            data, ctype = _get(a["url"], binary=True)
        except RuntimeError as exc:
            log(f"  WARN image fetch failed: {a['url']}: {exc}")
            state.setdefault("image_failures", []).append(
                {"post": slug, "url": a["url"], "error": str(exc)}
            )
            continue
        _polite_sleep()

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / base).write_bytes(data)
        sidecar.write_text(
            json.dumps(
                {
                    "type": "blog_image",
                    "name": base,
                    "image": base,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "content_type": (ctype.split(";")[0].strip() or a["content_type"]) or None,
                    "provenance": {
                        "source": "kontent_cms",
                        "post_slug": slug,
                        "post_url": f"{BLOG_ROOT}/{slug}",
                        "post_title": title,
                        "post_year": year,
                        "post_date": post_date,
                        "post_tags": tags,
                        "post_authors": author_codes,
                        "image_url": a["url"],
                        "asset_name": a["name"],
                        "asset_description": a["description"],
                        "referenced_entities": refs,
                    },
                    "license": {
                        "policy": "Paizo Community Use Policy",
                        "policy_url": "https://paizo.com/licenses/communityuse",
                        "notes": (
                            "Blog-published artwork is CUP-eligible; photographs are "
                            "not. asset_description often carries artist attribution; "
                            "eligibility + subject classification pending (pass 2)."
                        ),
                    },
                    "subject": None,
                    "crawled_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
                indent=1,
                ensure_ascii=False,
            )
            + "\n"
        )
        written += 1
    return written, len(assets)
