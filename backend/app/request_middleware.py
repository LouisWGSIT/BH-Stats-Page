from datetime import UTC, datetime
from time import time
from uuid import uuid4


def create_request_id_middleware(
    *,
    request_context_module,
    should_record_request,
    get_client_ip,
    get_process_rss_bytes,
    record_activity,
):
    """Build middleware that adds request IDs and records lightweight activity telemetry."""

    async def middleware(request, call_next):
        rid = uuid4().hex
        request_context_module.request_id.set(rid)
        start_ts = time()
        try:
            response = await call_next(request)
            response.headers['X-Request-ID'] = rid
            return response
        finally:
            request_context_module.request_id.set(None)
            try:
                do_record = True
                try:
                    if not should_record_request(request):
                        do_record = False
                except Exception:
                    do_record = True

                if do_record:
                    dur = int((time() - start_ts) * 1000)
                    try:
                        client_ip = get_client_ip(request)
                    except Exception:
                        client_ip = request.client.host if request.client else '0.0.0.0'
                    rss = get_process_rss_bytes()
                    record_activity(
                        {
                            'ts': datetime.now(UTC).replace(tzinfo=None).isoformat(),
                            'request_id': rid,
                            'path': request.url.path,
                            'method': request.method,
                            'client_ip': client_ip,
                            'user_agent': (request.headers.get('User-Agent') or '')[:256],
                            'status_code': getattr(response, 'status_code', None),
                            'duration_ms': dur,
                            'rss': rss,
                        }
                    )
            except Exception:
                pass

    return middleware
