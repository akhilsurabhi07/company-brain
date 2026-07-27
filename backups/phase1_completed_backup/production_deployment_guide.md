# Company Brain — Production Deployment Guide & KEDA Auto-Scaling Specification

This document summarizes all steps required to transition **Company Brain** from Development to Live Production Deployment on AWS / Kubernetes.

---

## 1. Third-Party Developer OAuth Credentials
Register production Developer Applications on external provider portals:

| Provider | Portal URL | Scope & Environment Variables |
| :--- | :--- | :--- |
| **Slack** | `api.slack.com/apps` | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` (`channels:history`, `files:read`) |
| **Google Drive** | `console.cloud.google.com` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (`drive.readonly`) |
| **GitHub** | `github.com/settings/developers` | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` (`repo`, `read:org`) |
| **Jira** | `developer.atlassian.com` | `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET` (`read:jira-work`) |
| **WhatsApp** | `developers.facebook.com` | `WHATSAPP_APP_ID`, `WHATSAPP_SECRET` (`whatsapp_business_messaging`) |
| **Microsoft Teams** | `portal.azure.com` (Entra ID) | `TEAMS_CLIENT_ID`, `TEAMS_CLIENT_SECRET` (`Chat.Read`, `Files.Read.All`) |

---

## 2. Production AWS Infrastructure Hardening

### AWS RDS PostgreSQL Instance
* Multi-AZ high availability deployment.
* Forced SSL connection mode (`sslmode=require`).
* DB Password stored in **AWS Secrets Manager**.

### AWS S3 Raw Vault Bucket (`company-brain-raw-data-vault`)
* Enable S3 Server-Side Encryption (KMS / AES-256).
* Enable S3 Bucket Versioning.
* S3 Lifecycle Policy: Auto-archive raw `.json.zst` payloads older than 365 days to **S3 Glacier** (cuts storage costs by 90%).

### AWS ElastiCache (Redis)
* Provision a managed Redis cluster for Celery message broker & event queue.

---

## 3. Containerized Deployment & KEDA Auto-Scaling

### Docker Containerization
* **Web Service:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`
* **Worker Service:** `celery -A app.workers.celery_app worker --loglevel=info`

### KEDA Auto-Scaling Specification (`keda-scaledobject.yaml`)
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: company-brain-worker-scaler
  namespace: company-brain
spec:
  scaleTargetRef:
    name: celery-worker-deployment
  minReplicaCount: 2      # Base idle workers (saves AWS cost)
  maxReplicaCount: 50     # Max workers during high traffic spikes
  cooldownPeriod: 300     # Wait 5 mins before scaling down
  triggers:
  - type: redis
    metadata:
      queueName: celery
      queueLength: "10"   # Add 1 worker container per 10 pending jobs in Redis
```

---

## 4. Production Webhook Callback Endpoints

Set official public HTTPS webhook callback URLs in provider portals:
* `https://app.yourcompany.com/api/v1/webhooks/slack`
* `https://app.yourcompany.com/api/v1/webhooks/github`
* `https://app.yourcompany.com/api/v1/webhooks/whatsapp`
