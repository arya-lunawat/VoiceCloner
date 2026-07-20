"""
Smart text chunker for XTTS v2 long-form generation.

XTTS v2 has a practical per-call limit of ~200-250 characters.
This module splits long text into chunks that respect sentence,
clause, and word boundaries so the generated audio sounds natural
when concatenated.

Abbreviation-safe splitting:
    Splits on sentence-ending punctuation (.!?) but avoids matching
    common abbreviations (Mr., Mrs., Dr., e.g., i.e., etc., vs.,
    Prof., Sr., Jr., St., approx., vol., dept., est., govt., inc.,
    ltd., co., etc.) so they don't cause premature splits.
"""
import re

# Maximum characters per chunk sent to XTTS v2. 200 is a safe conservative
# value; you can bump to 250 if testing shows the model handles it well.
MAX_CHARS = 220

# ── Abbreviation-safe sentence splitter ──────────────────────────────────

# Common English abbreviations that end with a period but should NOT
# be treated as sentence boundaries.  This is not exhaustive, but covers
# the vast majority of cases in typical prose.
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "dept", "est",
    "govt", "approx", "vol", "inc", "ltd", "co", "corp", "assn", "bros",
    "gen", "sgt", "capt", "lt", "col", "maj", "cpt", "sgt",
    "e.g", "i.e", "etc", "vs", "viz", "al", "cf", "et al",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "p.m", "a.m", "no", "nr",
    "chap", "ch", "p", "pp", "sec", "fig", "eq",
})

# Regex that matches a sentence-ending boundary:
#   - A period / question mark / exclamation mark
#   - Followed by optional quote or closing bracket
#   - Followed by whitespace (including newline) OR end-of-string
#
# The negative lookbehind checks the word before the punctuation to
# avoid splitting on known abbreviations.
_SENTENCE_END_RE = re.compile(
    r"(?<!\b" + r")(?<!\b".join(re.escape(abbr) for abbr in sorted(_ABBREVIATIONS, key=len, reverse=True)) + r")"
    r"[.!?]['\")\]]*(?:\s+|\Z)"
)

# Clause boundaries (for fallback when a sentence is too long)
_CLAUSE_BOUNDARY_RE = re.compile(r"[,;:]\s+")


# ── Public API ───────────────────────────────────────────────────────────

def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """
    Split `text` into chunks suitable for XTTS v2.

    Strategy (in order of preference):
        1. Preserve paragraph breaks (``\n\n``) — treat each paragraph
           as a unit so pacing stays natural.
        2. Within each paragraph, split on sentence boundaries (`. ! ?`)
           that are NOT part of common abbreviations.
        3. If a single sentence still exceeds `max_chars`, split on clause
           boundaries (`, ; :`).
        4. Last resort: hard word-boundary wrap at `max_chars` (no mid-word
           cuts).

    Returns a list of text chunks, each ≤ `max_chars` characters.
    """
    text = text.strip()
    if not text:
        return []

    # Step 1: Split on paragraph breaks first.
    paragraphs = re.split(r"\n\n+", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[str] = []

    for para in paragraphs:
        # Flatten internal single-newlines to spaces so that hard-wrapped
        # prose doesn't get weird spacing during TTS.
        para = para.replace("\n", " ")

        # Step 2: Split paragraph into sentences.
        sentences = _split_sentences(para)

        for sent in sentences:
            if len(sent) <= max_chars:
                chunks.append(sent)
            else:
                # Step 3: Sentence too long — split on clauses.
                _split_long_sentence(sent, max_chars, chunks)

    return chunks


# ── Internal helpers ─────────────────────────────────────────────────────

def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, abbreviation-safe."""
    parts: list[str] = []
    pos = 0
    for m in _SENTENCE_END_RE.finditer(text):
        start, end = m.start(), m.end()
        part = text[pos:end].strip()
        if part:
            parts.append(part)
        pos = end
    remaining = text[pos:].strip()
    if remaining:
        parts.append(remaining)
    return parts if parts else [text]


def _split_long_sentence(sentence: str, max_chars: int, out: list[str]) -> None:
    """
    Split a single long sentence into smaller chunks.

    Attempts clause boundaries first (`, ; :`), then falls back to
    word-boundary wrapping as a last resort.
    """
    clauses = _CLAUSE_BOUNDARY_RE.split(sentence)
    clauses = [c.strip() for c in clauses if c.strip()]

    # If clause splitting didn't help (or only 1 clause), hard-wrap.
    if len(clauses) <= 1:
        _word_wrap(sentence, max_chars, out)
        return

    # Try to combine adjacent clauses into ≤ max_chars groups.
    current = ""
    for clause in clauses:
        # A single clause longer than max_chars must be word-wrapped.
        if len(clause) > max_chars:
            if current:
                out.append(current)
                current = ""
            _word_wrap(clause, max_chars, out)
            continue

        candidate = (current + " " + clause).strip() if current else clause
        if len(candidate) <= max_chars:
            current = candidate
        else:
            out.append(current)
            current = clause

    if current:
        out.append(current)


def _word_wrap(text: str, max_chars: int, out: list[str]) -> None:
    """
    Hard word-boundary wrap: split `text` into segments no longer than
    `max_chars`, breaking at word boundaries. Never cuts a word in half.
    """
    words = text.split()
    current = ""
    for word in words:
        # Handle abnormally long words (e.g. chemical names) by hard-cutting
        # them if they exceed max_chars by themselves.
        if len(word) > max_chars:
            if current:
                out.append(current)
                current = ""
            # Split the long word into max_chars-long segments.
            for i in range(0, len(word), max_chars):
                out.append(word[i:i + max_chars])
            continue

        candidate = (current + " " + word).strip() if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                out.append(current)
            current = word

    if current:
        out.append(current)

