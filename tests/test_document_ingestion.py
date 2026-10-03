from document_ingestion import chunk_text


def test_chunk_text_creates_numbered_chunks_with_overlap():
    chunks = chunk_text("abcdefghij", source="note.md", chunk_size=4, overlap=1)

    assert [(item.chunk_id, item.text) for item in chunks] == [
        (1, "abcd"),
        (2, "defg"),
        (3, "ghij"),
    ]


def test_chunk_text_rejects_invalid_window():
    import pytest

    with pytest.raises(ValueError, match="overlap"):
        chunk_text("abc", source="note.md", chunk_size=3, overlap=3)


def test_chunk_text_keeps_source_and_starts_chunk_ids_at_one():
    chunks = chunk_text("abcdef", source="guide.md", chunk_size=3, overlap=0)

    assert [(item.source, item.chunk_id, item.text) for item in chunks] == [
        ("guide.md", 1, "abc"),
        ("guide.md", 2, "def"),
    ]


def test_chunk_text_keeps_short_final_chunk():
    chunks = chunk_text("abcdefgh", source="note.md", chunk_size=4, overlap=1)

    assert [item.text for item in chunks] == ["abcd", "defg", "gh"]
