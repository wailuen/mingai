# Deployment & Infrastructure

## Local Development (Docker Compose)

### Services

**File**: `docker-compose.yml`

```yaml
services:
  frontend: # Next.js dev server
    port: 3022 # localhost:3022

  api-service: # FastAPI backend
    port: 8022 # localhost:8022 (exposed)
    internal: 8021 # 8021 (internal container port)

  sync-worker: # Document sync service
    port: 8025 # localhost:8025

  cosmosdb: # Azure Cosmos DB emulator
    port: 8081 # localhost:8081/_explorer
    profiles: ["full"] # Optional: docker-compose --profile full up

  redis: # Redis cache (external: enterprise_redis)
    Managed externally via enterprise_common_network
```

### Network Topology

```
┌─────────────────────────────────────────────────┐
│          Docker Compose Network                 │
│  mingai-network (bridge)                         │
├─────────────────────────────────────────────────┤
│ ┌──────────┐    ┌──────────┐    ┌───────────┐  │
│ │ frontend │    │ api-svc  │    │sync-worker│  │
│ │ :3022    │    │ :8021    │    │ :8080     │  │
│ └────┬─────┘    └────┬─────┘    └─────┬─────┘  │
│      │               │                │        │
│      └───────────────┼────────────────┘        │
│                      │                         │
│              ┌───────▼────────┐               │
│              │ cosmosdb       │               │
│              │ :8081          │               │
│              └────────────────┘               │
└─────────────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │ enterprise_common_     │
         │ network (external)    │
         ├───────────────────────┤
         │ enterprise_redis      │
         │ :6379                │
         │                       │
         │ mailhog (for dev)     │
         │ :1025                │
         └───────────────────────┘
```

### Running Locally

```bash
# Start all services
docker-compose up -d

# Specific services
docker-compose up -d api-service cosmosdb redis

# View logs
docker-compose logs -f api-service

# Stop
docker-compose down

# Clean volumes (reset database)
docker-compose down -v
```

---

## Production Deployment (Azure)

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Azure Cloud                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐       ┌──────────────────┐           │
│  │   CDN        │───┬──→│  API Gateway     │           │
│  │ (Static)     │   │   │  (Azure Gateway) │           │
│  └──────────────┘   │   └────────┬─────────┘           │
│                     │            │                      │
│                     │   ┌────────▼─────────┐            │
│                     │   │ App Service      │            │
│                     │   │ (Container)      │            │
│                     │   │ instances:       │            │
│                     │   │ - api-service    │            │
│                     │   │ - sync-worker    │            │
│                     │   └────────┬─────────┘            │
│                     │            │                      │
│  ┌──────────────┐   │   ┌────────▼──────────┐          │
│  │Static Assets │───┘   │ Azure Cache       │          │
│  │(Blob Storage)│       │ for Redis         │          │
│  └──────────────┘       └───────────────────┘          │
│                                                          │
│  ┌────────────────────────────────────────────┐        │
│  │ Database & Search                          │        │
│  ├────────────────────────────────────────────┤        │
│  │ • Cosmos DB (NoSQL)                        │        │
│  │ • Azure Search (Hybrid search)             │        │
│  │ • Azure Storage (Documents)                │        │
│  └────────────────────────────────────────────┘        │
│                                                          │
│  ┌────────────────────────────────────────────┐        │
│  │ AI & ML Services                           │        │
│  ├────────────────────────────────────────────┤        │
│  │ • Azure OpenAI (GPT models, embeddings)   │        │
│  │ • Azure AI Search (Vector indexing)       │        │
│  └────────────────────────────────────────────┘        │
│                                                          │
│  ┌────────────────────────────────────────────┐        │
│  │ Security & Compliance                      │        │
│  ├────────────────────────────────────────────┤        │
│  │ • Azure Key Vault (Secrets)                │        │
│  │ • Application Insights (Monitoring)        │        │
│  │ • Azure Entra ID (Authentication)          │        │
│  └────────────────────────────────────────────┘        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Required Azure Resources

| Resource                 | SKU                   | Purpose                   | Cost            |
| ------------------------ | --------------------- | ------------------------- | --------------- |
| **App Service**          | Standard B2 (2 cores) | Run backend containers    | $50-100/mo      |
| **Cosmos DB**            | Standard (400 RU/s)   | Database                  | $100-500/mo     |
| **Azure Search**         | Basic                 | Full-text & vector search | $150-300/mo     |
| **Azure OpenAI**         | Pay-per-token         | GPT models                | $200-1000/mo    |
| **Cache for Redis**      | Standard C1           | Sessions & caching        | $50-100/mo      |
| **Key Vault**            | Standard              | Secrets management        | $0.50/secret/mo |
| **Storage Account**      | Standard LRS          | Document storage          | $0.024/GB       |
| **Application Insights** | Standard              | Monitoring & logging      | $0.50-5/mo      |

**Total Monthly (Estimated)**: $600-2000/mo

---

## Container Deployment

### Dockerfile (api-service)

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8021/health || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8021"]
```

### docker-compose.prod-test.yml

```yaml
version: "3.8"

