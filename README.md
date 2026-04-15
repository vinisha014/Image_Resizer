# PixelForge — AWS Setup Guide

Complete step-by-step setup for the image resizer application.

---

## Architecture Overview

```
Browser
  │
  ├─ POST /presign ──► Lambda: presign_handler   ──► S3 (presigned PUT URL)
  │                          └──► DynamoDB (create job)
  │
  ├─ PUT <presigned URL> ──────────────────────────► S3: pixelforge-uploads
  │
  ├─ POST /resize ──► Lambda: resize_handler
  │                         └──► Lambda: resize_processor (async invoke)
  │                                    ├──► S3: get original image
  │                                    ├──► Pillow: resize
  │                                    ├──► S3: put resized image
  │                                    └──► DynamoDB: update job = done
  │
  └─ GET /result/{jobId} ──► Lambda: result_handler ──► DynamoDB: get job
```

---

## Prerequisites

- AWS CLI installed and configured (`aws configure`)
- Python 3.11+ (for local testing)
- AWS account with permissions to create Lambda, S3, DynamoDB, API Gateway, IAM

---

## Step 1 — Create S3 Buckets

```bash
# Upload bucket (incoming originals)
aws s3api create-bucket \
  --bucket pixelforge-uploads \
  --region us-east-1

# Output bucket (resized images)
aws s3api create-bucket \
  --bucket pixelforge-output \
  --region us-east-1

# Block all public access on both buckets
aws s3api put-public-access-block \
  --bucket pixelforge-uploads \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

aws s3api put-public-access-block \
  --bucket pixelforge-output \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Apply CORS to upload bucket (required for direct browser upload)
aws s3api put-bucket-cors \
  --bucket pixelforge-uploads \
  --cors-configuration file://infrastructure/s3-cors.json

# Optional: auto-delete originals after 7 days
aws s3api put-bucket-lifecycle-configuration \
  --bucket pixelforge-uploads \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "delete-originals",
      "Status": "Enabled",
      "Expiration": {"Days": 7},
      "Filter": {"Prefix": "uploads/"}
    }]
  }'
```

---

## Step 2 — Create DynamoDB Table

```bash
aws dynamodb create-table \
  --table-name pixelforge-jobs \
  --attribute-definitions AttributeName=jobId,AttributeType=S \
  --key-schema AttributeName=jobId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --time-to-live-specification Enabled=true,AttributeName=ttl \
  --region us-east-1
```

---

## Step 3 — Create IAM Role for Lambda

```bash
# Create the trust policy file
cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

# Create the role
aws iam create-role \
  --role-name pixelforge-lambda-role \
  --assume-role-policy-document file:///tmp/trust-policy.json

# Attach permissions
aws iam put-role-policy \
  --role-name pixelforge-lambda-role \
  --policy-name pixelforge-permissions \
  --policy-document file://infrastructure/lambda-policy.json
```

---

## Step 4 — Add Pillow Lambda Layer

Pillow is not included in the Lambda runtime. Use the public Keith's Layer:

```bash
# For Python 3.11 in us-east-1:
LAYER_ARN="arn:aws:lambda:us-east-1:770693421928:layer:Klayers-p311-Pillow:9"

# List available versions:
# https://github.com/keithrozario/Klayers
```

Or build your own:
```bash
pip install Pillow -t python/lib/python3.11/site-packages/
zip -r pillow-layer.zip python/
aws lambda publish-layer-version \
  --layer-name pillow-layer \
  --zip-file fileb://pillow-layer.zip \
  --compatible-runtimes python3.11
```

---

## Step 5 — Package & Deploy Lambda Functions

### Package each function:

```bash
cd lambda/

# presign_handler
zip presign.zip presign_handler.py
aws lambda create-function \
  --function-name pixelforge-presign \
  --runtime python3.11 \
  --handler presign_handler.handler \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/pixelforge-lambda-role \
  --zip-file fileb://presign.zip \
  --timeout 10 \
  --memory-size 128 \
  --environment Variables="{
    UPLOAD_BUCKET=pixelforge-uploads,
    JOBS_TABLE=pixelforge-jobs
  }"

# resize_handler
zip resize.zip resize_handler.py
aws lambda create-function \
  --function-name pixelforge-resize \
  --runtime python3.11 \
  --handler resize_handler.handler \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/pixelforge-lambda-role \
  --zip-file fileb://resize.zip \
  --timeout 10 \
  --memory-size 128 \
  --environment Variables="{
    JOBS_TABLE=pixelforge-jobs,
    PROCESSOR_FUNCTION_NAME=pixelforge-resize-processor
  }"

# resize_processor (needs Pillow layer + more memory/timeout)
zip processor.zip resize_processor.py
aws lambda create-function \
  --function-name pixelforge-resize-processor \
  --runtime python3.11 \
  --handler resize_processor.handler \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/pixelforge-lambda-role \
  --zip-file fileb://processor.zip \
  --timeout 60 \
  --memory-size 512 \
  --layers $LAYER_ARN \
  --environment Variables="{
    UPLOAD_BUCKET=pixelforge-uploads,
    OUTPUT_BUCKET=pixelforge-output,
    JOBS_TABLE=pixelforge-jobs,
    OUTPUT_PREFIX=resized
  }"

# result_handler
zip result.zip result_handler.py
aws lambda create-function \
  --function-name pixelforge-result \
  --runtime python3.11 \
  --handler result_handler.handler \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/pixelforge-lambda-role \
  --zip-file fileb://result.zip \
  --timeout 10 \
  --memory-size 128 \
  --environment Variables="{
    JOBS_TABLE=pixelforge-jobs
  }"
```

