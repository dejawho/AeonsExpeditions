"""Helpers to turn Aeon's End wiki wikitext into plain text and to pull out links."""
import re

import mwparserfromhell as mw

AETHER = "Æ"

# Templates that render to nothing useful in plain text.
DROP_TEMPLATES = {
    "spoiler warning", "spoiler", "under construction", "disambig", "for", "cardimage",
    "featured", "featuredin", "startingcardlist", "breachtable", "mageintro", "nemesisintro",
    "playercardintro", "nemesiscardintro", "friendintro", "foeintro", "friend&foecardintro",
    "clear", "-", "!",
}


ICON_TEXT = {
    "aethertoken": f"{AETHER} token",
    "recall": "Recall:",
    "wandering": "Wandering",
    "knowledge": "Knowledge",
    "magenamespace": "the mage named on this card (any player outside the campaign)",
}


def _render_template(t, pagename):
    name = str(t.name).strip()
    low = name.lower()
    if low in ("cost", "aether"):
        return AETHER
    if low in ICON_TEXT:
        return ICON_TEXT[low]
    if low == "pagename":
        return pagename
    if low in ("card", "c"):
        if t.has(2):
            return to_text(str(t.get(2).value), pagename)
        if t.has(1):
            return to_text(str(t.get(1).value), pagename)
        return ""
    if low == "quote" and t.has("quote"):
        return to_text(str(t.get("quote").value), pagename)
    if low in DROP_TEMPLATES or low.startswith("#"):
        return ""
    # Unknown inline template (icons, charge symbols...): keep first positional arg if any.
    if t.has(1):
        return to_text(str(t.get(1).value), pagename)
    return ""


def to_text(wikitext, pagename=""):
    """Convert a wikitext fragment to readable plain text."""
    if not wikitext:
        return ""
    s = wikitext
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S | re.I)
    # Drop bold/italic and HTML first: the parser wraps them as tags, hiding the links/templates inside.
    s = re.sub(r"'''''|'''|''", "", s)
    s = re.sub(r"</?(div|span|center|small|big|p|u|s|sup|sub|blockquote|font)\b[^>]*>", "", s, flags=re.I)
    code = mw.parse(s)
    for t in code.filter_templates(recursive=False):
        try:
            code.replace(t, _render_template(t, pagename))
        except ValueError:
            pass
    for link in code.filter_wikilinks(recursive=False):
        target = str(link.title).strip()
        if re.match(r"(?i)^(file|image|category):", target):
            code.replace(link, "")
        else:
            code.replace(link, str(link.text).strip() if link.text else target.split("#")[0])
    for el in code.filter_external_links(recursive=False):
        code.replace(el, str(el.title or ""))
    s = str(code)
    s = re.sub(r"'''''|'''|''", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&mdash;", "—").replace("&ndash;", "–")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def links(wikitext):
    """Return linked page titles (wikilinks and {{Card|X}}) in a fragment, in order."""
    out = []
    code = mw.parse(wikitext or "")
    for link in code.filter_wikilinks():
        target = str(link.title).strip().split("#")[0]
        if target and not re.match(r"(?i)^(file|image|category|:category):", target):
            out.append(target)
    for t in code.filter_templates():
        if str(t.name).strip().lower() in ("card", "c", "cardimage") and t.has(1):
            out.append(str(t.get(1).value).strip())
    return [normalize_title(o) for o in out if o]


def normalize_title(t):
    t = t.replace("_", " ").strip()
    return t[:1].upper() + t[1:] if t else t


def template_params(t):
    return {str(p.name).strip(): str(p.value).strip() for p in t.params}


def sections(wikitext):
    """Split a page into (heading, level, body) tuples. Lead section has heading ''."""
    out = []
    parts = re.split(r"^(=+)\s*(.*?)\s*\1\s*$", wikitext, flags=re.M)
    out.append(("", 0, parts[0]))
    for i in range(1, len(parts) - 2, 3):
        out.append((parts[i + 1].strip(), len(parts[i]), parts[i + 2]))
    return out
