import httpx
import structlog
from config import settings

logger = structlog.get_logger()

# PagerDuty Events API v2 endpoint
PD_EVENTS_URL = "https://events.pagerduty.com/v2/enqueue"

async def trigger_incident(summary: str, source: str = "hyper_bot", severity: str = "critical", custom_details: dict = None):
    """
    Trigger a PagerDuty alert using Events API v2.
    """
    pd_routing_key = settings.PAGERDUTY_ROUTING_KEY
    if not pd_routing_key or pd_routing_key == "your_pg_routing_key_here":
        logger.warning("PG routing key not configured, skipping alert: " + summary)
        return

    payload = {
        "routing_key": pd_routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": summary,
            "source": source,
            "severity": severity,
            "custom_details": custom_details or {}
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(PD_EVENTS_URL, json=payload, timeout=10.0)
            resp.raise_for_status()
            logger.info("PagerDuty alert triggered successfully", summary=summary)
    except Exception as e:
        logger.error("Failed to trigger PagerDuty alert", error=str(e), summary=summary)
