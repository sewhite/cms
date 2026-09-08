# Create Readable Lexicon - Paratext Advanced Check script
#
# Reads the active project's lexicon.xml (the Word Analyses "Lexicon" file --
# the list of words/stems/prefixes/suffixes and the glosses assigned to each
# one) and builds a single, plain HTML page listing every entry together
# with its gloss(es), grouped into three sections: Words & Stems, Prefixes,
# and Suffixes.
#
# A permanent copy is saved as lexicon_readable.html next to the project's
# other files. The same content is also written to cms\checktext.htm --
# the fixed file that \toHtml opens in the user's browser (it is not a temp
# file Paratext creates for us; the script must write it directly).
#
# NOTE: Paratext runs this under its bundled IronPython 2.7 interpreter,
# not Python 3 - no f-strings, no pathlib, no typing imports.
#
# Globals provided by Paratext (see LexiconReadable.cms):
#   Project           - short name of the active project
#   SettingsDirectory - full path to the "My Paratext 9 Projects" folder
#                        (already ends with a backslash)

import re
import sys
import codecs

LEXICON_PATH = SettingsDirectory + Project + "\\lexicon.xml"
OUTPUT_PATH = SettingsDirectory + Project + "\\lexicon_readable.html"

BOM = u"\ufeff"

ENTITY_MAP = {
    "amp": u"&",
    "lt": u"<",
    "gt": u">",
    "quot": u'"',
    "apos": u"'",
}

ENTITY_RE = re.compile(r"&(#x?[0-9A-Fa-f]+|[a-zA-Z]+);")
ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
LEXEME_RE = re.compile(r'<Lexeme\s+Type="([^"]*)"\s+Form="([^"]*)"\s+Homograph="([^"]*)"\s*/>')
GLOSS_RE = re.compile(r'<Gloss\s+Language="([^"]*)"\s*>(.*?)</Gloss>', re.S)
LANGUAGE_RE = re.compile(r"<Language>(.*?)</Language>", re.S)


def xml_unescape(s):
    def repl(m):
        ent = m.group(1)
        if ent.startswith("#x") or ent.startswith("#X"):
            return unichr(int(ent[2:], 16))
        if ent.startswith("#"):
            return unichr(int(ent[1:]))
        return ENTITY_MAP.get(ent, m.group(0))
    return ENTITY_RE.sub(repl, s)


def html_escape(s):
    return s.replace(u"&", u"&amp;").replace(u"<", u"&lt;").replace(u">", u"&gt;")


def read_file(path):
    f = codecs.open(path, "r", "utf-8")
    try:
        text = f.read()
    finally:
        f.close()
    if text.startswith(BOM):
        text = text[1:]
    return text


def parse_lexicon(text):
    groups = {"Word": [], "Stem": [], "Phrase": [], "Prefix": [], "Suffix": []}
    for item_match in ITEM_RE.finditer(text):
        chunk = item_match.group(1)
        lex_match = LEXEME_RE.search(chunk)
        if not lex_match:
            continue
        ltype, form, homograph = lex_match.groups()
        form = xml_unescape(form)

        glosses = []
        seen = set()
        for lang, gloss_text in GLOSS_RE.findall(chunk):
            gloss_text = xml_unescape(gloss_text).strip()
            if not gloss_text:
                continue
            key = (gloss_text, lang)
            if key in seen:
                continue
            seen.add(key)
            glosses.append((gloss_text, lang))

        groups.setdefault(ltype, []).append((form, homograph, glosses))
    return groups


def sort_key(entry):
    form = entry[0]
    return (form.lower(), form)


def render_entries(entries):
    lines = []
    for form, homograph, glosses in entries:
        form_disp = html_escape(form) if form else u"(blank)"
        if homograph and homograph != "1":
            form_disp += u'<span class="homograph">%s</span>' % html_escape(homograph)
        if glosses:
            parts = []
            for gloss_text, lang in glosses:
                if lang == "en":
                    tag = u""
                else:
                    tag = u'<span class="lang">(%s)</span>' % html_escape(lang)
                parts.append(u"%s%s" % (html_escape(gloss_text), tag))
            gloss_str = u"; ".join(parts)
        else:
            gloss_str = u'<span class="none">(no gloss)</span>'
        lines.append(u'<li><span class="form">%s</span> <span class="dash">&mdash;</span> %s</li>' % (form_disp, gloss_str))
    return u"\n".join(lines)


