"""Tests for _content_filter HTML5 navigation stripping."""

from bs4 import BeautifulSoup

from pfsrd2.condition import _content_filter as condition_content_filter
from pfsrd2.equipment import _content_filter as equipment_content_filter
from pfsrd2.item_group import _content_filter as item_group_content_filter

# Minimal HTML5 page structure from AoN
HTML5_WITH_NAV = """<html><body>
<div id="main">
  <span><a href="nav1">Nav Link</a></span>
  <hr/>
  <span><h1>Item Name</h1></span>
  <b>Source</b> <a href="Sources.aspx?ID=1">Player Core</a>
  <p>Description text</p>
</div>
</body></html>"""

HTML5_NO_HR = """<html><body>
<div id="main">
  <span><h1>Item Name</h1></span>
  <b>Source</b> <a href="Sources.aspx?ID=1">Player Core</a>
</div>
</body></html>"""

HTML5_NO_MAIN = """<html><body>
<div id="other">
  <h1>No main div</h1>
</div>
</body></html>"""

HTML5_EMPTY_ANCHORS = """<html><body>
<div id="main">
  <hr/>
  <span><h1>Item Name</h1></span>
  <a></a>
  <a>  </a>
  <a><img src="icon.png"/></a>
  <a href="Traits.aspx?ID=1">Magical</a>
</div>
</body></html>"""


class TestEquipmentContentFilter:
    """Tests for equipment.py _content_filter."""

    def test_strips_nav_before_hr(self):
        soup = BeautifulSoup(HTML5_WITH_NAV, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        # Nav link and hr should be gone
        assert main.find("hr") is None
        assert "Nav Link" not in main.get_text()

    def test_unwraps_h1_span(self):
        soup = BeautifulSoup(HTML5_WITH_NAV, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        # h1 should now be a direct child, not wrapped in span
        h1 = main.find("h1")
        assert h1 is not None
        assert h1.parent == main

    def test_no_hr_does_not_crash(self):
        soup = BeautifulSoup(HTML5_NO_HR, "html.parser")
        equipment_content_filter(soup)
        # Should not raise; h1 should still be unwrapped
        main = soup.find(id="main")
        h1 = main.find("h1")
        assert h1 is not None
        assert h1.parent == main

    def test_no_main_div_does_not_crash(self):
        soup = BeautifulSoup(HTML5_NO_MAIN, "html.parser")
        equipment_content_filter(soup)  # Should not raise

    def test_removes_empty_anchors(self):
        soup = BeautifulSoup(HTML5_EMPTY_ANCHORS, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        anchors = main.find_all("a")
        # Empty anchors removed, img anchor and real link kept
        assert len(anchors) == 2
        texts = [a.get_text(strip=True) for a in anchors]
        assert "Magical" in texts

    def test_preserves_content_after_hr(self):
        soup = BeautifulSoup(HTML5_WITH_NAV, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        assert "Description text" in main.get_text()
        assert "Player Core" in main.get_text()


class TestConditionContentFilter:
    """Tests for condition.py _content_filter (same pattern, simpler)."""

    def test_strips_nav_before_hr(self):
        soup = BeautifulSoup(HTML5_WITH_NAV, "html.parser")
        condition_content_filter(soup)
        main = soup.find(id="main")
        assert main.find("hr") is None
        assert "Nav Link" not in main.get_text()

    def test_unwraps_h1_span(self):
        soup = BeautifulSoup(HTML5_WITH_NAV, "html.parser")
        condition_content_filter(soup)
        main = soup.find(id="main")
        h1 = main.find("h1")
        assert h1 is not None
        assert h1.parent == main


class TestItemGroupContentFilter:
    """Tests for item_group.py _content_filter."""

    def test_strips_nav_and_unwraps_h1(self):
        soup = BeautifulSoup(HTML5_WITH_NAV, "html.parser")
        item_group_content_filter(soup)
        main = soup.find(id="main")
        assert main.find("hr") is None
        h1 = main.find("h1")
        assert h1 is not None
        assert h1.parent == main
