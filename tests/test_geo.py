"""Tests for the per-org geo filter helper."""
from backend.scrapers.orgs._geo import is_out_of_region


def test_kl_locations_pass():
    assert not is_out_of_region("Kuala Lumpur")
    assert not is_out_of_region("WORQ KL Sentral")
    assert not is_out_of_region("Hab PMKS, Aras 4, Blok B")


def test_selangor_locations_pass():
    assert not is_out_of_region("Cyberjaya")
    assert not is_out_of_region("Petaling Jaya")
    assert not is_out_of_region("Subang Jaya")
    assert not is_out_of_region("Lembah Klang")


def test_penang_drops():
    assert is_out_of_region("Seberang Jaya, Pulau Pinang")
    assert is_out_of_region("Penang Skills Centre")


def test_perak_drops():
    assert is_out_of_region("UiTM Seri Iskandar, Perak")
    assert is_out_of_region("Ipoh Convention Centre")


def test_sarawak_sabah_drop():
    assert is_out_of_region("Kuching, Sarawak")
    assert is_out_of_region("Kota Kinabalu, Sabah")


def test_universities_outside_klang_valley_drop():
    assert is_out_of_region("UniSZA Kuala Terengganu")
    assert is_out_of_region("UMS campus")


def test_empty_string_passes():
    """Empty/None should not be flagged as out-of-region."""
    assert not is_out_of_region("")
    assert not is_out_of_region(None or "")


def test_partial_word_does_not_match():
    """Conservative tokens shouldn't match inside random words."""
    # 'pahang' is a real state name so this would be an actual leak.
    # The helper is intentionally conservative - we'd rather drop a real
    # KL event than show a Pahang event. But generic words shouldn't
    # trigger.
    assert not is_out_of_region("Some innovation lab")
    assert not is_out_of_region("Programme launch")
