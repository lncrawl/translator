import pytest

from translator.html_tools import (
    chunk_html,
    estimate_tokens,
    extract_segments,
    repair_untagged_output,
    tag_names,
)


def test_estimate_tokens_cjk_heavier_than_latin() -> None:
    assert estimate_tokens("好" * 100) > estimate_tokens("a" * 100)


def test_chunk_html_returns_single_chunk_when_small() -> None:
    html = "<p>hello</p><p>world</p>"
    assert chunk_html(html, max_tokens=1000) == [html]


def test_chunk_html_splits_on_block_boundaries() -> None:
    paragraphs = [f"<p>{'好' * 50}</p>" for _ in range(10)]
    html = "".join(paragraphs)
    chunks = chunk_html(html, max_tokens=120)
    assert len(chunks) > 1
    assert "".join(chunks) == html
    for chunk in chunks:
        assert chunk.startswith("<p>") and chunk.endswith("</p>")


def test_chunk_html_keeps_oversized_element_whole() -> None:
    html = f"<p>{'好' * 500}</p>"
    assert chunk_html(html, max_tokens=100) == [html]


def test_extract_segments_skips_untranslatable() -> None:
    html = (
        '<p>hello</p><code>x = 1</code><span translate="no">Xiao</span>'
        "<script>var a;</script><p>  </p><p>world</p>"
    )
    _, nodes = extract_segments(html)
    assert [str(n) for n in nodes] == ["hello", "world"]


def test_tag_names_order() -> None:
    assert tag_names("<p>a<b>c</b></p><p>d</p>") == ["p", "b", "p"]


@pytest.mark.parametrize(
    ("source", "output", "expected_wraps"),
    [
        ("<p>好</p><p>吗</p>", "hello\n\nthere", True),
        ("<p>好</p>", "<p>hello</p>", False),  # output already tagged
        ("plain source", "plain output", False),  # source had no tags
    ],
)
def test_repair_untagged_output(source: str, output: str, expected_wraps: bool) -> None:
    repaired = repair_untagged_output(source, output)
    if expected_wraps:
        assert repaired == "<p>hello</p><p>there</p>"
    else:
        assert repaired is None
