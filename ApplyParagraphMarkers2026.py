# Apply Paragraph Markers 2 - Paratext Advanced Check script
#
# Copies paragraph/poetry markers (default: \p \q1 \q2) from the ModelText
# project onto the selected books of Project, matched up verse by verse,
# and writes the result to OutputProject.
#
# This is the Paratext-integrated counterpart of the standalone copypara.py
# tool: same marker-detection logic (works regardless of where line breaks
# fall - a marker only needs to be separated from its \v by whitespace or
# other markers, not by an actual newline; ignores mid-verse continuation
# markers; skips markers already present in the target), but driven by the
# ScriptureObjects API instead of files on disk, and one chapter at a time
# instead of a whole multi-chapter file.
#
# NOTE: Paratext runs this under its bundled IronPython 2.7 interpreter,
# not Python 3 - no f-strings, no pathlib, no typing imports.
#
# Globals provided by Paratext (see ApplyParagraphMarkers2.cms):
#   Project               - short name of the input/target project
#   OutputProject         - short name of the project to write results to
#   Books                 - string of 1s/0s indicating which books to process
#   ModelText             - short name of the project that has the markers
#   MarkersToCopy         - space-separated marker list, or blank for the default
#   ClearExistingMarkers  - "Y" to strip existing markers before copying, else "N"

from ScriptureObjects import ScriptureText
import re
import sys

DEFAULT_MARKERS = ['\\p', '\\q1', '\\q2']


def normalize_marker_token(token):
    """
    Collapse a marker token down to exactly one leading backslash.

    Typing markers into the Options dialog is easy to get wrong by analogy
    with the \\p-style doubled backslashes used to display a literal
    backslash inside the .cms file's own description text - e.g. entering
    "\\\\p" (two backslashes) when a real USFM marker is "\\p" (one). A
    doubled backslash would never match anything in real text, so normalize
    away any extra leading backslashes (and add one if the user left it off
    entirely) rather than silently doing nothing.
    """
    bare = token.lstrip('\\')
    return '\\' + bare if bare else token


def extract_verse_positions(text):
    """Map verse number -> character position, within a single chapter."""
    verse_re = re.compile(r'\\v\s+(\d+)')
    positions = {}
    for m in verse_re.finditer(text):
        positions[int(m.group(1))] = m.start()
    return positions


MARKER_TOKEN_RE = re.compile(r'\\[A-Za-z0-9]+\*?')


def _tokenize(text):
    """
    Split text into an ordered sequence of ('marker', tag, start) and
    ('text', chunk, start) tuples covering the whole string.

    Tokenizing this way (rather than splitting on newlines) matters because
    real-world USFM isn't guaranteed to put one marker per line - many
    projects run whole paragraphs together on one physical line, e.g.
    "\\p \\v 1 ... \\v 2 ... \\q1 \xabQuote\xbb \\q \\v 3 ...", with markers
    appearing wherever they logically belong rather than at line starts.
    """
    pos = 0
    for m in MARKER_TOKEN_RE.finditer(text):
        if m.start() > pos:
            yield ('text', text[pos:m.start()], pos)
        yield ('marker', m.group(0), m.start())
        pos = m.end()
    if pos < len(text):
        yield ('text', text[pos:], pos)


def find_markers(text, marker_types):
    """
    Find where specified markers occur within a single chapter's text.

    Returns a dict mapping verse number -> list of markers that precede it.

    A marker is attributed to the verse it immediately precedes: only
    whitespace, or other markers from marker_types, may come between it and
    the \\v marker that follows. Any other content in between - ordinary
    text, or an unrelated marker like \\w or \\f - breaks the chain, since
    that marker is a mid-verse formatting change (e.g. a second line of
    poetry within the same verse), not a verse-opening marker, and there's
    no reliable way to place it at the right word in the target text.
    """
    marker_set = set(marker_types)
    markers_dict = {}
    pending_markers = []  # Markers seen but not yet assigned to a verse

    tokens = list(_tokenize(text))
    n = len(tokens)
    i = 0
    while i < n:
        kind, value, start = tokens[i]

        if kind == 'marker':
            if value == '\\v':
                verse_num = None
                if i + 1 < n and tokens[i + 1][0] == 'text':
                    num_match = re.match(r'\s*(\d+)', tokens[i + 1][1])
                    if num_match:
                        verse_num = int(num_match.group(1))
                if verse_num is not None and pending_markers:
                    markers_dict[verse_num] = pending_markers[:]
                pending_markers = []
            elif value in marker_set:
                pending_markers.append(value)
                # If real content (not just whitespace) immediately follows,
                # this marker doesn't lead into a \v - discard the chain.
                if i + 1 < n and tokens[i + 1][0] == 'text' and tokens[i + 1][1].strip() != '':
                    pending_markers = []
            else:
                # Some other marker (\w, \f, \s1, ...) breaks the chain.
                pending_markers = []
        else:
            if value.strip() != '':
                pending_markers = []

        i += 1

    return markers_dict


