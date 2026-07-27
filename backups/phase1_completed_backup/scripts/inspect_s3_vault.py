import json
import boto3
from app.config import settings
from app.storage.compressor import zstd_compressor

def inspect_aws_s3_vault(prefix="raw/317c7f4f-8cb9-4ee9-b6d2-727c247f222d/github"):
    """
    Utility script to inspect, download, and decompress Zstandard (.json.zst) files
    directly from the live AWS S3 raw vault bucket.
    """
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
    )

    print("=======================================================")
    print(f"INSPECTING AWS S3 REAL GITHUB VAULT PAYLOADS")
    print(f"Bucket: {settings.S3_BUCKET_NAME}")
    print(f"Prefix: {prefix}")
    print("=======================================================")

    response = s3_client.list_objects_v2(Bucket=settings.S3_BUCKET_NAME, Prefix=prefix)
    contents = response.get("Contents", [])

    if not contents:
        print(f"No objects found under prefix: {prefix}")
        return

    print(f"\nFound {len(contents)} real GitHub payloads in AWS S3:")
    print("=" * 75)

    for idx, obj in enumerate(contents, 1):
        s3_key = obj["Key"]
        size_bytes = obj["Size"]
        last_modified = obj["LastModified"]

        print(f"\n[{idx}] S3 Key: {s3_key}")
        print(f"    S3 Size (Compressed Zstd): {size_bytes} Bytes")
        print(f"    Uploaded At: {last_modified}")

        # Download object from S3
        s3_obj = s3_client.get_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
        compressed_bytes = s3_obj["Body"].read()

        # Decompress with Zstandard
        decompressed_json = zstd_compressor.decompress_json(compressed_bytes)
        uncompressed_size = len(json.dumps(decompressed_json).encode("utf-8"))
        ratio = (1 - (size_bytes / uncompressed_size)) * 100 if uncompressed_size > 0 else 0

        print(f"    Uncompressed JSON Size:    {uncompressed_size} Bytes")
        print(f"    Zstd Compression Ratio:   {ratio:.1f}% space saved")
        print("    Decompressed Real GitHub Payload Preview:")
        print("    " + json.dumps(decompressed_json, indent=2)[:400].replace("\n", "\n    ") + " ...")
        print("-" * 75)

if __name__ == "__main__":
    inspect_aws_s3_vault()
