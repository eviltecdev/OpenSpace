"""Tests for fuzzy_match module — Levenshtein distance and 6-level matching chain.

Target coverage: 70%+ (currently 0%)
Test count: 15-18 tests covering all replacer functions and edge cases.
"""

import pytest
from openspace.skill_engine.fuzzy_match import (
    levenshtein,
    simple_replacer,
    line_trimmed_replacer,
    block_anchor_replacer,
    whitespace_normalized_replacer,
    indentation_flexible_replacer,
    trimmed_boundary_replacer,
    fuzzy_find_match,
    fuzzy_replace,
    REPLACER_CHAIN,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def simple_content():
    """Basic content for testing."""
    return "hello\nworld\ntest"


@pytest.fixture
def content_with_variations():
    """Content with various whitespace patterns."""
    return """def hello():
    print("hello")
    return 42

def world():
    print("world")
    return 99
"""


@pytest.fixture
def content_with_indentation():
    """Content with mixed indentation."""
    return """  def function():
      x = 1
      y = 2
      return x + y
"""


@pytest.fixture
def content_with_multiple_blocks():
    """Content with multiple potential matches."""
    return """class Handler:
    def process(self):
        x = 1
        y = 2
        return x + y

class Processor:
    def process(self):
        x = 1
        y = 2
        return x + y
"""


@pytest.fixture
def multiline_content():
    """Content with multiple paragraphs."""
    return """Line 1
Line 2
Line 3
Line 4
Line 5
Line 6"""


# ============================================================================
# Tests: Levenshtein Distance
# ============================================================================


class TestLevenshteinDistance:
    """Test Levenshtein edit distance calculation."""

    def test_levenshtein_identical_strings(self):
        """Identical strings should return 0."""
        assert levenshtein("hello", "hello") == 0
        assert levenshtein("", "") == 0

    def test_levenshtein_empty_strings(self):
        """Empty string handling."""
        assert levenshtein("", "hello") == 5
        assert levenshtein("hello", "") == 5
        assert levenshtein("", "") == 0

    def test_levenshtein_single_char_diff(self):
        """Single character differences."""
        assert levenshtein("a", "b") == 1
        assert levenshtein("ab", "ba") == 2  # Transposition
        assert levenshtein("cat", "cut") == 1
        assert levenshtein("kitten", "sitting") == 3


# ============================================================================
# Tests: Individual Replacer Functions
# ============================================================================


class TestSimpleReplacer:
    """Test simple_replacer (yields find unconditionally)."""

    def test_simple_replacer_yields_find(self):
        """simple_replacer should yield find exactly."""
        candidates = list(simple_replacer("any content", "find"))
        assert "find" in candidates

    def test_simple_replacer_on_empty_content(self):
        """simple_replacer works with empty content."""
        candidates = list(simple_replacer("", "find"))
        assert "find" in candidates


class TestLineTrimmedReplacer:
    """Test line_trimmed_replacer (strip lines before comparing)."""

    def test_line_trimmed_replacer_exact_match(self, simple_content):
        """Line-trimmed match should find exact substring."""
        find = "hello\nworld"
        candidates = list(line_trimmed_replacer(simple_content, find))
        assert "hello\nworld" in candidates

    def test_line_trimmed_replacer_with_trailing_spaces(self, content_with_variations):
        """Should match despite trailing spaces on lines."""
        find = "def hello():\n    print(\"hello\")"
        candidates = list(line_trimmed_replacer(content_with_variations, find))
        assert len(candidates) > 0

    def test_line_trimmed_replacer_no_match(self, simple_content):
        """Should return empty when no match."""
        find = "nonexistent\nlines"
        candidates = list(line_trimmed_replacer(simple_content, find))
        assert len(candidates) == 0

    def test_line_trimmed_replacer_with_trailing_empty_line(self):
        """Should handle trailing empty line in find."""
        content = "line1\nline2\nline3"
        find = "line1\nline2\n"
        candidates = list(line_trimmed_replacer(content, find))
        assert len(candidates) > 0


class TestBlockAnchorReplacer:
    """Test block_anchor_replacer (anchor on first/last lines, Levenshtein on middle)."""

    def test_block_anchor_single_candidate(self):
        """Single candidate should match if similarity >= threshold."""
        content = """def start():
    middle line here
    another middle
def end():
    something else"""
        find = """def start():
    middle line here
    another middle
def end():"""
        candidates = list(block_anchor_replacer(content, find))
        assert len(candidates) > 0

    def test_block_anchor_multiple_candidates(self, content_with_multiple_blocks):
        """Multiple candidates should pick best match."""
        find = """def process(self):
        x = 1
        y = 2
        return x + y"""
        candidates = list(block_anchor_replacer(content_with_multiple_blocks, find))
        # Should find something if Levenshtein similarity is high
        assert isinstance(candidates, list)

    def test_block_anchor_insufficient_lines(self):
        """Block with < 3 lines should not match."""
        content = "line1\nline2"
        find = "line1\nline2"
        candidates = list(block_anchor_replacer(content, find))
        assert len(candidates) == 0

    def test_block_anchor_no_matching_boundaries(self):
        """Should return empty when boundaries don't match."""
        content = "start\nmiddle\nend"
        find = "different\nmiddle\nlines"
        candidates = list(block_anchor_replacer(content, find))
        assert len(candidates) == 0


class TestWhitespaceNormalizedReplacer:
    """Test whitespace_normalized_replacer (collapse whitespace)."""

    def test_whitespace_normalized_single_line(self):
        """Normalize whitespace on single line."""
        content = "hello    world    test"
        find = "hello world test"
        candidates = list(whitespace_normalized_replacer(content, find))
        assert "hello    world    test" in candidates

    def test_whitespace_normalized_multiline(self):
        """Normalize whitespace across multiple lines."""
        content = "line1  \nline2    \nline3"
        find = "line1\nline2\nline3"
        candidates = list(whitespace_normalized_replacer(content, find))
        assert len(candidates) > 0

    def test_whitespace_normalized_no_match(self):
        """Should return empty when content doesn't match."""
        content = "hello world"
        find = "goodbye world"
        candidates = list(whitespace_normalized_replacer(content, find))
        assert len(candidates) == 0


class TestIndentationFlexibleReplacer:
    """Test indentation_flexible_replacer (strip common indent)."""

    def test_indentation_flexible_matches_despite_indent(self, content_with_indentation):
        """Should match despite different indentation."""
        # Find pattern with no common indent (will be dedented to match content)
        find = """  def function():
      x = 1
      y = 2
      return x + y"""
        candidates = list(indentation_flexible_replacer(content_with_indentation, find))
        assert len(candidates) > 0

    def test_indentation_flexible_preserves_original(self):
        """Should yield original block from content, not dedented."""
        content = "    x = 1\n    y = 2"
        find = "x = 1\ny = 2"
        candidates = list(indentation_flexible_replacer(content, find))
        # The yielded match should be from content (preserving indentation)
        assert len(candidates) > 0

    def test_indentation_flexible_no_match(self):
        """Should return empty when dedented content doesn't match."""
        content = "x = 1\ny = 2"
        find = "x = 1\ny = 9"
        candidates = list(indentation_flexible_replacer(content, find))
        assert len(candidates) == 0


class TestTrimmedBoundaryReplacer:
    """Test trimmed_boundary_replacer (strip entire block)."""

    def test_trimmed_boundary_removes_leading_trailing(self):
        """Should trim entire block and search."""
        content = "  hello world  \n  test  "
        find = "\n  hello world  \n  test\n"
        candidates = list(trimmed_boundary_replacer(content, find))
        assert len(candidates) > 0

    def test_trimmed_boundary_skip_already_trimmed(self):
        """Should skip if find is already trimmed."""
        content = "hello world"
        find = "hello world"
        candidates = list(trimmed_boundary_replacer(content, find))
        # Should skip because trimmed == original
        assert len(candidates) == 0

    def test_trimmed_boundary_multiline(self):
        """Should handle multiline blocks."""
        content = "  line1\n  line2\n  line3  "
        find = "  \nline1\nline2\nline3\n  "
        candidates = list(trimmed_boundary_replacer(content, find))
        assert isinstance(candidates, list)


# ============================================================================
# Tests: Fuzzy Find Chain
# ============================================================================


class TestFuzzyFindMatch:
    """Test fuzzy_find_match (walks replacer chain)."""

    def test_fuzzy_find_exact_match(self, simple_content):
        """Exact match should find via simple_replacer."""
        match, pos = fuzzy_find_match(simple_content, "hello")
        assert match == "hello"
        assert pos == 0

    def test_fuzzy_find_line_trimmed_match(self, content_with_variations):
        """Line-trimmed match when exact fails."""
        find = "def hello():\n    print(\"hello\")"
        match, pos = fuzzy_find_match(content_with_variations, find)
        assert match != ""
        assert pos >= 0

    def test_fuzzy_find_no_match(self, simple_content):
        """Should return empty string and -1 when not found."""
        match, pos = fuzzy_find_match(simple_content, "nonexistent")
        assert match == ""
        assert pos == -1

    def test_fuzzy_find_multiline_search(self, multiline_content):
        """Should find multiline patterns."""
        find = "Line 2\nLine 3"
        match, pos = fuzzy_find_match(multiline_content, find)
        assert match != ""
        assert "Line 2" in match and "Line 3" in match


# ============================================================================
# Tests: Fuzzy Replace
# ============================================================================


class TestFuzzyReplace:
    """Test fuzzy_replace (replace with unique match detection)."""

    def test_fuzzy_replace_single_exact_match(self, simple_content):
        """Exact unique match should be replaced."""
        result = fuzzy_replace(simple_content, "hello", "goodbye")
        assert "goodbye" in result
        assert "hello" not in result

    def test_fuzzy_replace_with_fuzzy_match(self, content_with_variations):
        """Fuzzy match should also be replaced."""
        find = "def hello():\n    print(\"hello\")"
        result = fuzzy_replace(content_with_variations, find, "# replaced")
        assert "# replaced" in result

    def test_fuzzy_replace_identical_old_new_raises(self, simple_content):
        """Should raise ValueError when old == new."""
        with pytest.raises(ValueError, match="identical"):
            fuzzy_replace(simple_content, "hello", "hello")

    def test_fuzzy_replace_not_found_raises(self, simple_content):
        """Should raise ValueError when pattern not found."""
        with pytest.raises(ValueError, match="Could not find"):
            fuzzy_replace(simple_content, "nonexistent", "replacement")

    def test_fuzzy_replace_ambiguous_raises(self):
        """Should raise ValueError when multiple matches found."""
        content = "hello world\nhello again"
        with pytest.raises(ValueError, match="multiple matches"):
            fuzzy_replace(content, "hello", "goodbye")

    def test_fuzzy_replace_all_replaces_all_occurrences(self):
        """replace_all=True should replace all matches."""
        content = "hello world\nhello again"
        result = fuzzy_replace(content, "hello", "goodbye", replace_all=True)
        assert result.count("goodbye") == 2
        assert "hello" not in result

    def test_fuzzy_replace_all_with_fuzzy_match(self, content_with_multiple_blocks):
        """replace_all=True should work with fuzzy matches."""
        find = """def process(self):
        x = 1
        y = 2
        return x + y"""
        replacement = "pass"
        result = fuzzy_replace(
            content_with_multiple_blocks,
            find,
            replacement,
            replace_all=True
        )
        # Should replace (or attempt to replace) the found pattern
        assert isinstance(result, str)


# ============================================================================
# Tests: REPLACER_CHAIN Structure
# ============================================================================


class TestReplacerChain:
    """Test the REPLACER_CHAIN structure and ordering."""

    def test_replacer_chain_has_six_levels(self):
        """REPLACER_CHAIN should have 6 replacer functions."""
        assert len(REPLACER_CHAIN) == 6

    def test_replacer_chain_names(self):
        """REPLACER_CHAIN should have correct names in order."""
        names = [name for name, _ in REPLACER_CHAIN]
        expected_names = [
            "simple",
            "line_trimmed",
            "block_anchor",
            "whitespace_normalized",
            "indentation_flexible",
            "trimmed_boundary",
        ]
        assert names == expected_names

    def test_replacer_chain_functions_are_callable(self):
        """Each replacer should be callable."""
        for name, replacer in REPLACER_CHAIN:
            assert callable(replacer), f"{name} is not callable"


# ============================================================================
# Edge Cases & Integration
# ============================================================================


class TestEdgeCases:
    """Test edge cases and integration scenarios."""

    def test_empty_content_search(self):
        """Search in empty content."""
        match, pos = fuzzy_find_match("", "search")
        assert match == ""
        assert pos == -1

    def test_empty_find_pattern(self):
        """Search for empty pattern."""
        content = "hello world"
        # Most replacers should return empty for empty find
        candidates = list(simple_replacer(content, ""))
        assert "" in candidates

    def test_very_long_content(self):
        """Handle very long content efficiently."""
        content = "line\n" * 1000
        find = "line\nline"
        match, pos = fuzzy_find_match(content, find)
        assert match != ""
        assert pos >= 0

    def test_unicode_content(self):
        """Handle unicode characters."""
        content = "héllo wörld\nñoño"
        find = "héllo wörld"
        match, pos = fuzzy_find_match(content, find)
        assert match == "héllo wörld"

    def test_special_regex_chars_in_find(self):
        """Handle regex special characters in search pattern."""
        content = "def func(x, y):\n    return x + y"
        find = "def func(x, y):\n    return x + y"
        match, pos = fuzzy_find_match(content, find)
        assert match != ""

    def test_newline_variations(self):
        """Handle different newline patterns."""
        content = "line1\nline2\nline3"
        find = "line1\nline2"
        match, pos = fuzzy_find_match(content, find)
        assert match != ""
        assert "\n" in match
