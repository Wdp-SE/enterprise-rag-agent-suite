from src.embedding_text import EmbeddingTextBuilder, RetrievalTextMode


def test_child_only_is_exact_evidence_text():
    builder = EmbeddingTextBuilder()
    child = "  evidence text remains unchanged  "

    result = builder.build(
        RetrievalTextMode.CHILD_ONLY,
        child_text=child,
        section_title="ignored",
        section_path=["ignored"],
        document_title="ignored",
    )

    assert result.retrieval_text == child
    assert result.metadata_characters == 0


def test_section_path_is_normalized_and_deduplicated():
    builder = EmbeddingTextBuilder()
    child = "child"

    result = builder.build(
        RetrievalTextMode.SECTION_PATH,
        child_text=child,
        section_title=" Interface ",
        section_path=[" System  Design ", "Interface", "interface"],
    )

    assert result.retrieval_text == (
        "[Section]\nSystem Design > Interface\n\n[Content]\nchild"
    )
    assert result.path_component_count == 2
    assert result.retrieval_text.endswith(child)


def test_document_title_is_not_repeated_in_section_path():
    builder = EmbeddingTextBuilder()

    result = builder.build(
        RetrievalTextMode.DOCUMENT_SECTION_PATH,
        child_text="child",
        document_title="Design",
        section_path=["Design", "API"],
        section_title="API",
    )

    assert result.retrieval_text.count("Design") == 1
    assert result.retrieval_text.count("API") == 1
    assert result.document_title_included


def test_empty_metadata_falls_back_to_unchanged_child():
    builder = EmbeddingTextBuilder()

    result = builder.build(
        RetrievalTextMode.DOCUMENT_SECTION_PATH,
        child_text="child",
        document_title="",
        section_path=[],
        section_title="",
    )

    assert result.retrieval_text == "child"
    assert not result.section_metadata_included


def test_long_path_is_limited_without_truncating_child():
    builder = EmbeddingTextBuilder(max_path_components=2, max_path_characters=12)
    child = "full child body"

    result = builder.build(
        RetrievalTextMode.SECTION_PATH,
        child_text=child,
        section_path=["ancestor", "middle", "very-long-leaf-title"],
    )

    assert result.path_was_limited
    assert result.retrieval_text.endswith(child)
    assert child in result.retrieval_text
