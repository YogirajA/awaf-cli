from __future__ import annotations

from awaf import report_html as rh


def test_esc_escapes_markup_and_quotes() -> None:
    out = rh._esc('<b> & "x"')
    assert "<b>" not in out
    assert "&lt;b&gt;" in out
    assert "&amp;" in out
    assert "&quot;" in out


def test_load_list_parses_and_degrades() -> None:
    assert rh._load_list("[1, 2, 3]") == [1, 2, 3]
    assert rh._load_list("not json") == []
    assert rh._load_list('{"a": 1}') == []  # non-list JSON degrades to []
    assert rh._load_list("") == []


def test_band_for_maps_score_to_label_and_blurb() -> None:
    label, blurb = rh._band_for(90)
    assert label == "Production Ready"
    assert blurb
    assert rh._band_for(72)[0] == "Near Ready"
    assert rh._band_for(0)[0] == "Not Ready"


def test_severity_bucket_classifies() -> None:
    assert rh._severity_bucket("Critical") == "high"
    assert rh._severity_bucket("HIGH") == "high"
    assert rh._severity_bucket("Medium") == "medium"
    assert rh._severity_bucket("low") == "low"
    assert rh._severity_bucket("informational") == "other"


def test_text_of_handles_str_and_dict() -> None:
    assert rh._text_of("hello") == "hello"
    assert rh._text_of({"detail": "a gap"}) == "a gap"
    assert rh._text_of({"other": "x"})  # falls back to a non-empty string


def test_pillars_in_sync_with_cli() -> None:
    from awaf.cli import _PILLAR_ROWS

    assert len(rh._PILLARS) == len(_PILLAR_ROWS)
    for (name, s_attr, c_attr, tier, _accent), (rname, rs, rc, is_t2) in zip(
        rh._PILLARS, _PILLAR_ROWS, strict=True
    ):
        assert (name, s_attr, c_attr) == (rname, rs, rc)
        assert (tier == 2) == is_t2
