from typing import Any

from app.storage.results import read_markdown_slice

_READABLE_STATUSES = {"SUCCESS", "PARTIAL"}


async def read_result_impl(
    service: Any, *, job_id: str, offset: int, max_chars: int
) -> dict[str, Any]:
    """读取已完成抓取结果，支持分段读取（第 4.2 节）。

    非 SUCCESS/PARTIAL 的任务原样返回其存储的 status/error（第 4.3 节最后一条），
    而不是返回"文件不存在"这类二次抽象错误。
    """
    record = await service.db.get_by_job_id(job_id)
    if record is None:
        return {
            "job_id": job_id,
            "status": "FAILED",
            "error_code": "JOB_NOT_FOUND",
            "error_message": f"找不到 job_id: {job_id}",
        }

    if record.status not in _READABLE_STATUSES:
        return {
            "job_id": job_id,
            "status": record.status,
            "error_code": record.error_code,
            "error_message": record.error_message,
        }

    try:
        chunk, next_offset, has_more = read_markdown_slice(
            service.data_dir, job_id, offset=offset, max_chars=max_chars
        )
    except FileNotFoundError:
        return {
            "job_id": job_id,
            "status": "FAILED",
            "error_code": "INTERNAL_ERROR",
            "error_message": "结果文件缺失，可能已过期被清理。",
        }

    return {
        "job_id": job_id,
        "status": record.status,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": has_more,
        "markdown": chunk,
    }
