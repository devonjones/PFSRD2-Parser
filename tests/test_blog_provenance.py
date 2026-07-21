import os

from pfsrd2.blog_provenance import (
    _canonical_image_url,
    _safe_basename,
    extract_post,
)

_SAMPLE = os.path.join(os.path.dirname(__file__), "data", "blog_post_sample.html")


class TestCanonicalImageUrl:
    def test_strips_size_params_and_port(self):
        assert (
            _canonical_image_url("https://cdn.paizo.com:443/a/b/img.png?w=250&rect=0,0,10,10")
            == "https://cdn.paizo.com/a/b/img.png"
        )

    def test_leaves_clean_url(self):
        assert _canonical_image_url("https://cdn.paizo.com/a/img.jpg") == (
            "https://cdn.paizo.com/a/img.jpg"
        )


class TestSafeBasename:
    def test_sanitizes(self):
        assert _safe_basename("https://x/y/My Art (Final).png") == "My_Art__Final_.png"

    def test_empty_path_falls_back(self):
        assert _safe_basename("https://x/") == "image"


class TestExtractPost:
    def test_pulls_title_tags_and_images(self):
        info = extract_post(open(_SAMPLE).read())
        assert info["title"] == "Organized Play Review of 2020"
        assert "organized_play" in info["tags"]
        # at least the org-play logo, and no navigation chrome
        assert info["images"], "expected content images"
        assert all("navigation" not in im["url"].lower() for im in info["images"])
        assert all(im["url"].startswith("https://") for im in info["images"])
        # ISO date candidates captured for pass-2 refinement
        assert any(d.startswith("2020") for d in info["dates_seen"])

    def test_alt_text_recorded(self):
        info = extract_post(open(_SAMPLE).read())
        assert any(im["alt"] for im in info["images"])


from pfsrd2.blog_provenance import (  # noqa: E402
    _asset_records,
    _entity_refs,
    _post_components,
)


def _asset_el(url, desc):
    return {
        "type": "asset",
        "value": [
            {"url": url, "name": url.rsplit("/", 1)[-1], "description": desc, "type": "image/png"}
        ],
    }


def _comp(codename, ctype, elements):
    return {"system": {"codename": codename, "type": ctype, "name": codename}, "elements": elements}


class TestCmsPerPostResolution:
    def _batch(self):
        # Two posts share one modular_content map (as the API returns).
        mods = {
            "img_a": _comp(
                "img_a",
                "blog_entry___image_block",
                {"image": _asset_el("https://c/A.png", "art A")},
            ),
            "para_b": _comp(
                "para_b",
                "blog_entry___paragraph",
                {
                    "image": _asset_el("https://c/B.png", "art B"),
                    "refs": {"type": "modular_content", "value": ["cr_b"]},
                },
            ),
            "cr_b": _comp(
                "cr_b",
                "blog_entry___paragraph___creature",
                {"title": {"type": "text", "value": "Goblin"}},
            ),
            "img_sibling": _comp(
                "img_sibling",
                "blog_entry___image_block",
                {"image": _asset_el("https://c/SIB.png", "other post")},
            ),
        }
        post_a = {
            "system": {"name": "A"},
            "elements": {
                "content": {
                    "type": "rich_text",
                    "value": '<object data-codename="img_a"></object>',
                },
            },
        }
        post_b = {
            "system": {"name": "B"},
            "elements": {
                "content": {"type": "rich_text", "value": "<p>x</p>"},
                "blocks": {"type": "modular_content", "value": ["para_b"]},
            },
        }
        return post_a, post_b, mods

    def test_post_only_sees_own_components(self):
        post_a, post_b, mods = self._batch()
        comp_a = _post_components(post_a, mods)
        assert set(comp_a) == {"img_a"}
        # transitive: post B pulls its paragraph AND the creature it references
        comp_b = _post_components(post_b, mods)
        assert set(comp_b) == {"para_b", "cr_b"}

    def test_assets_scoped_to_post(self):
        post_a, post_b, mods = self._batch()
        urls_a = {a["url"] for a in _asset_records(post_a, _post_components(post_a, mods))}
        assert urls_a == {"https://c/A.png"}  # not B.png, not SIB.png
        urls_b = {a["url"] for a in _asset_records(post_b, _post_components(post_b, mods))}
        assert urls_b == {"https://c/B.png"}

    def test_entity_refs_resolve_titles(self):
        post_a, post_b, mods = self._batch()
        refs = _entity_refs(_post_components(post_b, mods))
        assert refs == [{"kind": "creature", "title": "Goblin", "codename": "cr_b"}]
