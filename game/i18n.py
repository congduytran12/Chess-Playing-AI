# The game's language. Every text the game shows is written in English in the code; tr() gives it in the chosen
# language (a dictionary of whole texts, and patterns for the texts that have numbers or names in them), and
# anything that has no translation stays English. main.py runs every text it renders or measures through tr(), so a
# language is only a table: lang_vi.py is Vietnamese.
#
# A table has 'exact' (English text -> translation) and 'templates': English texts with %s, %d, %+d or %.1f in
# them -> translation with {0}, {1}... for the parts that were there (a part that is a text of its own, like White
# in "Rematch: you play White", is translated too).

import re

import lang_vi

LANGUAGES = [('en', "English"), ('vi', "Tiếng Việt")]
_TABLES = {'vi': lang_vi}
_language = 'en'
_exact = {}
_patterns = []  # (compiled regex of the English template, translation with {0}, {1}...)
_cache = {}
CACHE_LIMIT = 4000  # texts that change all the time (clocks) must not fill the cache for ever

# the placeholders as re.escape leaves them, and the group that matches what stood there
_PLACEHOLDERS = [(r'%\+d', r'([+-]\d+)'), (r'%\.1f', r'(-?\d+\.\d+)'), ('%d', r'(\d+)'), ('%s', r'(.+?)')]


def templateRegex(template):
    """The regex that matches texts made from an English template, one group for each %s, %d, %+d or %.1f."""
    pattern = re.escape(template)
    for escaped, group in _PLACEHOLDERS:
        pattern = pattern.replace(escaped, group)
    return re.compile(pattern, re.DOTALL)


def language():
    return _language


def setLanguage(code):
    """Switches the language ('en' or a language with a table); an unknown one means English."""
    global _language, _exact, _patterns
    _language = code if code == 'en' or code in _TABLES else 'en'
    _cache.clear()
    table = _TABLES.get(_language)
    _exact = dict(table.EXACT) if table else {}
    # the most specific template first: "Hint: %s (%d left)" before "Hint: %s"
    ordered = sorted(table.TEMPLATES.items(), key=lambda item: -len(re.sub(r'%[+.]?\d?[sdf]', '', item[0]))) if table else []
    _patterns = [(templateRegex(english), translation) for english, translation in ordered]


def tr(text):
    """text in the chosen language, or as it is when it has no translation."""
    if _language == 'en' or not text:
        return text
    found = _cache.get(text)
    if found is not None:
        return found
    found = _translate(text)
    if len(_cache) > CACHE_LIMIT:
        _cache.clear()
    _cache[text] = found
    return found


def _translate(text):
    if text in _exact:
        return _exact[text]
    for regex, translation in _patterns:
        match = regex.fullmatch(text)
        if match:
            return translation.format(*[tr(part) for part in match.groups()])
    return text
