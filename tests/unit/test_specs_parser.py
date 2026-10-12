from specwatch.specs.parser import segment_markdown


def test_no_headings_returns_no_sections() -> None:
    assert segment_markdown("just some text\nmore text\n") == []


def test_single_heading_with_body() -> None:
    text = "# Title\n\nSome body text.\n"
    sections = segment_markdown(text)
    assert len(sections) == 1
    section = sections[0]
    assert section.heading == "Title"
    assert section.level == 1
    assert section.body == "Some body text."
    assert section.line_start == 1
    assert section.line_end == 3


def test_leaf_section_does_not_include_sibling_content() -> None:
    text = (
        "## Category\n"
        "\n"
        "### First\n"
        "\n"
        "First body.\n"
        "\n"
        "### Second\n"
        "\n"
        "Second body.\n"
    )
    sections = segment_markdown(text)
    headings = {s.heading: s for s in sections}
    assert headings["First"].body == "First body."
    assert headings["Second"].body == "Second body."


def test_container_section_own_body_excludes_nested_subsections() -> None:
    text = (
        "## Category intro\n"
        "\n"
        "### Child\n"
        "\n"
        "Child body must do something.\n"
    )
    sections = segment_markdown(text)
    headings = {s.heading: s for s in sections}
    assert headings["Category intro"].body == ""
    assert headings["Child"].body == "Child body must do something."


def test_line_end_excludes_trailing_blank_lines() -> None:
    text = "### Heading\n\nBody line.\n\n\n### Next\n\nOther.\n"
    sections = segment_markdown(text)
    first = sections[0]
    assert first.line_end == 3  # the "Body line." line, not the trailing blanks


def test_heading_with_no_body_uses_heading_line_as_line_end() -> None:
    text = "### Empty\n### Next\n\nSomething.\n"
    sections = segment_markdown(text)
    assert sections[0].heading == "Empty"
    assert sections[0].body == ""
    assert sections[0].line_start == sections[0].line_end == 1
