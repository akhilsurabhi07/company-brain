import pytest
from app.storage.compressor import zstd_compressor

def test_zstd_compression_lossless_roundtrip():
    original_data = {
        "tenant_id": "tenant_12345",
        "app": "slack",
        "messages": [
            {"id": 1, "text": "Hello world, this is a test payload."},
            {"id": 2, "text": "Zstandard compression should save massive S3 storage!"}
        ]
    }
    
    # Compress JSON
    compressed_bytes = zstd_compressor.compress_json(original_data)
    assert isinstance(compressed_bytes, bytes)
    assert len(compressed_bytes) > 0

    # Decompress back to exact original JSON
    decompressed_data = zstd_compressor.decompress_json(compressed_bytes)
    assert decompressed_data == original_data

def test_zstd_text_compression():
    original_text = "Enterprise Knowledge Platform Ingestion Engine " * 50
    compressed_bytes = zstd_compressor.compress_text(original_text)
    
    # Verify significant compression ratio (> 50% savings)
    assert len(compressed_bytes) < len(original_text.encode("utf-8")) / 2
    
    # Decompress back
    decompressed_text = zstd_compressor.decompress_text(compressed_bytes)
    assert decompressed_text == original_text
