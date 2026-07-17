import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResultPaths:
    job_dir: Path
    markdown_path: Path
    metadata_path: Path


def result_paths(data_dir: Path, job_id: str) -> ResultPaths:
    job_dir = data_dir / "results" / job_id
    return ResultPaths(
        job_dir=job_dir,
        markdown_path=job_dir / "content.md",
        metadata_path=job_dir / "metadata.json",
    )


def write_result(
    data_dir: Path, job_id: str, markdown: str, metadata: dict[str, Any]
) -> ResultPaths:
    paths = result_paths(data_dir, job_id)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.markdown_path.write_text(markdown, encoding="utf-8")
    paths.metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths


def read_markdown_slice(
    data_dir: Path, job_id: str, offset: int, max_chars: int
) -> tuple[str, int, bool]:
    paths = result_paths(data_dir, job_id)
    if not paths.markdown_path.exists():
        raise FileNotFoundError(job_id)
    text = paths.markdown_path.read_text(encoding="utf-8")
    chunk = text[offset : offset + max_chars]
    next_offset = offset + len(chunk)
    has_more = next_offset < len(text)
    return chunk, next_offset, has_more


def cleanup_expired_results(data_dir: Path, now: float, ttl_seconds: int) -> list[str]:
    """删除超过 ttl_seconds 未修改的结果目录，返回被删除的 job_id 列表。"""
    results_root = data_dir / "results"
    if not results_root.exists():
        return []

    removed = []
    for job_dir in sorted(results_root.iterdir()):
        if not job_dir.is_dir():
            continue
        if now - job_dir.stat().st_mtime > ttl_seconds:
            shutil.rmtree(job_dir)
            removed.append(job_dir.name)
    return removed
