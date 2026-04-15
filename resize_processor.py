"""
Lambda Function 3: resize_processor.py
Core image resizing logic using Pillow.
Triggered by: Async Lambda invoke from resize_handler.py
              OR directly via S3 trigger (optional pattern).

Requires Pillow Lambda Layer:
  arn:aws:lambda:<region>:770693421928:layer:Klayers-p311-Pillow:1
  (or build your own — see README)
"""

import io
import json
import os
import time
import boto3
from PIL import Image, ImageOps

s3_client  = boto3.client('s3')
dynamodb   = boto3.resource('dynamodb')

UPLOAD_BUCKET = os.environ['UPLOAD_BUCKET']
OUTPUT_BUCKET = os.environ['OUTPUT_BUCKET']
JOBS_TABLE    = os.environ['JOBS_TABLE']
OUTPUT_PREFIX = os.environ.get('OUTPUT_PREFIX', 'resized')

# Pillow resampling filter (LANCZOS = highest quality)
RESAMPLE = Image.Resampling.LANCZOS

FORMAT_MAP = {
    'jpeg': ('JPEG', 'image/jpeg', '.jpg'),
    'png':  ('PNG',  'image/png',  '.png'),
    'webp': ('WEBP', 'image/webp', '.webp'),
}


def handler(event, context):
    """
    Expects event payload:
    {
        "jobId":   "<uuid>",
        "fileKey": "uploads/<jobId>/photo.jpg",
        "width":   800,
        "height":  600,
        "format":  "jpeg",
        "quality": 85
    }
    """
    job_id   = event['jobId']
    file_key = event['fileKey']
    width    = int(event['width'])
    height   = int(event['height'])
    fmt      = event.get('format', 'jpeg').lower()
    quality  = int(event.get('quality', 85))

    table = dynamodb.Table(JOBS_TABLE)

    try:
        # ── 1. Download original image from S3 ──────────────────────────────
        print(f"[{job_id}] Downloading: s3://{UPLOAD_BUCKET}/{file_key}")
        s3_obj   = s3_client.get_object(Bucket=UPLOAD_BUCKET, Key=file_key)
        img_data = s3_obj['Body'].read()
        orig_size = len(img_data)

        # ── 2. Open and validate image ───────────────────────────────────────
        img = Image.open(io.BytesIO(img_data))
        img = ImageOps.exif_transpose(img)  # Auto-rotate based on EXIF
        orig_w, orig_h = img.size
        print(f"[{job_id}] Original: {orig_w}×{orig_h} {img.mode}")

        # ── 3. Convert to RGB/RGBA if needed ────────────────────────────────
        pil_format, mime_type, ext = FORMAT_MAP.get(fmt, FORMAT_MAP['jpeg'])
        if pil_format == 'JPEG' and img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        elif pil_format == 'PNG' and img.mode not in ('RGB', 'RGBA', 'L', 'LA'):
            img = img.convert('RGBA')
        elif pil_format == 'WEBP' and img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        # ── 4. Resize ────────────────────────────────────────────────────────
        target_size = (width, height)
        img = img.resize(target_size, RESAMPLE)
        print(f"[{job_id}] Resized to: {img.size}")

        # ── 5. Encode output ─────────────────────────────────────────────────
        out_buffer = io.BytesIO()
        save_kwargs = {}

        if pil_format == 'JPEG':
            save_kwargs = {'quality': quality, 'optimize': True, 'progressive': True}
        elif pil_format == 'WEBP':
            save_kwargs = {'quality': quality, 'method': 4}
        elif pil_format == 'PNG':
            save_kwargs = {'optimize': True, 'compress_level': 6}

        img.save(out_buffer, format=pil_format, **save_kwargs)
        out_data  = out_buffer.getvalue()
        out_size  = len(out_data)
        reduction = round((1 - out_size / orig_size) * 100, 1) if orig_size else 0
        print(f"[{job_id}] Output size: {out_size} bytes ({reduction}% reduction)")

        # ── 6. Upload resized image to S3 ────────────────────────────────────
        result_key = f"{OUTPUT_PREFIX}/{job_id}/resized{ext}"
        s3_client.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=result_key,
            Body=out_data,
            ContentType=mime_type,
            CacheControl='max-age=86400',
            Metadata={
                'jobId':     job_id,
                'origWidth': str(orig_w),
                'origHeight': str(orig_h),
                'width':     str(width),
                'height':    str(height),
                'format':    fmt
            }
        )

        # ── 7. Generate presigned GET URL (expires 1h) ───────────────────────
        result_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': OUTPUT_BUCKET, 'Key': result_key},
            ExpiresIn=3600
        )

        # ── 8. Update DynamoDB: done ─────────────────────────────────────────
        table.update_item(
            Key={'jobId': job_id},
            UpdateExpression='''SET #s = :s, resultKey = :rk, resultUrl = :ru,
                                    finalWidth = :w, finalHeight = :h,
                                    outputSize = :os, completedAt = :ca''',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={
                ':s':  'done',
                ':rk': result_key,
                ':ru': result_url,
                ':w':  width,
                ':h':  height,
                ':os': out_size,
                ':ca': int(time.time())
            }
        )

        print(f"[{job_id}] ✓ Complete. Result: s3://{OUTPUT_BUCKET}/{result_key}")
        return {'statusCode': 200, 'jobId': job_id, 'resultUrl': result_url}

    except Exception as e:
        print(f"[{job_id}] ✗ Error: {e}")
        table.update_item(
            Key={'jobId': job_id},
            UpdateExpression='SET #s = :s, errorMsg = :e',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':s': 'error', ':e': str(e)}
        )
        raise
