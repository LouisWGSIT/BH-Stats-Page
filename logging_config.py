import logging
import json
import time
import request_context

class JSONFormatter(logging.Formatter):
    """Simple JSON formatter that includes request_id from `request_context`.

    Keeps dependencies minimal so no external packages are required.
    """
    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(record.created))
        rid = None
        try:
            rid = request_context.request_id.get()
        except Exception:
            rid = None

        log_record = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": rid,
            "pathname": record.pathname,
            "func": record.funcName,
            "lineno": record.lineno,
        }

        # Attach exception information if present
        if record.exc_info:
            try:
                log_record["exc"] = self.formatException(record.exc_info)
            except Exception:
                log_record["exc"] = str(record.exc_info)

        # Include any user-supplied extra fields if they are JSON-serializable
        for key, value in record.__dict__.items():
            if key in ("name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs", "relativeCreated", "thread", "threadName", "processName", "process"):
                continue
            try:
                json.dumps({key: value})
                log_record[key] = value
            except Exception:
                try:
                    log_record[key] = str(value)
                except Exception:
                    pass

        return json.dumps(log_record)


def configure_logging(level=logging.INFO):
    root = logging.getLogger()
    # Avoid duplicate handlers if already configured
    if root.handlers:
        return
    root.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)


__all__ = ["configure_logging", "JSONFormatter"]
