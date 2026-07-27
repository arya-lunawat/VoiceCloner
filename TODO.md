# Fix Abbreviation-Safe Sentence Splitter

## Steps
- [x] 1. Fix `backend/chunking.py`: Add `re.IGNORECASE` to `_SENTENCE_END_RE` compilation
- [x] 2. Strengthen `tests/test_chunking.py`: Add direct test for `_split_sentences` with capitalized abbreviations
- [x] 3. Run test suite and confirm everything passes

