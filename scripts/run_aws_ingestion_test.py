import os
import sys
import boto3

# Add project root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.storage.compressor import zstd_compressor
from app.connectors.slack import SlackConnector
from app.connectors.google_drive import GoogleDriveConnector
from app.connectors.github import GitHubConnector
from app.connectors.jira import JiraConnector

def run_aws_ingestion_test(access_key: str, secret_key: str, bucket_name: str = "company-brain-raw-data-vault", region: str = "ap-south-1"):
    print("\n=======================================================")
    print(f"Connecting to AWS S3 Bucket: '{bucket_name}' ({region})")
    print("=======================================================\n")

    s3_client = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    tenant_id = "tenant_acme_corp"

    # Sample test connectors
    connectors = [
        SlackConnector(),
        GoogleDriveConnector(),
        GitHubConnector(),
        JiraConnector(),
    ]

    uploaded_keys = []

    for conn in connectors:
        source_app = conn.source_app
        print(f"Processing {source_app.upper()} connector data...")

        # Build test resource
        if source_app == "slack":
            res_type = "message"
            ext_id = "slack_msg_1001"
            payload = {"type": "message", "user": "U12345", "text": "Welcome to Company Brain Phase 1 AWS test!", "channel": "C98765"}
        elif source_app == "google_drive":
            res_type = "file"
            ext_id = "gdrive_file_2002"
            payload = {"name": "Q3_Strategy_Roadmap.pdf", "mimeType": "application/pdf", "owner": "alice@acme.com"}
        elif source_app == "github":
            res_type = "pull_request"
            ext_id = "github_pr_3003"
            payload = {"number": 42, "title": "PR #42: Add Zstd Compression to AWS S3", "user": "octocat"}
        else:
            res_type = "issue"
            ext_id = "jira_issue_PROJ-101"
            payload = {"key": "PROJ-101", "summary": "Configure Multi-Tenant Security", "creator": "dev_lead"}

        # Compress payload using Zstandard (.json.zst)
        zstd_bytes = zstd_compressor.compress_json(payload)
        
        # S3 Path Convention
        s3_key = f"raw/{tenant_id}/{source_app}/{res_type}/{ext_id}.json.zst"

        # Upload directly to AWS S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=zstd_bytes,
            ContentType="application/zstd",
            Metadata={
                "tenant_id": tenant_id,
                "source_app": source_app,
                "is_compressed": "true",
            }
        )

        print(f"   [SUCCESS] Uploaded compressed object to AWS S3:")
        print(f"             s3://{bucket_name}/{s3_key} ({len(zstd_bytes)} bytes compressed)")
        uploaded_keys.append(s3_key)

    print("\n=======================================================")
    print(f"TEST COMPLETE! Successfully uploaded {len(uploaded_keys)} objects to AWS S3.")
    print("Go refresh your AWS S3 Console browser page to see the 'raw/' folder!")
    print("=======================================================\n")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/run_aws_ingestion_test.py <AWS_ACCESS_KEY_ID> <AWS_SECRET_ACCESS_KEY>")
        sys.exit(1)
        
    access_key_arg = sys.argv[1]
    secret_key_arg = sys.argv[2]
    run_aws_ingestion_test(access_key_arg, secret_key_arg)