def strip_markers(text, marker_types):
    """
    Remove every occurrence of the given markers from text - not just ones
    immediately preceding a \\v, but also ones stranded mid-verse (a second
    \\q1 continuing a line of poetry, for example) - then tidy up the
    whitespace/blank lines left behind so the result still reads cleanly.

    Used when the user wants existing markers cleared out first rather than
    merged with what the Model text supplies. Returns (new_text, removed_count).
    """
    marker_set = set(marker_types)
    kept = []
    removed_count = 0
    for kind, value, _start in _tokenize(text):
        if kind == 'marker' and value in marker_set:
            removed_count += 1
            continue
        kept.append(value)
    result = ''.join(kept)
    result = re.sub(r'[ \t]+\n', '\n', result)   # trailing space left on a line
    result = re.sub(r'\n[ \t]*\n+', '\n', result)  # blank line(s) left behind
    result = re.sub(r'[ \t]{2,}', ' ', result)   # run of spaces left inline
    return result, removed_count


def transfer_markers_for_chapter(src_text, tgt_text, marker_types):
    """
    Insert markers found in src_text into tgt_text at matching verse
    positions. Returns (new_text, inserted_count, skipped_count, missing_verses).
    """
    markers_found = find_markers(src_text, marker_types)
    tgt_verses = extract_verse_positions(tgt_text)

    # Markers the target already has immediately preceding each verse (e.g.
    # a \p the target was already hand-edited with) - found the same way we
    # find markers in the source, just applied to the target text instead.
    already_in_target = find_markers(tgt_text, marker_types)

    insertions = []  # (position, marker_text)
    skipped = 0
    missing_verses = []

    for verse_num, markers_list in markers_found.items():
        if verse_num not in tgt_verses:
            missing_verses.append(verse_num)
            continue
        pos = tgt_verses[verse_num]
        already_present = already_in_target.get(verse_num, [])
        to_insert = [m for m in markers_list if m not in already_present]
        skipped += len(markers_list) - len(to_insert)
        if not to_insert:
            continue
        marker_text = '\n'.join(to_insert) + '\n'
        insertions.append((pos, marker_text))

    # Apply insertions in reverse position order so earlier positions stay valid.
    insertions.sort(reverse=True)
    result = tgt_text
    for pos, marker_text in insertions:
        result = result[:pos] + marker_text + result[pos:]

    missing_verses.sort()
    return result, len(insertions), skipped, missing_verses


# ------------------------- Paratext entry point -------------------------

# NOTE: Paratext supplies option values (and Project/OutputProject/Books/
# ModelText) as names resolvable in this script's local scope, not as
# entries in the true globals() dict - so they must be read as bare names
# (guarded by NameError, since a blank/never-set option may not be bound
# at all), never via globals().get(...), which can't see them.
try:
    marker_option = MarkersToCopy or ''
except NameError:
    marker_option = ''
marker_types = ([normalize_marker_token(t) for t in marker_option.split()]
                 if marker_option.strip() else DEFAULT_MARKERS)

try:
    clear_option_raw = ClearExistingMarkers
except NameError:
    clear_option_raw = None
clear_existing = str(clear_option_raw or '').strip().upper().startswith('Y')

if not ModelText:
    sys.stderr.write("No Model text was specified. Please choose a Model text and try again.\n")
    sys.stderr.write("\nPress <Enter> to continue\n")
    sys.stdin.read(1)
    sys.exit(1)

scrSource = ScriptureText(ModelText)   # project that HAS the markers
scrTarget = ScriptureText(Project)     # project that receives them
if Project == OutputProject:
    scrOut = scrTarget
else:
    scrOut = ScriptureText(OutputProject)

sys.stderr.write("Copying markers (" + ' '.join(marker_types) + ") from " + ModelText + " into " + OutputProject +
                  (" (clearing existing markers first)" if clear_existing else "") + "\n")

total_inserted = 0
total_skipped = 0
total_stripped = 0

for reference, tgtText in scrTarget.chapters(Books):
    if len(tgtText) == 0:
        continue

    if clear_existing:
        tgtText, stripped_count = strip_markers(tgtText, marker_types)
        total_stripped += stripped_count

    m = re.match(r'(\w{3}) (\d+)', reference)
    if not m:
        continue
    book, chapter = m.group(1), m.group(2)

    try:
        srcText = scrSource.getText(reference)
    except Exception as e:
        sys.stderr.write(book + " " + chapter + "\tCould not read chapter from " + ModelText + ": " + str(e) + "\n")
        continue

    if not srcText:
        continue

    newText, inserted, skipped, missingVerses = transfer_markers_for_chapter(srcText, tgtText, marker_types)
    total_inserted += inserted
    total_skipped += skipped

    for v in missingVerses:
        sys.stdout.write(book + " " + chapter + ":" + str(v) + "\t\tVerse found in " + ModelText + " but not in " + Project + "; marker not copied.\n")

    # Always write the chapter, even when no markers changed. OutputProject
    # may be a different project than Project (see \outputProject in the
    # .cms file), and it may not already contain this chapter's base text -
    # skipping the write when newText == tgtText left such chapters blank
    # in the output whenever no marker needed inserting.
    scrOut.putText(reference, newText)

# The books present might have changed, so update the ssf file.
scrOut.save(OutputProject)

sys.stderr.write("\nDone. Inserted " + str(total_inserted) + " marker group(s); skipped " + str(total_skipped) + " already present in the target" +
                  ("; removed " + str(total_stripped) + " existing marker(s) first" if clear_existing else "") + ".\n")

sys.stderr.write("\nPress <Enter> to continue\n")
sys.stdin.read(1)
