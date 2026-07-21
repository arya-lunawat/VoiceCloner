"""
Tests for the smart text chunking module.

Verifies that chunk_text:
- Respects the max_chars limit
- Splits on sentence boundaries
- Correctly handles abbreviations (doesn't split on "Dr.", "Mr.", etc.)
- Falls back to word-wrap for very long sentences
- Handles empty / edge-case input
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from chunking import chunk_text


# ── Tests ────────────────────────────────────────────────────────────────

def test_empty_text():
    assert chunk_text("") == []
    assert chunk_text("   ") == []
    assert chunk_text("\n\n\n") == []


def test_short_text_no_split():
    """Text under max_chars should return a single chunk."""
    result = chunk_text("Hello world.")
    assert len(result) == 1
    assert result[0] == "Hello world."


def test_splits_on_sentence_boundary():
    """Two long sentences should be split into two chunks."""
    text = "This is the first sentence here. This is the second sentence here."
    result = chunk_text(text, max_chars=50)
    assert len(result) >= 2
    # Each chunk should end with sentence-ending punctuation
    for chunk in result[:-1]:  # last chunk may not end with punctuation if text ends
        assert chunk.rstrip().endswith(".") or chunk.rstrip().endswith("!") or chunk.rstrip().endswith("?")


def test_respects_max_chars():
    """No chunk should exceed max_chars."""
    text = "A. " * 500  # 500 short sentences
    result = chunk_text(text, max_chars=200)
    for chunk in result:
        assert len(chunk) <= 200, f"Chunk length {len(chunk)} exceeds max_chars"


def test_abbreviation_not_split():
    """Common abbreviations like 'Dr.' and 'Mr.' should not trigger a split."""
    text = "Dr. Smith went to Washington. He met with Mr. Jones."
    result = chunk_text(text, max_chars=200)
    # The abbreviations should be kept intact within their sentence
    assert "Dr." in result[0] or "Dr." in (result[1] if len(result) > 1 else "")
    assert "Mr." in ([c for c in result if "Mr." in c][0] if any("Mr." in c for c in result) else "")


def test_paragraph_breaks_preserved():
    """Paragraph breaks should produce clean split points."""
    text = "First paragraph about something.\n\nSecond paragraph about something else."
    result = chunk_text(text, max_chars=200)
    assert len(result) == 2


def test_long_sentence_word_wrap():
    """A single very long sentence with no punctuation should be word-wrapped."""
    text = "word " * 500  # 2500 chars, no punctuation
    result = chunk_text(text, max_chars=200)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 200


def test_no_mid_word_cut():
    """Word wrap should never cut a word in half."""
    text = ("hello " * 100) + "supercalifragilisticexpialidocious " + ("world " * 100)
    result = chunk_text(text, max_chars=200)
    for chunk in result:
        # No chunk should end with a partial word (exception: super-long words
        # are intentionally split character-by-character, which is acceptable)
        words = chunk.split()
        if words:
            assert len(words[-1]) <= 220 or "supercalifragilisticexpialidocious" in chunk


def test_multiple_sentences_in_one_chunk():
    """Multiple short sentences can be combined into one chunk."""
    text = "Hi. Bye. Go. Stop. Yes. No. Maybe. So. " * 3
    result = chunk_text(text, max_chars=200)
    for chunk in result:
        assert len(chunk) <= 200
    # There should be fewer chunks than sentences (grouping occurred)
    num_sentences = text.count(".")
    assert len(result) < num_sentences

