"""
Lambda Function 4: result_handler.py
Polls job status from DynamoDB.
Triggered by: GET /result/{jobId} (API Gateway)
"""

import json
import os
import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
JOBS_TABLE = os.environ['JOBS_TABLE']


def handler(event, context):
    """
    Path: GET /result/{jobId}
    Returns job status + result URL when done.
    """
    try:
        job_id = event.get('pathParameters', {}).get('jobId')
        if not job_id:
            return response(400, {'error': 'jobId is required'})

        table = dynamodb.Table(JOBS_TABLE)
        result = table.get_item(Key={'jobId': job_id})
        item = result.get('Item')

        if not item:
            return response(404, {'error': 'Job not found'})

        status = item.get('status', 'pending')

        if status == 'done':
            return response(200, {
                'status':    'done',
                'jobId':     job_id,
                'resultUrl': item.get('resultUrl'),
                'width':     item.get('finalWidth'),
                'height':    item.get('finalHeight'),
                'format':    item.get('format'),
                'size':      item.get('outputSize')
            })

        elif status == 'error':
            return response(200, {
                'status':  'error',
                'jobId':   job_id,
                'message': item.get('errorMsg', 'Unknown error')
            })

        else:
            return response(200, {
                'status': status,
                'jobId':  job_id
            })

    except ClientError as e:
        print(f"DynamoDB error: {e}")
        return response(500, {'error': 'Database error'})
    except Exception as e:
        print(f"Error: {e}")
        return response(500, {'error': 'Internal server error'})


def response(status_code: int, body: dict) -> dict:
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'GET,OPTIONS'
        },
        'body': json.dumps(body)
    }
