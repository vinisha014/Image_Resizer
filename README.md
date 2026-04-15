# ImgToPDF — Complete AWS Deployment Guide
# React → Docker → ECR → ECS Fargate → ALB

Prerequisites — Install These First
Tool Install Command / LinkNode.js 18+ - https://nodejs.org
Docker - https://docs.docker.com/get-docker/AWS CLI v2https://aws.amazon.com/cli/Githttps://git-scm.com
Configure AWS CLI:
bashaws configure
Enter: AWS Access Key ID
Enter: AWS Secret Access Key
Enter: Default region (e.g., us-east-1)
Enter: Default output format (json)

# Verify it works:
aws sts get-caller-identity

════════════════════════════════════════════════════
STEP 1 — Application Development (React)
════════════════════════════════════════════════════
The React app is already built in this folder. Let's test it locally first.
bashcd img-to-pdf/

# Install dependencies
npm install

# Run locally at http://localhost:3000
npm start
Test the app:

Upload 1-3 images
Adjust page size, orientation, margin
Click "Convert to PDF"
Verify the PDF downloads and looks correct

Build the production bundle:
bashnpm run build
# Creates /build folder — optimized, minified React app

════════════════════════════════════════════════════
STEP 2 — Dockerization
════════════════════════════════════════════════════
2.1 — Understand the Dockerfile
Our Dockerfile uses a multi-stage build:

Stage 1 (builder): Uses Node 18 Alpine to run npm run build
Stage 2 (runner): Uses Nginx Alpine to serve the built files

This results in a tiny final image (~25MB) vs a full Node image (~400MB).
2.2 — Build the Docker image locally
bash# Make sure you're in the project root (where Dockerfile is)
cd img-to-pdf/

# Build the image and tag it
docker build -t img-to-pdf:latest .

# Verify the image was created
docker images | grep img-to-pdf
Expected output:
img-to-pdf   latest   abc123def456   30 seconds ago   25.4MB
2.3 — Test the Docker container locally
bash# Run the container, mapping port 80 (nginx) to 3000 on your machine
docker run -d -p 3000:80 --name img-pdf-test img-to-pdf:latest

# Check it's running
docker ps

# Open http://localhost:3000 in your browser and test the app

# View container logs
docker logs img-pdf-test

# Test health endpoint
curl http://localhost:3000/health
# Should respond: healthy

# Stop and remove the test container
docker stop img-pdf-test && docker rm img-pdf-test

════════════════════════════════════════════════════
STEP 3 — Push Docker Image to Amazon ECR
════════════════════════════════════════════════════
3.1 — Create an ECR Repository
bash# Set your region
export AWS_REGION=us-east-1
export APP_NAME=img-to-pdf

# Create the ECR repository
aws ecr create-repository \
  --repository-name $APP_NAME \
  --region $AWS_REGION \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability MUTABLE

# Save the repository URI (you'll need this often!)
export ECR_URI=$(aws ecr describe-repositories \
  --repository-names $APP_NAME \
  --query 'repositories[0].repositoryUri' \
  --output text)

echo "Your ECR URI: $ECR_URI"
# Example: 123456789012.dkr.ecr.us-east-1.amazonaws.com/img-to-pdf
3.2 — Authenticate Docker with ECR
bash# Get an authentication token and log Docker in to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $(aws sts get-caller-identity --query Account --output text).dkr.ecr.$AWS_REGION.amazonaws.com

# You should see: Login Succeeded
3.3 — Tag and Push the Image
bash# Tag your local image with the ECR URI
docker tag img-to-pdf:latest $ECR_URI:latest

# Also tag with a version number (good practice)
docker tag img-to-pdf:latest $ECR_URI:v1.0.0

# Push both tags to ECR
docker push $ECR_URI:latest
docker push $ECR_URI:v1.0.0

# Verify the image is in ECR
aws ecr list-images --repository-name $APP_NAME --region $AWS_REGION
Expected output:
json{
    "imageIds": [
        {"imageDigest": "sha256:...", "imageTag": "latest"},
        {"imageDigest": "sha256:...", "imageTag": "v1.0.0"}
    ]
}

════════════════════════════════════════════════════
STEP 4 — ECS Task Definition
════════════════════════════════════════════════════
4.1 — Create IAM Role for ECS Task Execution
bash# Create trust policy for ECS
cat > /tmp/ecs-trust.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

# Create the execution role
aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file:///tmp/ecs-trust.json

# Attach the AWS managed policy for pulling ECR images and writing logs
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Get your account ID
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account ID: $ACCOUNT_ID"
4.2 — Create CloudWatch Log Group
bashaws logs create-log-group \
  --log-group-name /ecs/img-to-pdf \
  --region $AWS_REGION
4.3 — Register the Task Definition
bash# Create the task definition JSON
cat > /tmp/task-def.json << EOF
{
  "family": "img-to-pdf-task",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::${ACCOUNT_ID}:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "img-to-pdf",
      "image": "${ECR_URI}:latest",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 80,
          "protocol": "tcp"
        }
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "wget -q --tries=1 --spider http://localhost/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 10
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/img-to-pdf",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
EOF

