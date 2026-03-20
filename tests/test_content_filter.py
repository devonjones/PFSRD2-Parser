"""Tests for _content_filter HTML5 navigation stripping."""

from bs4 import BeautifulSoup

from pfsrd2.condition import _content_filter as condition_content_filter
from pfsrd2.equipment import _content_filter_v2 as equipment_content_filter
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
    """Tests for equipment.py _content_filter_v2.

    _content_filter_v2 uses recursive=False for hr detection (equipment has
    nested nav spans), restructures h1 to contain the item name, and extracts
    PFS/level metadata as a prefix in the h1 text.
    """

    # Equipment HTML has two nav levels with nested hrs
    EQUIPMENT_HTML = """<html><body>
<div id="main">
  <span><h1 style="text-align:center">All Equipment | Armor</h1><hr/></span>
  <span><h2 style="text-align:center">Base Armor | Shields</h2></span>
  <hr/>
  <span>
    <h1 class="title"><a href="PFS.aspx"><span style="float:left;"><img alt="PFS Standard" src="icon.png"/></span></a></h1>
  </span>
  <a href="Armor.aspx?ID=1">Padded Armor</a>
  <span style="margin-left:auto; margin-right:0">Item 1</span>
  <b>Source</b> <a href="Sources.aspx?ID=1"><i>Player Core</i></a>
  <p>Description text</p>
</div>
</body></html>"""

    def test_strips_nav_before_direct_child_hr(self):
        soup = BeautifulSoup(self.EQUIPMENT_HTML, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        # Both nav sections and the direct-child hr should be gone
        assert "All Equipment" not in main.get_text()
        assert "Base Armor" not in main.get_text()

    def test_extracts_name_into_h1(self):
        soup = BeautifulSoup(self.EQUIPMENT_HTML, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        assert h1 is not None
        # h1 text should contain metadata prefix + name
        assert "Padded Armor" in h1.get_text()

    def test_extracts_pfs_and_level_metadata(self):
        soup = BeautifulSoup(self.EQUIPMENT_HTML, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        text = h1.get_text()
        assert "__EQ_META:Standard:1__" in text

    def test_removes_empty_anchors(self):
        soup = BeautifulSoup(HTML5_EMPTY_ANCHORS, "html.parser")
        equipment_content_filter(soup)
        main = soup.find(id="main")
        anchors = main.find_all("a")
        # Empty anchors removed, img anchor and real link kept
        assert len(anchors) == 2
        texts = [a.get_text(strip=True) for a in anchors]
        assert "Magical" in texts

    def test_no_main_div_does_not_crash(self):
        soup = BeautifulSoup(HTML5_NO_MAIN, "html.parser")
        equipment_content_filter(soup)  # Should not raise

    def test_preserves_content_after_nav(self):
        soup = BeautifulSoup(self.EQUIPMENT_HTML, "html.parser")
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
    """Tests for item_group.py _content_filter.

    Item group pages have TWO nav sections before the h1.title content.
    """

    # Item group pages have two nav sections separated by <hr> before the content
    ITEM_GROUP_HTML = """<html><body>
<div id="main">
  <span><a href="nav1">All Equipment</a> | <a href="nav2">Armor</a></span>
  <hr/>
  <span><h2>Base Armor | Consumables</h2></span>
  <hr/>
  <span><h1 class="title"><a href="ArmorGroups.aspx?ID=1">Chain</a></h1></span>
  <b>Source</b> <a href="Sources.aspx?ID=1">Player Core</a>
</div>
</body></html>"""

    def test_strips_both_nav_sections(self):
        soup = BeautifulSoup(self.ITEM_GROUP_HTML, "html.parser")
        item_group_content_filter(soup)
        main = soup.find(id="main")
        # Both nav sections should be gone
        assert "All Equipment" not in main.get_text()
        assert "Base Armor" not in main.get_text()

    def test_unwraps_h1_span(self):
        soup = BeautifulSoup(self.ITEM_GROUP_HTML, "html.parser")
        item_group_content_filter(soup)
        main = soup.find(id="main")
        h1 = main.find("h1")
        assert h1 is not None
        assert h1.parent == main

    def test_preserves_content(self):
        soup = BeautifulSoup(self.ITEM_GROUP_HTML, "html.parser")
        item_group_content_filter(soup)
        main = soup.find(id="main")
        assert "Chain" in main.get_text()
        assert "Player Core" in main.get_text()
