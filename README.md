
# 🎯 Project Summary: Image Resizer Deployment (Docker + AWS)

## 🧠 1. Core Idea

This project demonstrates how a **static web application** can be:

* Containerized using Docker
* Stored in AWS ECR
* Deployed using ECS Fargate
* Exposed via an Application Load Balancer

---

# ⚙️ 2. How the System Works (Flow)

## 🔄 End-to-End Flow

```text
User → Load Balancer → ECS Fargate → Docker Container → Nginx → Static Website
```

---

## 🔍 Step-by-step explanation

### 🔹 Step 1: Application Layer

* Built a simple **HTML/CSS/JS app**
* No backend, no Node.js
* Pure static frontend

👉 Important decision:

> No npm needed because there is no build step

---

### 🔹 Step 2: Containerization (Docker)

* Created a Docker image using Nginx:

```dockerfile
FROM nginx:alpine
COPY . /usr/share/nginx/html
```

👉 What happens:

* Nginx serves the static files
* App runs inside a container

---

### 🔹 Step 3: Local Testing

```bash
docker build -t img-resizer .
docker run -d -p 8080:80 img-resizer
```

👉 Verified app works locally before cloud deployment

---

### 🔹 Step 4: Image Storage (AWS ECR)

* Created an ECR repository
* Logged in using AWS CLI
* Tagged and pushed image

👉 Purpose:

> Store Docker image in cloud for deployment

---

### 🔹 Step 5: Compute Layer (ECS Fargate)

* Created ECS cluster
* Defined task (CPU, memory, container image)
* Ran container using **Fargate (serverless)**

👉 Key point:

> No need to manage servers

---

### 🔹 Step 6: Networking (ALB)

* Created Application Load Balancer
* Connected it to ECS service

👉 What it does:

* Routes traffic to containers
* Makes app publicly accessible

---

### 🔹 Step 7: Final Output

* Accessed app using ALB DNS:

```text
http://<alb-dns-name>
```

---

# 🔥 3. Key Challenges & Fixes

### ❌ npm errors

* Cause: Not a Node app
* Fix: Used Nginx instead

---

### ❌ ECR login issues

* Cause: Region mismatch
* Fix: Matched CLI + ECR region

---

### ❌ Docker port conflict

* Cause: Port already in use
* Fix: Changed/killed process

---

# 💡 4. Key Learnings

* Difference between **static vs build-based apps**
* Docker containerization
* AWS ECR + ECS workflow
* Importance of region consistency in AWS
* Debugging real-world deployment issues

---
