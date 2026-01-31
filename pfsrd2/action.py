from bs4 import BeautifulSoup, NavigableString

from universal.universal import build_object


def extract_action_type(text, title=False):
    # Action must be the first child of the text
    def _handle_to_actions(action, newchildren):
        if len(newchildren) == 0:
            return
        child = newchildren[0]
        if type(child) != NavigableString:
            return
        if child.strip() == "to":
            newchildren.pop(0)
            assert newchildren[0].name == "span"
            if action["name"] == "One Action":
                if newchildren[0]["title"] == "Three Actions":
                    action["name"] = "One to Three Actions"
                elif newchildren[0]["title"] == "Two Actions":
                    action["name"] = "One or Two Actions"
                else:
                    raise AssertionError()
            elif action["name"] == "Tro Actions":
                if newchildren[0]["title"] == "Three Actions":
                    action["name"] = "Two to Three Actions"
                else:
                    raise AssertionError()
            newchildren.pop(0)
        elif child.strip() == "or":
            newchildren.pop(0)
            assert newchildren[0].name == "span"
            if action["name"] in ["One Action", "Single Action"]:
                if newchildren[0]["title"] == "Two Actions":
                    action["name"] = "One or Two Actions"
                elif newchildren[0]["title"] == "Three Actions":
                    action["name"] = "One or Three Actions"
                else:
                    raise AssertionError()
            elif action["name"] == "Two Actions":
                assert newchildren[0]["title"] == "Three Actions"
                action["name"] = "Two or Three Actions"
            elif action["name"] == "Free Action":
                assert newchildren[0]["title"] == "Single Action"
                action["name"] = "Free Action or Single Action"
            else:
                raise AssertionError()
            newchildren.pop(0)

    children = list(BeautifulSoup(text.strip(), "html.parser").children)
    action = None
    newchildren = []
    action_names = [
        "Reaction",
        "Free Action",
        "Single Action",
        "Two Actions",
        "Three Actions",
    ]
    while len(children) > 0:
        child = children.pop(0)
        if child.name == "span" and child["title"] in action_names:
            action = build_action_type(child, action)
        else:
            newchildren.append(child)
            if not title:
                newchildren.extend(children)
                break
    _handle_to_actions(action, newchildren)

    text = "".join([str(c) for c in newchildren]).strip()
    return text, action


def build_action_type(child, action=None):
    action_name = child["title"]
    if not action:
        action = build_object("stat_block_section", "action_type", action_name)
        if action_name == "Single Action":
            action["name"] = "One Action"
    return action