# Register the task definition
aws ecs register-task-definition \
  --cli-input-json file:///tmp/task-def.json \
  --region $AWS_REGION

# Verify registration
aws ecs describe-task-definition \
  --task-definition img-to-pdf-task \
  --query 'taskDefinition.taskDefinitionArn'

════════════════════════════════════════════════════
STEP 5 — ECS Cluster + Fargate Deployment
════════════════════════════════════════════════════
5.1 — Create ECS Cluster
bashaws ecs create-cluster \
  --cluster-name img-to-pdf-cluster \
  --capacity-providers FARGATE FARGATE_SPOT \
  --region $AWS_REGION

# Verify cluster
aws ecs describe-clusters \
  --clusters img-to-pdf-cluster \
  --query 'clusters[0].status'
# Should output: "ACTIVE"
5.2 — Find Your VPC and Subnets
bash# Get the default VPC ID
export VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=is-default,Values=true" \
  --query 'Vpcs[0].VpcId' \
  --output text)
echo "VPC ID: $VPC_ID"

# Get subnet IDs (get at least 2 for high availability)
export SUBNET_IDS=$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' \
  --output text | tr '\t' ',')
echo "Subnets: $SUBNET_IDS"
5.3 — Create Security Groups
bash# Security Group for the ALB (public internet → ALB)
export ALB_SG=$(aws ec2 create-security-group \
  --group-name img-pdf-alb-sg \
  --description "Allow HTTP/HTTPS from internet to ALB" \
  --vpc-id $VPC_ID \
  --query 'GroupId' \
  --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $ALB_SG \
  --protocol tcp --port 80 --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id $ALB_SG \
  --protocol tcp --port 443 --cidr 0.0.0.0/0

echo "ALB Security Group: $ALB_SG"

# Security Group for ECS Tasks (ALB → ECS only)
export ECS_SG=$(aws ec2 create-security-group \
  --group-name img-pdf-ecs-sg \
  --description "Allow traffic from ALB to ECS tasks" \
  --vpc-id $VPC_ID \
  --query 'GroupId' \
  --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $ECS_SG \
  --protocol tcp --port 80 \
  --source-group $ALB_SG

echo "ECS Security Group: $ECS_SG"

════════════════════════════════════════════════════
STEP 6 — Application Load Balancer (ALB)
════════════════════════════════════════════════════
6.1 — Create the ALB
bash# Convert comma-separated subnets to space-separated for ALB
SUBNETS_SPACE=$(echo $SUBNET_IDS | tr ',' ' ')

export ALB_ARN=$(aws elbv2 create-load-balancer \
  --name img-to-pdf-alb \
  --subnets $SUBNETS_SPACE \
  --security-groups $ALB_SG \
  --scheme internet-facing \
  --type application \
  --ip-address-type ipv4 \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text)

echo "ALB ARN: $ALB_ARN"

# Get the ALB DNS name (this is your public URL!)
export ALB_DNS=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' \
  --output text)

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Your App URL: http://$ALB_DNS  ║"
echo "╚══════════════════════════════════════════════╝"
6.2 — Create Target Group
bashexport TG_ARN=$(aws elbv2 create-target-group \
  --name img-pdf-targets \
  --protocol HTTP \
  --port 80 \
  --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --query 'TargetGroups[0].TargetGroupArn' \
  --output text)

echo "Target Group ARN: $TG_ARN"
6.3 — Create ALB Listener
bashaws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN

6.4 — Create ECS Service (Fargate)
bash# Convert subnet IDs for ECS service JSON
SUBNETS_JSON=$(echo $SUBNET_IDS | tr ',' '\n' | jq -R . | jq -s .)

cat > /tmp/ecs-service.json << EOF
{
  "cluster": "img-to-pdf-cluster",
  "serviceName": "img-to-pdf-service",
  "taskDefinition": "img-to-pdf-task",
  "desiredCount": 2,
  "launchType": "FARGATE",
  "networkConfiguration": {
    "awsvpcConfiguration": {
      "subnets": $(echo $SUBNET_IDS | python3 -c "import sys,json; s=sys.stdin.read().strip(); print(json.dumps(s.split(',')))"),
      "securityGroups": ["$ECS_SG"],
      "assignPublicIp": "ENABLED"
    }
  },
  "loadBalancers": [
    {
      "targetGroupArn": "$TG_ARN",
      "containerName": "img-to-pdf",
      "containerPort": 80
    }
  ],
  "healthCheckGracePeriodSeconds": 60,
  "deploymentConfiguration": {
    "maximumPercent": 200,
    "minimumHealthyPercent": 100,
    "deploymentCircuitBreaker": {
      "enable": true,
      "rollback": true
    }
  }
}
EOF

aws ecs create-service \
  --cli-input-json file:///tmp/ecs-service.json \
  --region $AWS_REGION

════════════════════════════════════════════════════
STEP 7 — Verify Deployment
════════════════════════════════════════════════════
7.1 — Watch Tasks Start Up
bash# Watch ECS service status (runs every 5 seconds)
watch -n 5 "aws ecs describe-services \
  --cluster img-to-pdf-cluster \
  --services img-to-pdf-service \
  --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount,Pending:pendingCount}' \
  --output table"

# Wait for runningCount = 2 (takes ~2-3 minutes)
7.2 — Check Target Group Health
bashaws elbv2 describe-target-health \
  --target-group-arn $TG_ARN \
  --query 'TargetHealthDescriptions[*].{Target:Target.Id,Health:TargetHealth.State}'
# Both targets should show "healthy"
7.3 — Test the App
bashecho "App URL: http://$ALB_DNS"

# Test health endpoint
curl http://$ALB_DNS/health
# Expected: healthy

# Open in browser
open http://$ALB_DNS    # macOS
xdg-open http://$ALB_DNS  # Linux
7.4 — View Logs
bash# List log streams
aws logs describe-log-streams \
  --log-group-name /ecs/img-to-pdf \
  --order-by LastEventTime \
  --descending \
  --max-items 3

# Tail live logs
aws logs tail /ecs/img-to-pdf --follow

════════════════════════════════════════════════════
STEP 8 — Update Deployment (Rolling Update)
════════════════════════════════════════════════════
When you make code changes:
bash# 1. Rebuild Docker image
docker build -t img-to-pdf:latest .
docker tag img-to-pdf:latest $ECR_URI:v1.1.0
docker tag img-to-pdf:latest $ECR_URI:latest

# 2. Push to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin \
  $(echo $ECR_URI | cut -d/ -f1)

docker push $ECR_URI:v1.1.0
docker push $ECR_URI:latest

# 3. Register new task definition revision
#    (update the image tag in task-def.json if needed)
aws ecs register-task-definition --cli-input-json file:///tmp/task-def.json

# 4. Update the service (triggers rolling deployment)
aws ecs update-service \
  --cluster img-to-pdf-cluster \
  --service img-to-pdf-service \
  --task-definition img-to-pdf-task \
  --force-new-deployment \
  --region $AWS_REGION

# Watch the rolling update
aws ecs describe-services \
  --cluster img-to-pdf-cluster \
  --services img-to-pdf-service \
  --query 'services[0].deployments'

════════════════════════════════════════════════════
TROUBLESHOOTING
════════════════════════════════════════════════════
Tasks Not Starting
bash# Check stopped task reasons
aws ecs list-tasks \
  --cluster img-to-pdf-cluster \
  --desired-status STOPPED \
  --query 'taskArns[0]'

aws ecs describe-tasks \
  --cluster img-to-pdf-cluster \
  --tasks <TASK_ARN> \
  --query 'tasks[0].stoppedReason'
Health Checks Failing
bash# Ensure nginx is running and /health returns 200
docker run --rm -p 3000:80 img-to-pdf:latest &
curl http://localhost:3000/health
# Must return: healthy
ECR Pull Errors
bash# Ensure task execution role has ECR permissions
aws iam get-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-name AmazonECSTaskExecutionRolePolicy
ALB 502 Bad Gateway

ECS tasks may not be running — check runningCount
Security group may block ALB → ECS on port 80 — re-check Step 5.3
Target health may show unhealthy — check container logs


════════════════════════════════════════════════════
ARCHITECTURE SUMMARY
════════════════════════════════════════════════════
Internet
   │
   ▼
┌─────────────────────────────────────────┐
│  Application Load Balancer (ALB)        │
│  img-to-pdf-alb                         │
│  Port 80 → forwards to Target Group     │
└─────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────┐
│  ECS Service — img-to-pdf-service       │
│  Launch Type: FARGATE (serverless)      │
│  Desired Count: 2 tasks                 │
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │  Task 1      │  │  Task 2      │    │
│  │  CPU: 256    │  │  CPU: 256    │    │
│  │  RAM: 512MB  │  │  RAM: 512MB  │    │
│  │  nginx:80    │  │  nginx:80    │    │
│  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────┐
│  Amazon ECR                             │
│  123456789012.dkr.ecr.region.../        │
│  img-to-pdf:latest                      │
└─────────────────────────────────────────┘

════════════════════════════════════════════════════
CLEANUP (Avoid AWS Charges)
════════════════════════════════════════════════════
bash# 1. Scale down ECS service to 0 tasks
aws ecs update-service \
  --cluster img-to-pdf-cluster \
  --service img-to-pdf-service \
  --desired-count 0

# 2. Delete ECS service
aws ecs delete-service \
  --cluster img-to-pdf-cluster \
  --service img-to-pdf-service \
  --force

# 3. Delete ECS cluster
aws ecs delete-cluster --cluster img-to-pdf-cluster

# 4. Delete ALB and Target Group
aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN
aws elbv2 delete-target-group --target-group-arn $TG_ARN

# 5. Delete ECR repository (and all images)
aws ecr delete-repository --repository-name img-to-pdf --force

# 6. Delete Log Group
aws logs delete-log-group --log-group-name /ecs/img-to-pdf

# 7. Delete Security Groups
aws ec2 delete-security-group --group-id $ECS_SG
aws ec2 delete-security-group --group-id $ALB_SG
