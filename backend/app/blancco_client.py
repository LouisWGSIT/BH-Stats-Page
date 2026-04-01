import os

import httpx


def get_config():
    api_url = os.getenv("BLANCCO_API_URL", "")
    api_key = os.getenv("BLANCCO_API_KEY", "")
    qa_confirmed_score = int(os.getenv("QA_CONFIRMED_SCORE", "95"))
    return api_url, api_key, qa_confirmed_score


async def fetch_device_details(job_id: str, *, api_url: str, api_key: str, timeout_seconds: float = 5.0):
    """Fetch device details from Blancco API using job ID."""
    if not api_url or not job_id:
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            response = await client.get(
                f"{api_url}/reports/{job_id}",
                headers=headers,
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "manufacturer": data.get("hardware", {}).get("manufacturer"),
                    "model": data.get("hardware", {}).get("model"),
                    "drive_size": data.get("storage", {}).get("totalCapacity"),
                    "drive_count": data.get("storage", {}).get("driveCount"),
                    "drive_type": data.get("storage", {}).get("type"),
                }
    except Exception as e:
        print(f"[BLANCCO API] Failed to fetch device details for job {job_id}: {e}")

    return None
