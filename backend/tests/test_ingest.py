import uuid

import pytest

from oracle.common.ingest import UnsupportedFileTypeError, ingest_file


@pytest.mark.parametrize("suffix", [".pdf", ".docx", ".PDF"])
def test_ingest_file_copies_with_uuid_name(tmp_path, suffix):
    source = tmp_path / f"source{suffix}"
    source.write_bytes(b"file contents")
    uploads_dir = tmp_path / "uploads"

    destination = ingest_file(source, uploads_dir=uploads_dir)

    assert destination.parent == uploads_dir
    assert destination.suffix == suffix.lower()
    assert uuid.UUID(destination.stem)
    assert destination.read_bytes() == b"file contents"
    assert source.exists()


def test_ingest_file_creates_uploads_dir_if_missing(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"file contents")
    uploads_dir = tmp_path / "does" / "not" / "exist"

    destination = ingest_file(source, uploads_dir=uploads_dir)

    assert destination.exists()


def test_ingest_file_rejects_unsupported_extension(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"file contents")

    with pytest.raises(UnsupportedFileTypeError):
        ingest_file(source, uploads_dir=tmp_path / "uploads")


def test_ingest_file_raises_for_missing_source(tmp_path):
    source = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        ingest_file(source, uploads_dir=tmp_path / "uploads")
