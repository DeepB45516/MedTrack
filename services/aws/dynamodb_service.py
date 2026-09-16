"""
FUTURE (Phase 2) — DynamoDB integration.

Not used in the current local phase. Nothing here runs or is imported
by the app unless config.DYNAMODB_ENABLED is explicitly set to true,
and boto3 is only ever imported lazily inside methods so the local app
never fails to start without AWS credentials.

Planned table mapping (1 SQLite table -> 1 DynamoDB table):
    users          -> medtrack-users          (PK: id)
    doctors        -> medtrack-doctors        (PK: id, GSI: user_id)
    appointments   -> medtrack-appointments   (PK: id, GSI: patient_id, GSI: doctor_id)
    diagnoses      -> medtrack-diagnoses      (PK: id, GSI: patient_id)
    notifications  -> medtrack-notifications  (PK: id, GSI: user_id)

Intended surface (to mirror database/database.py so route/service code
does not change when this is switched on):
    - get_item(table, key)
    - put_item(table, item)
    - query(table, index_name, key_condition)
    - update_item(table, key, updates)
    - delete_item(table, key)
"""


class DynamoDBService:
    def __init__(self, region_name="ap-south-1"):
        self.region_name = region_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy import: never required for local phase
            self._client = boto3.resource("dynamodb", region_name=self.region_name)
        return self._client

    def get_item(self, table, key):
        raise NotImplementedError("DynamoDB integration is planned for Phase 2.")

    def put_item(self, table, item):
        raise NotImplementedError("DynamoDB integration is planned for Phase 2.")

    def query(self, table, index_name, key_condition):
        raise NotImplementedError("DynamoDB integration is planned for Phase 2.")

    def update_item(self, table, key, updates):
        raise NotImplementedError("DynamoDB integration is planned for Phase 2.")

    def delete_item(self, table, key):
        raise NotImplementedError("DynamoDB integration is planned for Phase 2.")
