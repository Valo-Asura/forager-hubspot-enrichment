"""Unit tests for job-title matching, title variation handling, and deduplication."""

import pytest
from app.services.discovery import matches_job_title


@pytest.mark.parametrize(
    "candidate_title,allowed_titles,expected",
    [
        # Exact and case-insensitive
        ("Software Engineer", ["Software Engineer"], True),
        ("software engineer", ["Software Engineer"], True),
        ("SOFTWARE ENGINEER", ["software engineer"], True),
        # Prefix / seniority variations
        ("Senior Software Engineer", ["Software Engineer"], True),
        ("Staff Software Engineer - Infrastructure", ["Software Engineer"], True),
        ("Lead Software Engineer", ["Software Engineer"], True),
        ("Principal Software Engineer", ["Software Engineer"], True),
        # Role synonym & acronym expansion
        ("Chief Technology Officer", ["CTO"], True),
        ("CTO & Co-Founder", ["CTO"], True),
        ("Co-Founder and CTO", ["CTO"], True),
        ("Vice President of Engineering", ["VP of Engineering"], True),
        ("VP Engineering", ["VP of Engineering"], True),
        ("VP, Engineering", ["VP of Engineering"], True),
        ("Head of Engineering", ["Head of Engineering"], True),
        ("Director of Engineering", ["Head of Engineering"], True),
        # Product roles
        ("Product Manager", ["Product Manager"], True),
        ("Senior Product Manager", ["Product Manager"], True),
        ("Group Product Manager", ["Product Manager"], True),
        # Non-matching roles
        ("Account Executive", ["Software Engineer", "CTO"], False),
        ("Sales Development Representative", ["Software Engineer", "Product Manager"], False),
        ("Office Manager", ["Software Engineer"], False),
        ("Recruiting Coordinator", ["Software Engineer", "VP of Engineering"], False),
        ("Customer Success Manager", ["CTO", "Software Engineer"], False),
    ],
)
def test_matches_job_title(candidate_title, allowed_titles, expected):
    """Test job title matcher against various real-world titles and variations."""
    result = matches_job_title(candidate_title, allowed_titles)
    assert result == expected
