from oracle.common.embeddings import ChunkToIndex, VectorIndex


def test_search_on_an_empty_index_returns_nothing(vector_index: VectorIndex) -> None:
    assert vector_index.search("anything", limit=10) == []


def test_search_returns_nearest_chunks_first(vector_index: VectorIndex) -> None:
    vector_index.index_chunks(
        1,
        [
            ChunkToIndex(chunk_id=1, text="the quick brown fox"),
            ChunkToIndex(chunk_id=2, text="annual financial revenue report"),
        ],
    )

    matches = vector_index.search("quick fox", limit=10)

    assert [match.chunk_id for match in matches] == [1, 2]
    assert matches[0].distance < matches[1].distance


def test_search_respects_the_limit(vector_index: VectorIndex) -> None:
    vector_index.index_chunks(
        1,
        [ChunkToIndex(chunk_id=i, text=f"chunk number {i}") for i in range(5)],
    )

    matches = vector_index.search("chunk number", limit=3)

    assert len(matches) == 3


def test_index_chunks_with_no_chunks_is_a_noop(vector_index: VectorIndex) -> None:
    vector_index.index_chunks(1, [])

    assert vector_index.search("anything", limit=10) == []


def test_reindexing_a_chunk_id_overwrites_it(vector_index: VectorIndex) -> None:
    vector_index.index_chunks(1, [ChunkToIndex(chunk_id=1, text="old text")])
    vector_index.index_chunks(1, [ChunkToIndex(chunk_id=1, text="new words entirely")])

    matches = vector_index.search("new words entirely", limit=10)

    assert [match.chunk_id for match in matches] == [1]
    assert matches[0].distance < 0.001


def test_delete_document_removes_only_its_chunks(vector_index: VectorIndex) -> None:
    vector_index.index_chunks(1, [ChunkToIndex(chunk_id=1, text="first document")])
    vector_index.index_chunks(2, [ChunkToIndex(chunk_id=2, text="second document")])

    vector_index.delete_document(1)

    matches = vector_index.search("document", limit=10)
    assert [match.chunk_id for match in matches] == [2]


def test_delete_document_for_an_unknown_doc_is_a_noop(
    vector_index: VectorIndex,
) -> None:
    vector_index.index_chunks(1, [ChunkToIndex(chunk_id=1, text="first document")])

    vector_index.delete_document(999)

    matches = vector_index.search("document", limit=10)
    assert [match.chunk_id for match in matches] == [1]
