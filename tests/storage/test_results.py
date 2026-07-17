import os

import pytest

from app.storage.results import (
    cleanup_expired_results,
    read_markdown_slice,
    result_paths,
    write_result,
)


def test_write_result_creates_markdown_and_metadata(tmp_path):
    paths = write_result(
        tmp_path, "cr_001", "# Title\n\nBody", {"job_id": "cr_001", "status": "SUCCESS"}
    )

    assert paths.markdown_path.read_text(encoding="utf-8") == "# Title\n\nBody"
    assert paths.metadata_path.exists()
    assert '"status": "SUCCESS"' in paths.metadata_path.read_text(encoding="utf-8")


def test_result_paths_layout(tmp_path):
    paths = result_paths(tmp_path, "cr_002")

    assert paths.job_dir == tmp_path / "results" / "cr_002"
    assert paths.markdown_path == paths.job_dir / "content.md"
    assert paths.metadata_path == paths.job_dir / "metadata.json"


def test_read_markdown_slice_paginates(tmp_path):
    write_result(tmp_path, "cr_003", "0123456789", {"job_id": "cr_003"})

    chunk, next_offset, has_more = read_markdown_slice(tmp_path, "cr_003", offset=0, max_chars=4)
    assert (chunk, next_offset, has_more) == ("0123", 4, True)

    chunk, next_offset, has_more = read_markdown_slice(tmp_path, "cr_003", offset=4, max_chars=100)
    assert (chunk, next_offset, has_more) == ("456789", 10, False)


def test_read_markdown_slice_missing_job_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_markdown_slice(tmp_path, "does-not-exist", offset=0, max_chars=100)


def test_cleanup_removes_only_expired_dirs(tmp_path):
    write_result(tmp_path, "cr_old", "old", {"job_id": "cr_old"})
    write_result(tmp_path, "cr_new", "new", {"job_id": "cr_new"})

    old_dir = result_paths(tmp_path, "cr_old").job_dir
    new_dir = result_paths(tmp_path, "cr_new").job_dir

    now = 1_000_000
    os.utime(old_dir, (now - 1000, now - 1000))
    os.utime(new_dir, (now - 100, now - 100))

    removed = cleanup_expired_results(tmp_path, now=now, ttl_seconds=500)

    assert removed == ["cr_old"]
    assert not old_dir.exists()
    assert new_dir.exists()


def test_cleanup_handles_missing_results_root(tmp_path):
    removed = cleanup_expired_results(tmp_path / "does-not-exist", now=0, ttl_seconds=500)
    assert removed == []
