"""
Lambda Function 1: presign_handler.py
Generates a presigned S3 URL for direct client-side upload.
Triggered by: POST /presign (API Gateway)
"""

import json
import uuid
import boto3
import os
from botocore.exceptions import ClientError

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

UPLOAD_BUCKET = os.environ['UPLOAD_BUCKET']          # e.g. pixelforge-uploads
JOBS_TABLE    = os.environ['JOBS_TABLE']              # DynamoDB table name
URL_EXPIRY    = int(os.environ.get('URL_EXPIRY', 300)) # seconds (5 min default)

ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/bmp', 'image/tiff'}


def handler(event, context):
    """
    Expects JSON body:
    {
        "filename":    "photo.jpg",
        "contentType": "image/jpeg"
    }
    Returns:
    {
        "uploadUrl": "https://...",
        "fileKey":   "uploads/<jobId>/photo.jpg",
        "jobId":     "<uuid>"
    }
    """
    try:
        body = json.loads(event.get('body', '{}'))
        filename    = body.get('filename', 'upload.jpg')
        content_type = body.get('contentType', 'image/jpeg')

        # Validate content type
        if content_type not in ALLOWED_TYPES:
            return response(400, {'error': f'Unsupported content type: {content_type}'})

        # Generate a unique job ID and S3 key
        job_id   = str(uuid.uuid4())
        safe_name = secure_filename(filename)
        file_key  = f"uploads/{job_id}/{safe_name}"

        # Generate presigned PUT URL
        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket':      UPLOAD_BUCKET,
                'Key':         file_key,
                'ContentType': content_type,
            },
            ExpiresIn=URL_EXPIRY
        )

        # Create job record in DynamoDB
        table = dynamodb.Table(JOBS_TABLE)
        table.put_item(Item={
            'jobId':      job_id,
            'status':     'pending',
            'fileKey':    file_key,
            'filename':   safe_name,
            'createdAt':  context.aws_request_id,
            'ttl':        get_ttl(hours=24)
        })

        return response(200, {
            'uploadUrl': upload_url,
            'fileKey':   file_key,
            'jobId':     job_id
        })

    except ClientError as e:
        print(f"AWS Error: {e}")
        return response(500, {'error': 'AWS service error'})
    except Exception as e:
        print(f"Error: {e}")
        return response(500, {'error': 'Internal server error'})


def secure_filename(filename: str) -> str:
    """Sanitize filename to avoid path traversal."""
    import re
    filename = os.path.basename(filename)
    filename = re.sub(r'[^\w\s\-.]', '', filename)
    return filename[:200] or 'upload'


def get_ttl(hours: int = 24) -> int:
    import time
    return int(time.time()) + hours * 3600


def response(status_code: int, body: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',         # Restrict in production!
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'POST,OPTIONS'
        },
        'body': json.dumps(body)
    }
