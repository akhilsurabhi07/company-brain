import asyncio
import io
import json
from typing import Any, Dict, List, Tuple, BinaryIO, Optional
import boto3
from botocore.config import Config
from app.config import settings
from app.storage.compressor import zstd_compressor

class S3StorageEngine:
    """
    AWS S3 / MinIO Raw Payload & Binary Storage Engine.
    Handles lossless Zstandard (.json.zst) uploads, downloads, parallel streams,
    and S3 Multipart File Streaming for large binary files (> 50MB) without RAM spikes.
    """

    def __init__(self):
        self.bucket_name = settings.S3_BUCKET_NAME
        self.region = settings.S3_REGION
        
        # High-performance Boto3 client with connection pooling
        boto_config = Config(
            region_name=self.region,
            max_pool_connections=50,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=boto_config,
        )

    def save_raw_json(
        self,
        tenant_id: str,
        source_app: str,
        resource_type: str,
        external_id: str,
        raw_payload: Dict[str, Any],
        compress: bool = True,
    ) -> Tuple[str, int]:
        """
        Saves raw payload dict to S3 under key: raw/{tenant_id}/{source_app}/{resource_type}/{external_id}.json.zst
        Returns tuple: (s3_key, file_size_bytes)
        """
        ext = "json.zst" if compress else "json"
        s3_key = f"raw/{tenant_id}/{source_app}/{resource_type}/{external_id}.{ext}"

        if compress:
            payload_bytes = zstd_compressor.compress_json(raw_payload)
            content_type = "application/zstd"
        else:
            payload_bytes = json.dumps(raw_payload).encode("utf-8")
            content_type = "application/json"

        file_len = len(payload_bytes)

        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=s3_key,
            Body=payload_bytes,
            ContentType=content_type,
            Metadata={
                "tenant_id": tenant_id,
                "source_app": source_app,
                "resource_type": resource_type,
                "external_id": external_id,
                "is_compressed": str(compress),
            },
        )
        return s3_key, file_len

    def stream_large_binary(
        self,
        tenant_id: str,
        source_app: str,
        resource_type: str,
        external_id: str,
        file_obj: BinaryIO,
        mime_type: str = "application/octet-stream",
        file_extension: str = "bin",
    ) -> Tuple[str, int]:
        """
        Improvement 3: S3 Multipart File Streaming for large binary files (> 50MB).
        Streams directly from file/socket to S3 without buffering entire contents in RAM.
        """
        s3_key = f"raw/{tenant_id}/{source_app}/{resource_type}/{external_id}.{file_extension}"

        # Get file size if seekable
        file_len = 0
        try:
            file_obj.seek(0, io.SEEK_END)
            file_len = file_obj.tell()
            file_obj.seek(0)
        except Exception:
            pass

        self.s3_client.upload_fileobj(
            Fileobj=file_obj,
            Bucket=self.bucket_name,
            Key=s3_key,
            ExtraArgs={
                "ContentType": mime_type,
                "Metadata": {
                    "tenant_id": tenant_id,
                    "source_app": source_app,
                    "resource_type": resource_type,
                    "external_id": external_id,
                    "is_large_binary": "True",
                },
            },
        )
        return s3_key, file_len

    async def async_save_raw_json(
        self,
        tenant_id: str,
        source_app: str,
        resource_type: str,
        external_id: str,
        raw_payload: Dict[str, Any],
        compress: bool = True,
    ) -> Tuple[str, int]:
        """Async wrapper for non-blocking S3 uploads."""
        return await asyncio.to_thread(
            self.save_raw_json,
            tenant_id,
            source_app,
            resource_type,
            external_id,
            raw_payload,
            compress,
        )

    async def save_batch_parallel(
        self,
        tenant_id: str,
        source_app: str,
        items: List[Dict[str, Any]],
        concurrency: int = 10,
    ) -> List[Tuple[str, int]]:
        """Parallel Batch S3 Uploads using asyncio.gather()."""
        semaphore = asyncio.Semaphore(concurrency)

        async def worker(item):
            async with semaphore:
                return await self.async_save_raw_json(
                    tenant_id=tenant_id,
                    source_app=source_app,
                    resource_type=item["resource_type"],
                    external_id=item["external_id"],
                    raw_payload=item["raw_payload"],
                    compress=True,
                )

        return await asyncio.gather(*(worker(item) for item in items))

    def fetch_raw_json(self, s3_key: str) -> Dict[str, Any]:
        """Downloads and decompresses raw payload from S3."""
        response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
        compressed_bytes = response["Body"].read()
        if s3_key.endswith(".zst"):
            return zstd_compressor.decompress_json(compressed_bytes)
        return json.loads(compressed_bytes.decode("utf-8"))

s3_storage = S3StorageEngine()
