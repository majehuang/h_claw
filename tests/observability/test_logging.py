import json
import logging

from app.observability.logging import RedactingJsonFormatter


def test_formatter_redacts_sensitive_extra_fields():
    formatter = RedactingJsonFormatter()
    record = logging.LogRecord(
        name="crawler", level=logging.INFO, pathname=__file__, lineno=1,
        msg="fetch done", args=(), exc_info=None,
    )
    record.job_id = "cr_1"
    record.extra = {"cookie": "session=secret", "domain": "shop.example.com"}

    output = json.loads(formatter.format(record))

    assert output["message"] == "fetch done"
    assert output["job_id"] == "cr_1"
    assert output["extra"]["cookie"] == "***"
    assert output["extra"]["domain"] == "shop.example.com"


def test_formatter_emits_valid_json():
    formatter = RedactingJsonFormatter()
    record = logging.LogRecord(
        name="crawler", level=logging.WARNING, pathname=__file__, lineno=1,
        msg="blocked", args=(), exc_info=None,
    )
    output = json.loads(formatter.format(record))
    assert output["level"] == "WARNING"
