"""
FUTURE (Phase 2) — S3 integration.

Mirrors the LocalFileService interface in services/diagnosis_service.py
(save_file / resolve_path / delete_file) so that switching
`get_file_service()` over to this class is a one-line change with no
route or template edits. boto3 is imported lazily so the local app
never requires AWS credentials to start.
"""


class S3Service:
    def __init__(self, bucket_name, region_name="ap-south-1"):
        self.bucket_name = bucket_name
        self.region_name = region_name
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3  # lazy import: never required for local phase
            self._client = boto3.client("s3", region_name=self.region_name)
        return self._client

    def allowed_file(self, filename):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in {"pdf", "jpg", "jpeg", "png"}

    def save_file(self, file_storage):
        raise NotImplementedError("S3 integration is planned for Phase 2.")

    def resolve_path(self, stored_name):
        # Phase 2: return a presigned URL instead of a filesystem path.
        raise NotImplementedError("S3 integration is planned for Phase 2.")

    def delete_file(self, stored_name):
        raise NotImplementedError("S3 integration is planned for Phase 2.")
