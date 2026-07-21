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
