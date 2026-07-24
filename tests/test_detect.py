from __future__ import annotations

from translator.detect import detect_language


def test_chinese_prose() -> None:
    d = detect_language("萧炎盯着面前的老者，心中充满了疑惑。斗气大陆，强者为尊。")
    assert d.language == "zh"
    assert d.confidence > 0.5


def test_japanese_prose_with_kana() -> None:
    d = detect_language("彼は静かに部屋へ入って、窓の外を眺めていた。")
    assert d.language == "ja"
    assert d.confidence > 0.8


def test_korean_prose() -> None:
    d = detect_language("그는 조용히 방으로 들어가 창밖을 바라보았다.")
    assert d.language == "ko"
    assert d.confidence > 0.8


def test_english_prose() -> None:
    d = detect_language("He quietly entered the room and stared out the window.")
    assert d.language == "en"


def test_html_is_stripped_before_detection() -> None:
    d = detect_language("<p>그는 <b>조용히</b> 방으로 들어갔다.</p>")
    assert d.language == "ko"


def test_empty_input_is_unknown() -> None:
    assert detect_language("   ").language == "und"
    assert detect_language("<p></p>").language == "und"


def test_hanzi_only_title_reports_zh_with_moderate_confidence() -> None:
    # A kanji-only Japanese title is indistinguishable from Chinese;
    # we report zh but must not claim near-certainty on a short title.
    d = detect_language("転生賢者")
    assert d.language == "zh"
    assert d.confidence < 0.8


def test_latin_text_quoting_hanzi_terms_is_not_chinese() -> None:
    # A few hanzi names inside latin-script prose must not hijack detection;
    # the statistical detector judges the dominant script instead.
    d = detect_language("The protagonist opened the 斗气大陆 map and smiled.")
    assert d.language == "en"
