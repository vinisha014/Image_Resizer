"""
Lambda Function 2: resize_handler.py
Triggered by: POST /resize (API Gateway)
Submits resize job metadata then triggers async processing Lambda.
"""

import json
import boto3
import os

dynamodb   = boto3.resource('dynamodb')
lambda_cli = boto3.client('lambda')

JOBS_TABLE       = os.environ['JOBS_TABLE']
PROCESSOR_FUNC   = os.environ['PROCESSOR_FUNCTION_NAME']  # ARN of resize_processor Lambda


def handler(event, context):
    """
    Expects JSON body:
    {
        "fileKey":  "uploads/<jobId>/photo.jpg",
        "jobId":    "<uuid>",
        "width":    800,
        "height":   600,
        "format":   "jpeg",
        "quality":  85
    }
    Returns:
    {
        "jobId": "<uuid>",
        "status": "processing"
    }
    """
    try:
        body    = json.loads(event.get('body', '{}'))
        job_id  = body.get('jobId')
        file_key = body.get('fileKey')
        width   = int(body.get('width', 800))
        height  = int(body.get('height', 600))
        fmt     = body.get('format', 'jpeg').lower()
        quality = min(max(int(body.get('quality', 85)), 1), 100)

        if not job_id or not file_key:
            return response(400, {'error': 'jobId and fileKey are required'})

        if fmt not in ('jpeg', 'png', 'webp'):
            return response(400, {'error': f'Unsupported format: {fmt}'})

        if not (1 <= width <= 8000) or not (1 <= height <= 8000):
            return response(400, {'error': 'Dimensions must be between 1 and 8000px'})

        # Update job status to "processing"
        table = dynamodb.Table(JOBS_TABLE)
        table.update_item(
            Key={'jobId': job_id},
            UpdateExpression='SET #s = :s, width = :w, height = :h, #f = :f, quality = :q',
            ExpressionAttributeNames={'#s': 'status', '#f': 'format'},
            ExpressionAttributeValues={
                ':s': 'processing',
                ':w': width,
                ':h': height,
                ':f': fmt,
                ':q': quality
            }
        )

        # Invoke resize processor Lambda asynchronously
        payload = {
            'jobId':   job_id,
            'fileKey': file_key,
            'width':   width,
            'height':  height,
            'format':  fmt,
            'quality': quality
        }
        lambda_cli.invoke(
            FunctionName=PROCESSOR_FUNC,
            InvocationType='Event',           # Async invocation
            Payload=json.dumps(payload).encode()
        )

        return response(200, {'jobId': job_id, 'status': 'processing'})

    except Exception as e:
        print(f"Error: {e}")
        return response(500, {'error': str(e)})


def response(status_code: int, body: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'POST,OPTIONS'
        },
        'body': json.dumps(body)
    }
