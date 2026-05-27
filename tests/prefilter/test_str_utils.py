import pytest
from prefilter.str_utils import (
    _contains_phrase,
    _location_contains,
    _flatten_strings,
    merge_country_aliases,
    check_banned_terms,
)


@pytest.mark.parametrize(
    "text, phrase, expected",
    [
        # Exact matching
        ("Senior Software Engineer", "Software", True),
        ("Senior Software Engineer", "software", True),  # Case insensitivity
        # Multi-word phrase tracking
        ("Senior Machine Learning Engineer", "Machine Learning", True),
        (
            "Senior Machine Learning Engineer",
            "Learning Machine",
            False,
        ),  # Order verification
        # Substring/Word boundary safety
        ("Welder Application", "weld", False),  # Substring boundaries protected
        ("Biomechanical Software Engineer", "mechanical", False),
        # Empty/None handlers
        ("", "software", False),
        (None, "software", False),
    ],
)
def test_contains_phrase_word_boundaries(text, phrase, expected):
    """Verifies that phrases are accurately tokenized with correct word boundaries."""
    assert _contains_phrase(text, phrase) == expected


@pytest.mark.parametrize(
    "text, allowed_location, expected",
    [
        # Exact token ordering flips
        ("Washington - Pullman", "Pullman, WA", True),
        ("Pullman, WA", "Washington - Pullman", True),
        # State abbreviation canonicalization overrides
        ("Seattle, WA", "Seattle, Washington", True),
        ("Portland, Oregon", "Portland, OR", True),
        # Partial alignment mismatches
        ("Pullman, Illinois", "Pullman, WA", False),
        # Edge cases
        ("", "Pullman, WA", False),
        (None, "Pullman, WA", False),
    ],
)
def test_location_contains_state_canonicalization(text, allowed_location, expected):
    """Verifies state expansion logic isolates positional changes in address formatting."""
    assert _location_contains(text, allowed_location) == expected


@pytest.mark.parametrize(
    "input_val, expected",
    [
        ("plain string", ["plain string"]),
        (["list", "of", "strings"], ["list", "of", "strings"]),
        ({"key1": "val1", "key2": ["nested", "val"]}, ["val1", "nested", "val"]),
        (None, []),
        (42, ["42"]),  # Numeric fallbacks
    ],
)
def test_flatten_strings_unpacks_arbitrary_nested_types(input_val, expected):
    """Ensures complex dicts, lists, and structures resolve into flat strings."""
    assert sorted(_flatten_strings(input_val)) == sorted(expected)


def test_merge_country_aliases_combines_user_and_system_defaults():
    """Validates merging dictionary tracking configs with pre-configured arrays."""
    configured = {"USA": ["US-Custom"], "CA": ["Canada"]}
    merged = merge_country_aliases("USA", configured)

    assert "US-Custom" in merged["USA"]
    assert "US" in merged["USA"]  # From default list
    assert "Canada" in merged["CA"]
    assert "USA" in merged["USA"]  # Selected country anchor loop


def test_check_banned_terms_isolates_title_from_global_description():
    """Verifies title check fires on titles while preventing description noise."""
    banned_terms = {
        "banned_in_title": ["specialist", "technician"],
        "banned_anywhere": ["toxic-company"],
    }

    # Case 1: Rejects if banned word lands directly in the title
    is_banned, match = check_banned_terms(
        company="SEL",
        title="Engineering Support Specialist I",
        location="Pullman, WA",
        description="Core software systems work.",
        banned_terms=banned_terms,
    )
    assert is_banned is True
    assert match == "banned_in_title:specialist"

    # Case 2: Safely ALLOWS if the title is safe, even if description uses the word
    is_banned, match = check_banned_terms(
        company="SEL",
        title="Software Engineer",
        location="Pullman, WA",
        description="You will support deployment specialists across our infrastructure team.",
        banned_terms=banned_terms,
    )
    assert is_banned is False
    assert match is None

    # Case 3: Triggers anywhere block if bad actor exists in descriptions
    is_banned, match = check_banned_terms(
        company="toxic-company",
        title="C++ Software Engineer",
        location="Remote",
        description="Systems automation work.",
        banned_terms=banned_terms,
    )
    assert is_banned is True
    assert match == "banned_anywhere:toxic-company"