HTML_TEMPLATE = u"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>##PROJECT## Lexicon</title>
<style>
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 900px; margin: 2em auto; padding: 0 1.5em; line-height: 1.5; color: #222; background: #fdfdfb; }
  h1 { text-align: center; margin-bottom: 0.1em; }
  h2.subtitle { text-align: center; font-weight: normal; color: #555; margin-top: 0; font-size: 1.1em; }
  h2.section { border-bottom: 2px solid #888; padding-bottom: 0.2em; margin-top: 2.5em; }
  .count { color: #777; font-size: 0.85em; font-weight: normal; }
  #toc { margin: 2em 0; padding: 1em 1.5em; background: #f2f0ea; border-radius: 6px; }
  #toc a { text-decoration: none; color: #2a5d8a; }
  ul.entries { list-style: none; padding-left: 0; }
  ul.entries li { padding: 0.15em 0; border-bottom: 1px solid #eee; }
  .form { font-weight: bold; font-size: 1.05em; }
  .homograph { font-weight: normal; font-size: 0.7em; vertical-align: sub; color: #888; }
  .dash { color: #aaa; }
  .lang { color: #888; font-size: 0.85em; margin-left: 0.2em; }
  .none { color: #aaa; font-style: italic; }
  #search { width: 100%; padding: 0.5em; font-size: 1em; margin: 1em 0; box-sizing: border-box; }
  li[hidden] { display: none; }
</style>
</head>
<body>
<h1>##PROJECT## Lexicon</h1>
<h2 class="subtitle">Language code: ##LANGUAGE##</h2>

<input id="search" type="text" placeholder="Filter entries (form or gloss)...">

<div id="toc">
  <strong>Contents</strong><br>
  <a href="#words">Words &amp; Stems (##WORD_COUNT##)</a> &middot;
  <a href="#prefixes">Prefixes (##PREFIX_COUNT##)</a> &middot;
  <a href="#suffixes">Suffixes (##SUFFIX_COUNT##)</a>
</div>

<h2 class="section" id="words">Words &amp; Stems <span class="count">(##WORD_COUNT## entries)</span></h2>
<ul class="entries" id="words-list">
##WORD_ENTRIES##
</ul>

<h2 class="section" id="prefixes">Prefixes <span class="count">(##PREFIX_COUNT## entries)</span></h2>
<ul class="entries" id="prefixes-list">
##PREFIX_ENTRIES##
</ul>

<h2 class="section" id="suffixes">Suffixes <span class="count">(##SUFFIX_COUNT## entries)</span></h2>
<ul class="entries" id="suffixes-list">
##SUFFIX_ENTRIES##
</ul>

<script>
document.getElementById('search').addEventListener('input', function(e) {
  var q = e.target.value.toLowerCase();
  document.querySelectorAll('ul.entries li').forEach(function(li) {
    li.hidden = q.length > 0 && !li.textContent.toLowerCase().includes(q);
  });
});
</script>
</body>
</html>
"""

ERROR_TEMPLATE = u"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Lexicon not found</title></head>
<body>
<h1>Could not build the lexicon report</h1>
<p>%s</p>
</body>
</html>
"""


def build_html():
    text = read_file(LEXICON_PATH)

    language_match = LANGUAGE_RE.search(text)
    language_code = language_match.group(1).strip() if language_match else u""

    groups = parse_lexicon(text)
    for key in groups:
        groups[key].sort(key=sort_key)

    word_entries = groups["Word"] + groups["Stem"] + groups["Phrase"]
    word_entries.sort(key=sort_key)
    prefix_entries = groups["Prefix"]
    suffix_entries = groups["Suffix"]

    doc = HTML_TEMPLATE
    doc = doc.replace(u"##PROJECT##", html_escape(Project))
    doc = doc.replace(u"##LANGUAGE##", html_escape(language_code))
    doc = doc.replace(u"##WORD_COUNT##", unicode(len(word_entries)))
    doc = doc.replace(u"##PREFIX_COUNT##", unicode(len(prefix_entries)))
    doc = doc.replace(u"##SUFFIX_COUNT##", unicode(len(suffix_entries)))
    doc = doc.replace(u"##WORD_ENTRIES##", render_entries(word_entries))
    doc = doc.replace(u"##PREFIX_ENTRIES##", render_entries(prefix_entries))
    doc = doc.replace(u"##SUFFIX_ENTRIES##", render_entries(suffix_entries))
    return doc


try:
    html_doc = build_html()
except IOError:
    html_doc = ERROR_TEMPLATE % (
        u"No lexicon.xml file was found for project '%s' at:<br><code>%s</code><br>"
        u"Run some word-analysis checks (e.g. Checking &gt; Spelling) to build up the lexicon first."
        % (html_escape(Project), html_escape(LEXICON_PATH))
    )
    sys.stderr.write(u"Lexicon file not found: %s\n" % LEXICON_PATH)

fout = codecs.open(OUTPUT_PATH, "w", "utf-8")
try:
    fout.write(html_doc)
finally:
    fout.close()

# \toHtml opens the fixed file "cms\checktext.htm" -- it is not a temp file
# Paratext creates on our behalf, so the script has to write it directly.
fcheck = codecs.open(SettingsDirectory + "cms\\checktext.htm", "w", "utf-8")
try:
    fcheck.write(html_doc)
finally:
    fcheck.close()
