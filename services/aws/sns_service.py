"""
FUTURE (Phase 2) — SNS integration.

Mirrors services/notification_service.py's notify() call so switching
over is a matter of calling SNSService.publish() alongside (or instead
of) the local SQLite insert — no route changes needed. boto3 is
imported lazily so the local app never requires AWS credentials.
"""


class SNSService:
    def __init__(self, topic_arn=None, region_name="ap-south-1"):
        self.topic_arn = topic_arn
        self.region_name = region_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy import: never required for local phase
            self._client = boto3.client("sns", region_name=self.region_name)
        return self._client

    def publish(self, user_id, notif_type, message):
        raise NotImplementedError("SNS integration is planned for Phase 2.")
