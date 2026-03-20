web: uvicorn main:app --host 0.0.0.0 --port $PORT
worker: rq worker exports --url $REDIS_URL
