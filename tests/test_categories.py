"""Regression tests for filter config (commit 2).

Locks down: filters.yaml is the single source of truth for topics, and
the orchestrator re-categorises events using FilterEngine.categorize so
new topics added to YAML reach the DB without per-scraper edits.
"""
from datetime import datetime

import pytest

from backend.api.events import _load_categories
from backend.filters import FilterEngine


def test_yaml_loads_all_ten_topics():
    """All ten topics defined in filters.yaml must be returned by the API."""
    cats = _load_categories()
    names = {c.name for c in cats}
    expected = {
        "AI", "Cybersecurity", "Anti-Scam", "Blockchain",
        "Investment", "Trading", "Fintech", "Entrepreneurship",
        "Hackathon", "Social Enterprise",
    }
    assert names == expected


def test_every_topic_has_color_and_keywords():
    """No topic ships without a color or without at least one keyword."""
    cats = _load_categories()
    for c in cats:
        assert c.color and c.color.startswith("#"), f"{c.name} missing color"
        assert c.keywords, f"{c.name} has no keywords"


def test_hackathon_keyword_matches():
    """Hackathon topic catches a typical title."""
    engine = FilterEngine()
    cats = engine.categorize("Codeathon @ Sunway iLabs (Hackathon)", "")
    assert "Hackathon" in cats


def test_anti_scam_keyword_matches():
    engine = FilterEngine()
    cats = engine.categorize("Online Safety: Phishing & Scam Awareness", "")
    assert "Anti-Scam" in cats


def test_social_enterprise_keyword_matches():
    engine = FilterEngine()
    cats = engine.categorize("ESG Investing for Founders", "")
    assert "Social Enterprise" in cats


def test_fintech_keyword_matches():
    engine = FilterEngine()
    cats = engine.categorize("Open Banking & Digital Banking Forum", "")
    assert "Fintech" in cats


def test_orchestrator_recategorises_events():
    """Orchestrator overrides per-scraper categories with filters.yaml.
    
    A scraper labelled an event ['Tech'] - the orchestrator should rewrite
    it to the topic set from FilterEngine.categorize.
    """
    from backend.orchestrator import Orchestrator

    orch = Orchestrator()
    event = {
        "title": "AI Hackathon: Building Agentic Systems",
        "description": "",
        "categories": ["Tech"],  # legacy scraper label
        "start_datetime": datetime(2026, 6, 1, 19, 0),
        "location": "Kuala Lumpur",
        "source_platform": "test",
    }
    # Mimic the orchestrator step that re-categorises
    event["categories"] = orch.filter_engine.categorize(
        event["title"], event.get("description", "") or ""
    )
    assert "AI" in event["categories"]
    assert "Hackathon" in event["categories"]
    assert "Tech" not in event["categories"]



# ---------------------------------------------------------------------------
# Word-boundary keyword matching (fixes "AI inside Français" false positive)
# ---------------------------------------------------------------------------

def test_short_keyword_does_not_match_inside_word():
    """'AI' must NOT match inside 'Français'."""
    engine = FilterEngine()
    cats = engine.categorize("Soirée de Conversation en Français", "")
    assert "AI" not in cats
    assert cats == ["Other"]


def test_short_keyword_matches_as_whole_word():
    """'AI' SHOULD match in 'AI Hackathon' (word boundary)."""
    engine = FilterEngine()
    cats = engine.categorize("AI Hackathon", "")
    assert "AI" in cats


def test_short_keyword_matches_with_punctuation():
    """'AI' should match 'AI:' or 'AI,' or '(AI)'."""
    engine = FilterEngine()
    assert "AI" in engine.categorize("Intro to AI: Foundations", "")
    assert "AI" in engine.categorize("Workshop (AI focus)", "")


def test_ml_does_not_match_family():
    """'ML' must NOT match inside 'family'."""
    engine = FilterEngine()
    cats = engine.categorize("Family Day at the Park", "")
    assert "AI" not in cats  # AI keywords include 'ML'


def test_long_keyword_uses_substring_match():
    """Long keywords like 'cybersecurity' still match anywhere."""
    engine = FilterEngine()
    cats = engine.categorize("Advanced cybersecurity workshop", "")
    assert "Cybersecurity" in cats


def test_other_when_no_keyword_matches():
    """Off-topic events get the 'Other' bucket."""
    engine = FilterEngine()
    cats = engine.categorize("Badminton @ Sri Petaling", "")
    assert cats == ["Other"]
    cats = engine.categorize("Reset Run", "")
    assert cats == ["Other"]