services:
  api-gateway:
    image: mingai:latest
    container_name: mingai_api_gateway
    ports:
      - "8000:8000"
    environment:
      ENVIRONMENT: production
      DEBUG: "false"
      COSMOSDB_ENDPOINT: "https://cosmos-prod.documents.azure.com:443/"
      AZURE_OPENAI_ENDPOINT: "https://openai-prod.openai.azure.com/"
      # ... all prod secrets from environment ...

  sync-worker:
    image: mingai-sync:latest
    container_name: mingai_sync_worker
    environment:
      ENVIRONMENT: production
      # ... sync-specific config ...
```

---

## CI/CD Pipeline (GitHub Actions)

### .github/workflows/deploy.yml

```yaml
name: Deploy to Azure

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pip install -r requirements.txt
      - run: pytest src/backend/
      - run: npm --prefix src/frontend/ ci
      - run: npm --prefix src/frontend/ run build

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Build and push image
        run: |
          docker build -t ${{ secrets.REGISTRY_LOGIN }}.azurecr.io/mingai:${{ github.sha }} .
          docker push ${{ secrets.REGISTRY_LOGIN }}.azurecr.io/mingai:${{ github.sha }}

      - name: Deploy to App Service
        uses: azure/webapps-deploy@v2
        with:
          app-name: "mingai-prod"
          images: "${{ secrets.REGISTRY_LOGIN }}.azurecr.io/mingai:${{ github.sha }}"
```

---

## Monitoring & Observability

### Application Insights

```python
from opentelemetry import trace, metrics
from opentelemetry.exporter.azure_monitor import AzureMonitorTraceExporter

# Configure tracing
trace_exporter = AzureMonitorTraceExporter(
    connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
)

# Log all requests
@app.middleware("http")
async def log_request(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000

    logger.info({
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": duration
    })

    return response
```

### Key Metrics to Monitor

```
Performance:
- API response latency (p50, p95, p99)
- LLM generation time
- Search query latency

Errors:
- Error rate (4xx, 5xx)
- LLM API failures
- Search timeouts

Business:
- User count (daily active)
- Chat queries/day
- Cost per query
- Confidence scores (distribution)

Infrastructure:
- CPU usage
- Memory usage
- Cosmos DB RU/s
- Redis memory
```

---

## Backup & Disaster Recovery

### Cosmos DB

```
Backup Strategy:
- Automatic backups every 8 hours (built-in)
- Retention: 30 days (configurable)
- Geo-redundant replication (multi-region)

Recovery RTO: ~15 minutes
Recovery RPO: <1 hour
```

### Search Indexes

```
Backup:
- Export indexes to blob storage (weekly)
- Document backups (rolling 7-day retention)

Recovery:
- Reindex from Cosmos DB documents
- Restore from backup if needed
```

### Secrets Management

```
Azure Key Vault:
- Store all API keys, connection strings
- Automatic rotation policies
- Access audit logging

Disaster Recovery:
- Key Vault with geo-replication
- Backup to secondary region
```

---

## Performance Optimization

### Frontend

```
Next.js optimization:
- Static generation (ISR) for public pages
- Code splitting for lazy loading
- Image optimization (next/image)
- CSS minification with Tailwind

CDN:
- Serve static assets from Azure CDN
- Cache: 30 days for static files, 1 hour for HTML
```

### Backend

```
Caching:
- Redis for sessions (1 hour TTL)
- Permission cache (1 hour TTL)
- Index list cache (30 minutes)
- Embedding cache (1 year)

Database:
- Connection pooling (50 connections)
- Composite indexes for common queries
- Partition pruning for large result sets

Async Operations:
- Document sync: Background task
- Analytics aggregation: Nightly batch job
- Token refresh: Background worker
```

---

## Scaling Strategy

### Horizontal Scaling

```
API Service:
- App Service plan: Premium P1v2 (2 cores)
- Auto-scale: 2-10 instances based on CPU/Memory
- Load balancer: Azure Traffic Manager

Sync Worker:
- Dedicated instance (single)
- Scheduled jobs: Daily at 2 AM UTC
```

### Vertical Scaling

```
If single instance overwhelmed:
- Upgrade App Service SKU (P2v2, P3v2)
- Increase Cosmos DB RU/s
- Increase Azure Search capacity
```

### Cost Optimization

```
Recommendations:
- Reserved Instances (1-year): 30% discount
- Spot instances for dev/test: 70% discount
- Resource groups: Separate for prod/staging
- Budget alerts: Trigger at $1500/mo
```

---

## Compliance & Security

### Network Security

```
Azure Network Security Group:
- Allow HTTPS (443) inbound
- Allow internal traffic only
- Deny all by default
- DDoS protection enabled
```

### Data Encryption

```
At rest:
- Cosmos DB: Encryption enabled (AES-256)
- Storage accounts: Encryption enabled
- Key Vault: FIPS 140-2 Level 2 certified

In transit:
- TLS 1.2+ enforced
- HTTPS for all endpoints
```

### Compliance Certifications

```
Current: None (MVP)

Roadmap:
- SOC 2 Type II: 6-12 months
- HIPAA: If needed (healthcare vertical)
- GDPR: Already compliant (EU data residency supported)
```

---

**Document Version**: 1.0
**Last Updated**: March 4, 2026