### Update existing functions:
```bash
aws lambda update-function-code \
  --function-name pixelforge-presign \
  --zip-file fileb://presign.zip
```

---

## Step 6 — Create API Gateway (HTTP API)

```bash
# Create HTTP API
aws apigatewayv2 create-api \
  --name pixelforge-api \
  --protocol-type HTTP \
  --cors-configuration \
    AllowOrigins='["*"]',AllowMethods='["GET","POST","OPTIONS"]',AllowHeaders='["content-type"]'
```

Then in AWS Console (easier):
1. Go to **API Gateway → Create API → HTTP API**
2. Add integrations for each Lambda:

| Method | Path             | Lambda Function             |
|--------|------------------|-----------------------------|
| POST   | /presign         | pixelforge-presign          |
| POST   | /resize          | pixelforge-resize           |
| GET    | /result/{jobId}  | pixelforge-result           |

3. Deploy to a stage (e.g., `prod`)
4. Copy the **Invoke URL** — paste it into `frontend/index.html` as `API_BASE`

---

## Step 7 — Deploy Frontend

Option A — S3 Static Website:
```bash
aws s3 sync frontend/ s3://your-frontend-bucket/ --delete
aws s3 website s3://your-frontend-bucket/ \
  --index-document index.html
```

Option B — CloudFront + S3 (recommended for production)

Option C — Just open `index.html` locally for testing

---

## Step 8 — Test End-to-End

```bash
# Set your API URL
API="https://xxxx.execute-api.us-east-1.amazonaws.com"

# 1. Get presigned URL
curl -X POST $API/presign \
  -H "Content-Type: application/json" \
  -d '{"filename":"test.jpg","contentType":"image/jpeg"}'

# 2. Upload image (use the uploadUrl from step 1)
curl -X PUT "<uploadUrl>" \
  -H "Content-Type: image/jpeg" \
  --data-binary @test.jpg

# 3. Trigger resize
curl -X POST $API/resize \
  -H "Content-Type: application/json" \
  -d '{"fileKey":"<fileKey>","jobId":"<jobId>","width":400,"height":300,"format":"jpeg","quality":80}'

# 4. Poll result
curl $API/result/<jobId>
```

---

## Environment Variables Summary

| Function              | Variable                | Value                          |
|-----------------------|-------------------------|--------------------------------|
| presign_handler       | UPLOAD_BUCKET           | pixelforge-uploads             |
| presign_handler       | JOBS_TABLE              | pixelforge-jobs                |
| resize_handler        | JOBS_TABLE              | pixelforge-jobs                |
| resize_handler        | PROCESSOR_FUNCTION_NAME | pixelforge-resize-processor    |
| resize_processor      | UPLOAD_BUCKET           | pixelforge-uploads             |
| resize_processor      | OUTPUT_BUCKET           | pixelforge-output              |
| resize_processor      | JOBS_TABLE              | pixelforge-jobs                |
| resize_processor      | OUTPUT_PREFIX           | resized                        |
| result_handler        | JOBS_TABLE              | pixelforge-jobs                |

---

## Costs (estimates for low traffic)

| Service      | Cost                                  |
|--------------|---------------------------------------|
| Lambda       | Free tier: 1M requests/month free     |
| S3           | ~$0.023/GB/month storage              |
| DynamoDB     | Free tier: 25GB + 25 RCU/WCU free    |
| API Gateway  | Free tier: 1M HTTP API calls/month    |

**Most small-scale usage will stay within the AWS free tier.**

---

## Production Checklist

- [ ] Replace `AllowedOrigins: ["*"]` with your actual domain in CORS + IAM
- [ ] Enable S3 versioning on output bucket
- [ ] Add CloudFront in front of S3 for faster delivery
- [ ] Set up CloudWatch alarms for Lambda errors
- [ ] Add API Gateway throttling/rate limiting
- [ ] Use AWS Secrets Manager for any sensitive config
- [ ] Enable S3 access logging
- [ ] Consider SQS queue instead of direct Lambda-to-Lambda for higher volume
