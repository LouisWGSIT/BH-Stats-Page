from contextvars import ContextVar

# Context variable to hold the current request id for logging correlation
request_id = ContextVar('request_id', default=None)
