# Cloud-Agnostic Deployment Strategy

**Date**: March 4, 2026
**Status**: Architecture Design
**Scope**: Abstracting Azure-specific services for multi-cloud deployment

---

## Overview

The current system is deeply coupled to Azure services: Cosmos DB, Azure AI Search, Azure Blob Storage, Azure OpenAI, Azure AD (Entra), Azure Monitor, Azure Key Vault, and Azure Document Intelligence. A multi-tenant SaaS platform serving customers across regions must support deployment to AWS (primary), Azure, GCP, and Alibaba Cloud. This document maps every Azure dependency to its cloud equivalents and designs the abstraction layer.

---

## Cloud Selection via Config

A single environment variable drives the entire cloud provider selection:

```
CLOUD_PROVIDER=aws|azure|gcp|self-hosted
```

This env var determines which provider implementations are loaded at application startup. **All application code is cloud-provider-agnostic** -- the abstraction layer translates to provider-specific APIs. No cloud SDK is imported outside the provider adapter modules.

**How it works**:

1. Application reads `CLOUD_PROVIDER` from `.env` at startup
2. The provider factory (`create_infrastructure()`) instantiates the correct adapter for each service (database, search, storage, secrets, telemetry)
3. Application code interacts only with abstract interfaces (`DocumentStore`, `SearchEngine`, `ObjectStore`, etc.)
4. Cloud-specific SDKs are imported lazily inside adapter implementations only

**Example `.env` for AWS deployment (Phase 1)**:

```env
CLOUD_PROVIDER=aws
DOCUMENT_STORE_ENDPOINT=us-east-1
SEARCH_ENGINE_ENDPOINT=https://search-mingai-xxx.us-east-1.es.amazonaws.com
OBJECT_STORE_CONNECTION=us-east-1
SECRET_STORE_URL=arn:aws:secretsmanager:us-east-1:123456789:secret:mingai
TELEMETRY_CONNECTION=us-east-1
```

---

## Phase 1: AWS Launch

Phase 1 deploys exclusively on AWS. The abstraction layer is built from day 1, but only AWS adapters are implemented and tested. Azure and GCP adapters come in Phase 5.

### Why AWS First

- **Broadest enterprise reach**: AWS has the largest enterprise market share
- **Strongest managed services**: Aurora PostgreSQL, OpenSearch, S3, ElastiCache are mature and well-documented
- **EKS ecosystem**: Rich Kubernetes tooling and marketplace
- **Cost optimization**: Spot instances, Savings Plans, and Reserved Instances for production workloads

### AWS Service Stack (Phase 1)

| Service Category   | AWS Service                                              | Notes                                           |
| ------------------ | -------------------------------------------------------- | ----------------------------------------------- |
| **Database**       | Aurora PostgreSQL / RDS PostgreSQL                       | Managed PostgreSQL with multi-AZ failover       |
| **Search**         | AWS OpenSearch Service                                   | Managed OpenSearch with vector search support   |
| **Object Storage** | Amazon S3                                                | Standard object storage with lifecycle policies |
| **Cache**          | Amazon ElastiCache (Redis)                               | Managed Redis for session and query caching     |
| **LLM**            | AWS Bedrock (optional) + provider abstraction            | See doc 04 for LLM provider management          |
| **Secrets**        | AWS Secrets Manager                                      | Automatic rotation, IAM-based access control    |
| **Monitoring**     | Amazon CloudWatch / AWS X-Ray                            | Logs, metrics, and distributed tracing          |
| **Identity**       | Auth0 / Okta broker (Entra ID as supported SSO provider) | See doc 03 for auth/SSO strategy                |
| **Kubernetes**     | Amazon EKS                                               | Managed Kubernetes with Fargate option          |
| **CDN/Ingress**    | AWS ALB + CloudFront                                     | Load balancing and edge caching                 |

### Phase 1 Adapter Coverage

| Abstraction Layer       | AWS Adapter                    | Status  |
| ----------------------- | ------------------------------ | ------- |
| `DocumentStore`         | `PostgreSQLStore` (via Aurora) | Phase 1 |
| `SearchEngine`          | `OpenSearchEngine`             | Phase 1 |
| `ObjectStore`           | `S3Store`                      | Phase 1 |
| `SecretStore`           | `AWSSecretsManagerStore`       | Phase 1 |
| `TelemetryExporter`     | `CloudWatchExporter`           | Phase 1 |
| `DocumentStore` (Azure) | `CosmosDBStore`                | Phase 5 |
| `SearchEngine` (Azure)  | `AzureAISearchEngine`          | Phase 5 |
| `ObjectStore` (Azure)   | `AzureBlobStore`               | Phase 5 |
| `DocumentStore` (GCP)   | `FirestoreStore`               | Phase 5 |

---

## Current Azure Dependencies

### Evidence from Source Code

Every Azure service dependency traced from configuration and service files:

**Database** -- Cosmos DB (config.py:30-37):

```python
# config.py:30-33
cosmosdb_endpoint: str = Field(default="")
cosmosdb_key: str = Field(default="")
cosmosdb_database: str = Field(default="mingai-dev")
```

**Search** -- Azure AI Search (config.py:178-187):

```python
# config.py:178-183
azure_search_endpoint: str = Field(default="")
azure_search_admin_key: str = Field(default="")
azure_search_query_key: str = Field(default="")
azure_search_api_version: str = Field(default="2024-07-01")
```

**Object Storage** -- Azure Blob Storage (config.py:212-217):

```python
# config.py:212-213
azure_storage_connection_string: str = Field(default="")
retention_archive_storage_container: str = Field(default="conversation-archives")

# config.py:216-217
azure_blob_storage_connection_string: str = Field(default="")
azure_blob_container_name: str = Field(default="mingai-docs")
```

**LLM** -- Azure OpenAI (config.py:82-176, openai_client.py:17):

```python
# openai_client.py:17
from openai import AsyncAzureOpenAI
```

**Identity** -- Azure AD / Entra ID (config.py:57-61):

```python
# config.py:57-61
azure_ad_tenant_id: str = Field(default="")
azure_ad_client_id: str = Field(default="")
azure_ad_client_secret: str = Field(default="")
```

**Monitoring** -- Azure Monitor (config.py:350):

```python
# config.py:350
azure_monitor_connection_string: str = Field(default="", env="AZURE_MONITOR_CONNECTION_STRING")
```

**Secret Management** -- Azure Key Vault (config.py:239):

```python
# config.py:239
azure_keyvault_url: str = Field(default="", env="AZURE_KEYVAULT_URL")
```

**Document Intelligence** -- Azure Document Intelligence (config.py:219-222):

```python
# config.py:219-222
azure_document_intelligence_endpoint: str = Field(default="")
azure_document_intelligence_key: str = Field(default="")
```

**Speech** -- Azure Speech Services (config.py:246-247):

```python
# config.py:246-247
azure_speech_key: str = Field(default="", env="AZURE_SPEECH_KEY")
azure_speech_region: str = Field(default="", env="AZURE_SPEECH_REGION")
```

**MS Graph** -- Microsoft Graph API (services/msgraph.py):

- Used for profile enrichment (department, jobTitle)
- Used for SharePoint sync (sharepoint_client.py)
- Used by Azure AD MCP for calendar/email OBO access

---

## Cloud Service Equivalence Matrix

AWS is listed first as the primary deployment platform (Phase 1). Azure, GCP, and AliCloud adapters follow in later phases.

| Service Category          | AWS (Primary -- Phase 1)           | Azure                  | GCP                               | AliCloud                           | Abstraction Layer                                 |
| ------------------------- | ---------------------------------- | ---------------------- | --------------------------------- | ---------------------------------- | ------------------------------------------------- |
| **Database**              | Aurora PostgreSQL / RDS PostgreSQL | Cosmos DB              | Firestore / Cloud SQL             | Table Store / ApsaraDB for MongoDB | `DocumentStore`                                   |
| **Search**                | AWS OpenSearch Service             | Azure AI Search        | Vertex AI Search                  | OpenSearch on ECS                  | `SearchEngine`                                    |
| **Object Storage**        | Amazon S3                          | Azure Blob Storage     | Cloud Storage (GCS)               | OSS (Object Storage Service)       | `ObjectStore`                                     |
| **LLM**                   | AWS Bedrock (optional)             | Azure OpenAI           | Vertex AI                         | DashScope/Model Studio             | `LLMProvider` (see 04-llm-provider-management.md) |
| **Identity/SSO**          | Auth0/Okta broker                  | Azure AD / Entra ID    | Firebase Auth / Identity Platform | RAM (Resource Access Mgmt)         | `Auth0` broker (see 03-auth-sso-strategy.md)      |
| **Monitoring**            | Amazon CloudWatch / AWS X-Ray      | Azure Monitor          | Cloud Monitoring + Logging        | ARMS + SLS                         | `TelemetryExporter`                               |
| **Secrets**               | AWS Secrets Manager                | Azure Key Vault        | Secret Manager                    | KMS                                | `SecretStore`                                     |
| **Document Processing**   | Amazon Textract                    | Azure Doc Intelligence | Document AI                       | OCR Service                        | `DocumentExtractor`                               |
| **Speech**                | Amazon Transcribe                  | Azure Speech Services  | Speech-to-Text                    | Intelligent Speech Interaction     | `SpeechService`                                   |
| **Cache**                 | Amazon ElastiCache (Redis)         | Azure Cache for Redis  | Memorystore (Redis)               | ApsaraDB for Redis                 | Direct Redis client (portable)                    |
| **Workspace Integration** | N/A                                | MS Graph API           | Google Workspace API              | DingTalk Open API                  | `WorkspaceConnector`                              |

---

## Abstraction Layer Design

### Layer 1: Document Store (Cosmos DB Replacement)

The `TenantScopedRepository` from `02-data-isolation.md:149-211` already abstracts database operations. The cloud-agnostic layer sits beneath it:

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class DocumentStore(ABC):
    """
    Abstract document store interface.

    All database operations MUST go through this interface.
    Never import cloud-specific SDKs in application code.
    """

    @abstractmethod
    async def get_container(self, name: str) -> "Container":
        """Get a named container/table/collection."""

    @abstractmethod
    async def create_item(self, container: str, item: dict, partition_key: str) -> dict:
        """Create a document."""

    @abstractmethod
    async def read_item(self, container: str, item_id: str, partition_key: str) -> dict:
        """Read a document by ID."""

    @abstractmethod
    async def query_items(
        self,
        container: str,
        query: str,
        parameters: List[dict],
        partition_key: Optional[str] = None,
    ) -> List[dict]:
        """Query documents with parameters."""

    @abstractmethod
    async def replace_item(
        self, container: str, item_id: str, item: dict, partition_key: str,
    ) -> dict:
        """Replace a document."""

    @abstractmethod
    async def delete_item(self, container: str, item_id: str, partition_key: str):
        """Delete a document."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check store connectivity."""


class CosmosDBStore(DocumentStore):
    """Azure Cosmos DB implementation."""

    def __init__(self, endpoint: str, key: str, database: str):
        from azure.cosmos.aio import CosmosClient
        self.client = CosmosClient(endpoint, credential=key)
        self.database = self.client.get_database_client(database)

    async def create_item(self, container, item, partition_key):
        container_client = self.database.get_container_client(container)
        return await container_client.create_item(item)

    async def read_item(self, container, item_id, partition_key):
        container_client = self.database.get_container_client(container)
        return await container_client.read_item(item_id, partition_key=partition_key)

    async def query_items(self, container, query, parameters, partition_key=None):
        container_client = self.database.get_container_client(container)
        kwargs = {"query": query, "parameters": parameters}
        if partition_key:
            kwargs["partition_key"] = partition_key
        else:
            kwargs["enable_cross_partition_query"] = True
        return list(container_client.query_items(**kwargs))

    # ... replace_item, delete_item, health_check


class DynamoDBStore(DocumentStore):
    """AWS DynamoDB implementation."""

    def __init__(self, region: str, table_prefix: str = "mingai_"):
        import aioboto3
        self.session = aioboto3.Session()
        self.region = region
        self.prefix = table_prefix

    async def create_item(self, container, item, partition_key):
        async with self.session.resource("dynamodb", region_name=self.region) as dynamodb:
            table = await dynamodb.Table(f"{self.prefix}{container}")
            await table.put_item(Item=item)
            return item

    async def read_item(self, container, item_id, partition_key):
        async with self.session.resource("dynamodb", region_name=self.region) as dynamodb:
            table = await dynamodb.Table(f"{self.prefix}{container}")
            response = await table.get_item(Key={"id": item_id, "tenant_id": partition_key})
            return response.get("Item")

    async def query_items(self, container, query, parameters, partition_key=None):
        # DynamoDB uses KeyConditionExpression, not SQL
        # Translate parameterized query to DynamoDB format
        async with self.session.resource("dynamodb", region_name=self.region) as dynamodb:
            table = await dynamodb.Table(f"{self.prefix}{container}")
            if partition_key:
                response = await table.query(
                    KeyConditionExpression="tenant_id = :tid",
                    ExpressionAttributeValues={":tid": partition_key},
                )
                return response.get("Items", [])
            else:
                response = await table.scan()
                return response.get("Items", [])


class FirestoreStore(DocumentStore):
    """Google Cloud Firestore implementation."""

    def __init__(self, project_id: str, database: str = "(default)"):
        from google.cloud.firestore_v1 import AsyncClient
        self.client = AsyncClient(project=project_id, database=database)

    async def create_item(self, container, item, partition_key):
        doc_ref = self.client.collection(container).document(item["id"])
        await doc_ref.set(item)
        return item

    async def read_item(self, container, item_id, partition_key):
        doc_ref = self.client.collection(container).document(item_id)
        doc = await doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        raise KeyError(f"Document {item_id} not found")

    async def query_items(self, container, query, parameters, partition_key=None):
        collection = self.client.collection(container)
        if partition_key:
            query_ref = collection.where("tenant_id", "==", partition_key)
        else:
            query_ref = collection
        docs = await query_ref.get()
        return [doc.to_dict() for doc in docs]
```

### Layer 2: Search Engine (Azure AI Search Replacement)

```python
class SearchEngine(ABC):
    """Abstract vector search engine interface."""

    @abstractmethod
    async def search(
        self,
        index_name: str,
        query_text: str,
        query_vector: Optional[List[float]] = None,
        filters: Optional[str] = None,
        top: int = 5,
    ) -> List[dict]:
        """Hybrid text + vector search."""

    @abstractmethod
    async def create_index(self, index_name: str, fields: List[dict], vector_config: dict):
        """Create a search index with vector support."""

    @abstractmethod
    async def index_documents(self, index_name: str, documents: List[dict]):
        """Index/update documents."""

    @abstractmethod
    async def delete_index(self, index_name: str):
        """Delete an index."""

    @abstractmethod
    async def get_index_stats(self, index_name: str) -> dict:
        """Get document count and storage size."""


class AzureAISearchEngine(SearchEngine):
    """Azure AI Search implementation (current)."""

    def __init__(self, endpoint: str, admin_key: str, query_key: str):
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient
        self.endpoint = endpoint
        self.admin_credential = AzureKeyCredential(admin_key)
        self.query_credential = AzureKeyCredential(query_key)

    async def search(self, index_name, query_text, query_vector=None, filters=None, top=5):
        from azure.search.documents import SearchClient
        from azure.search.documents.models import VectorizedQuery

        client = SearchClient(
            endpoint=self.endpoint,
            index_name=index_name,
            credential=self.query_credential,
        )

        vector_queries = None
        if query_vector:
            vector_queries = [VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top,
                fields="content_vector",
            )]

        results = client.search(
            search_text=query_text,
            vector_queries=vector_queries,
            filter=filters,
            top=top,
        )
        return [dict(r) for r in results]


class OpenSearchEngine(SearchEngine):
    """AWS OpenSearch / Alibaba OpenSearch implementation."""

    def __init__(self, endpoint: str, username: str, password: str):
        from opensearchpy import AsyncOpenSearch
        self.client = AsyncOpenSearch(
            hosts=[endpoint],
            http_auth=(username, password),
            use_ssl=True,
        )

    async def search(self, index_name, query_text, query_vector=None, filters=None, top=5):
        body = {
            "size": top,
            "query": {
                "bool": {
                    "must": [{"match": {"content": query_text}}] if query_text else [],
                }
            }
        }

        if query_vector:
            body["knn"] = {
                "content_vector": {
                    "vector": query_vector,
                    "k": top,
                }
            }

        if filters:
            body["query"]["bool"]["filter"] = [{"term": filters}]

        response = await self.client.search(index=index_name, body=body)
        return [hit["_source"] for hit in response["hits"]["hits"]]
```

### Layer 3: Object Store (Azure Blob Replacement)

```python
class ObjectStore(ABC):
    """Abstract object/blob storage interface."""

    @abstractmethod
    async def upload(self, container: str, path: str, data: bytes, content_type: str = None):
        """Upload an object."""

    @abstractmethod
    async def download(self, container: str, path: str) -> bytes:
        """Download an object."""

    @abstractmethod
    async def list_objects(self, container: str, prefix: str = "") -> List[str]:
        """List object paths with optional prefix filter."""

    @abstractmethod
    async def delete(self, container: str, path: str):
        """Delete an object."""

    @abstractmethod
    async def get_signed_url(self, container: str, path: str, expires_in: int = 3600) -> str:
        """Generate a pre-signed/SAS URL for direct download."""


class AzureBlobStore(ObjectStore):
    """Azure Blob Storage implementation (current)."""

    def __init__(self, connection_string: str):
        from azure.storage.blob.aio import BlobServiceClient
        self.client = BlobServiceClient.from_connection_string(connection_string)

    async def upload(self, container, path, data, content_type=None):
        container_client = self.client.get_container_client(container)
        kwargs = {}
        if content_type:
            from azure.storage.blob import ContentSettings
            kwargs["content_settings"] = ContentSettings(content_type=content_type)
        await container_client.upload_blob(path, data, overwrite=True, **kwargs)

    async def download(self, container, path):
        container_client = self.client.get_container_client(container)
        blob = await container_client.download_blob(path)
        return await blob.readall()

    async def get_signed_url(self, container, path, expires_in=3600):
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions
        from datetime import datetime, timezone, timedelta
        sas = generate_blob_sas(
            account_name=self.client.account_name,
            container_name=container,
            blob_name=path,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
        return f"{self.client.url}{container}/{path}?{sas}"


class S3Store(ObjectStore):
    """AWS S3 implementation."""

    def __init__(self, region: str, bucket_prefix: str = "mingai-"):
        import aioboto3
        self.session = aioboto3.Session()
        self.region = region
        self.prefix = bucket_prefix

    async def upload(self, container, path, data, content_type=None):
        bucket = f"{self.prefix}{container}"
        async with self.session.client("s3", region_name=self.region) as s3:
            kwargs = {"Bucket": bucket, "Key": path, "Body": data}
            if content_type:
                kwargs["ContentType"] = content_type
            await s3.put_object(**kwargs)

    async def download(self, container, path):
        bucket = f"{self.prefix}{container}"
        async with self.session.client("s3", region_name=self.region) as s3:
            response = await s3.get_object(Bucket=bucket, Key=path)
            return await response["Body"].read()

    async def get_signed_url(self, container, path, expires_in=3600):
        bucket = f"{self.prefix}{container}"
        async with self.session.client("s3", region_name=self.region) as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": path},
                ExpiresIn=expires_in,
            )


class GCSStore(ObjectStore):
    """Google Cloud Storage implementation."""

    def __init__(self, project_id: str):
        from google.cloud.storage import Client
        self.client = Client(project=project_id)

    async def upload(self, container, path, data, content_type=None):
        bucket = self.client.bucket(container)
        blob = bucket.blob(path)
        blob.upload_from_string(data, content_type=content_type)

    async def download(self, container, path):
        bucket = self.client.bucket(container)
        blob = bucket.blob(path)
        return blob.download_as_bytes()

    async def get_signed_url(self, container, path, expires_in=3600):
        from datetime import timedelta
        bucket = self.client.bucket(container)
        blob = bucket.blob(path)
        return blob.generate_signed_url(expiration=timedelta(seconds=expires_in))
```

### Layer 4: Secret Store (Key Vault Replacement)

```python
class SecretStore(ABC):
    """Abstract secret/credential management interface."""

    @abstractmethod
    async def get_secret(self, name: str) -> str:
        """Retrieve a secret value."""

    @abstractmethod
    async def set_secret(self, name: str, value: str):
        """Store a secret value."""

    @abstractmethod
    async def delete_secret(self, name: str):
        """Delete a secret."""


class AzureKeyVaultStore(SecretStore):
    """Azure Key Vault implementation."""

    def __init__(self, vault_url: str):
        from azure.identity.aio import DefaultAzureCredential
        from azure.keyvault.secrets.aio import SecretClient
        self.client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())

    async def get_secret(self, name):
        secret = await self.client.get_secret(name)
        return secret.value

    async def set_secret(self, name, value):
        await self.client.set_secret(name, value)


class AWSSecretsManagerStore(SecretStore):
    """AWS Secrets Manager implementation."""

    def __init__(self, region: str):
        import aioboto3
        self.session = aioboto3.Session()
        self.region = region

    async def get_secret(self, name):
        async with self.session.client("secretsmanager", region_name=self.region) as sm:
            response = await sm.get_secret_value(SecretId=name)
            return response["SecretString"]

    async def set_secret(self, name, value):
        async with self.session.client("secretsmanager", region_name=self.region) as sm:
            try:
                await sm.update_secret(SecretId=name, SecretString=value)
            except sm.exceptions.ResourceNotFoundException:
                await sm.create_secret(Name=name, SecretString=value)


class GCPSecretManagerStore(SecretStore):
    """Google Cloud Secret Manager implementation."""

    def __init__(self, project_id: str):
        from google.cloud import secretmanager_v1
        self.client = secretmanager_v1.SecretManagerServiceAsyncClient()
        self.project = project_id

    async def get_secret(self, name):
        resource_name = f"projects/{self.project}/secrets/{name}/versions/latest"
        response = await self.client.access_secret_version(name=resource_name)
        return response.payload.data.decode("utf-8")

    async def set_secret(self, name, value):
        parent = f"projects/{self.project}/secrets/{name}"
        await self.client.add_secret_version(
            parent=parent,
            payload={"data": value.encode("utf-8")},
        )
```

### Layer 5: Telemetry Exporter (Azure Monitor Replacement)

```python
class TelemetryExporter(ABC):
    """Abstract telemetry/monitoring interface."""

    @abstractmethod
    async def track_event(self, name: str, properties: dict):
        """Track a custom event."""

    @abstractmethod
    async def track_metric(self, name: str, value: float, dimensions: dict = None):
        """Track a metric value."""

    @abstractmethod
    async def track_exception(self, exception: Exception, properties: dict = None):
        """Track an exception."""


class AzureMonitorExporter(TelemetryExporter):
    """Azure Monitor / Application Insights."""

    def __init__(self, connection_string: str):
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        self.exporter = AzureMonitorTraceExporter(connection_string=connection_string)


class CloudWatchExporter(TelemetryExporter):
    """AWS CloudWatch."""

    def __init__(self, region: str, log_group: str):
        import aioboto3
        self.session = aioboto3.Session()
        self.region = region
        self.log_group = log_group


class GCPMonitoringExporter(TelemetryExporter):
    """Google Cloud Monitoring + Logging."""

    def __init__(self, project_id: str):
        from google.cloud import monitoring_v3
        self.client = monitoring_v3.MetricServiceClient()
        self.project = project_id
```

---

## Environment Variable Abstraction

### Current: Azure-Specific Variables (config.py)

The current `config.py` has 80+ Azure-specific environment variables. The abstraction layer uses provider-agnostic naming:

### New: Cloud-Agnostic Variables

```python
class CloudAgnosticSettings(BaseSettings):
    """Cloud-agnostic configuration. Provider selected by CLOUD_PROVIDER."""

    # Cloud Provider Selection
    cloud_provider: str = Field(default="aws")  # aws | azure | gcp | alicloud | self-hosted

    # Document Store
    document_store_endpoint: str = Field(default="")
    document_store_key: str = Field(default="")
    document_store_database: str = Field(default="mingai")

    # Search Engine
    search_engine_endpoint: str = Field(default="")
    search_engine_admin_key: str = Field(default="")
    search_engine_query_key: str = Field(default="")

    # Object Store
    object_store_connection: str = Field(default="")  # Connection string or region
    object_store_container: str = Field(default="mingai-docs")

    # Secret Store
    secret_store_url: str = Field(default="")  # Vault URL or ARN

    # Telemetry
    telemetry_connection: str = Field(default="")

    # Cache (Redis -- portable across all clouds)
    redis_url: str = Field(default="redis://localhost:6379/0")
```

### Provider Factory

```python
def create_infrastructure(settings: CloudAgnosticSettings) -> Infrastructure:
    """
    Create cloud-specific infrastructure from agnostic config.

    This is the ONLY place where cloud-specific SDKs are imported.
    """
    provider = settings.cloud_provider

    if provider == "aws":
        region = settings.document_store_endpoint  # AWS uses region
        return Infrastructure(
            document_store=PostgreSQLStore(
                connection_string=settings.document_store_endpoint,
                database=settings.document_store_database,
            ),
            search_engine=OpenSearchEngine(
                endpoint=settings.search_engine_endpoint,
                username="admin",
                password=settings.search_engine_admin_key,
            ),
            object_store=S3Store(region=region),
            secret_store=AWSSecretsManagerStore(region=region),
            telemetry=CloudWatchExporter(region=region, log_group="mingai"),
        )

    elif provider == "azure":
        return Infrastructure(
            document_store=CosmosDBStore(
                endpoint=settings.document_store_endpoint,
                key=settings.document_store_key,
                database=settings.document_store_database,
            ),
            search_engine=AzureAISearchEngine(
                endpoint=settings.search_engine_endpoint,
                admin_key=settings.search_engine_admin_key,
                query_key=settings.search_engine_query_key,
            ),
            object_store=AzureBlobStore(
                connection_string=settings.object_store_connection,
            ),
            secret_store=AzureKeyVaultStore(
                vault_url=settings.secret_store_url,
            ),
            telemetry=AzureMonitorExporter(
                connection_string=settings.telemetry_connection,
            ),
        )

    elif provider == "gcp":
        project = settings.document_store_endpoint  # GCP uses project ID
        return Infrastructure(
            document_store=FirestoreStore(project_id=project),
            search_engine=OpenSearchEngine(  # Or Vertex AI Search
                endpoint=settings.search_engine_endpoint,
                username="admin",
                password=settings.search_engine_admin_key,
            ),
            object_store=GCSStore(project_id=project),
            secret_store=GCPSecretManagerStore(project_id=project),
            telemetry=GCPMonitoringExporter(project_id=project),
        )

    elif provider == "alicloud":
        return Infrastructure(
            document_store=DynamoDBStore(  # ApsaraDB for MongoDB compatible
                region=settings.document_store_endpoint,
            ),
            search_engine=OpenSearchEngine(
                endpoint=settings.search_engine_endpoint,
                username="admin",
                password=settings.search_engine_admin_key,
            ),
            object_store=OSSStore(  # Alibaba OSS
                endpoint=settings.object_store_connection,
            ),
            secret_store=AliKMSStore(
                endpoint=settings.secret_store_url,
            ),
            telemetry=ARMSExporter(
                endpoint=settings.telemetry_connection,
            ),
        )

    raise ValueError(f"Unsupported cloud provider: {provider}")
```

---

## Container-First Deployment (Docker / Kubernetes)

### Current Architecture

The system already uses Docker containers:

```
mingai/
├── src/backend/api-service/        # FastAPI application
├── src/backend/sync-worker/        # Background worker
├── src/mcp-servers/                # 9 MCP server containers
│   ├── azure-ad-mcp/
│   ├── bloomberg-mcp/
│   ├── perplexity-mcp/
│   ├── capiq-mcp/
│   ├── ilevel-mcp/
│   ├── oracle-fusion-mcp/
│   ├── pitchbook-mcp/
│   ├── teamworks-mcp/
│   └── alphageo-mcp/
└── src/frontend/                   # Next.js frontend
```

### Kubernetes Deployment

```yaml
# k8s/base/api-service.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api-service
  template:
    metadata:
      labels:
        app: api-service
    spec:
      containers:
        - name: api-service
          image: mingai/api-service:latest
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: cloud-config
            - secretRef:
                name: cloud-secrets
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2000m"
              memory: "4Gi"
          livenessProbe:
            httpGet:
              path: /v1/health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /v1/health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
```

### Cloud-Specific Overlays (Kustomize)

```
k8s/
├── base/                    # Common manifests
│   ├── api-service.yaml
│   ├── sync-worker.yaml
│   ├── frontend.yaml
│   ├── redis.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── aws/                # AWS-specific config (Phase 1 -- primary)
│   │   ├── configmap.yaml  # CLOUD_PROVIDER=aws, Aurora PostgreSQL settings
│   │   ├── secrets.yaml    # AWS credentials
│   │   ├── ingress.yaml    # AWS ALB + CloudFront
│   │   └── kustomization.yaml
│   ├── azure/              # Azure-specific config (Phase 5)
│   │   ├── configmap.yaml  # CLOUD_PROVIDER=azure, Cosmos DB settings
│   │   ├── secrets.yaml    # Azure credentials
│   │   ├── ingress.yaml    # Azure Application Gateway
│   │   └── kustomization.yaml
│   ├── gcp/                # GCP-specific config (Phase 5)
│   │   ├── configmap.yaml  # CLOUD_PROVIDER=gcp, Firestore settings
│   │   ├── secrets.yaml    # GCP service account
│   │   ├── ingress.yaml    # GCP Cloud Load Balancer
│   │   └── kustomization.yaml
│   └── alicloud/           # Alibaba-specific config (Phase 5)
│       ├── configmap.yaml  # CLOUD_PROVIDER=alicloud
│       └── kustomization.yaml
```

---

## Infrastructure as Code (Terraform)

### Module Structure

AWS is the primary module (Phase 1). Azure and GCP modules are scaffolded but implemented in Phase 5.

```
terraform/
├── modules/
│   ├── document-store/
│   │   ├── aws/            # Aurora PostgreSQL / RDS PostgreSQL (Phase 1)
│   │   │   ├── main.tf
│   │   │   ├── variables.tf
│   │   │   └── outputs.tf
│   │   ├── azure/          # Cosmos DB (Phase 5)
│   │   └── gcp/            # Firestore / Cloud SQL (Phase 5)
│   ├── search-engine/
│   │   ├── aws/            # OpenSearch Service (Phase 1)
│   │   ├── azure/          # Azure AI Search (Phase 5)
│   │   └── gcp/            # Vertex AI Search (Phase 5)
│   ├── object-store/
│   │   ├── aws/            # S3 (Phase 1)
│   │   ├── azure/          # Blob Storage (Phase 5)
│   │   └── gcp/            # GCS (Phase 5)
│   ├── cache/
│   │   ├── aws/            # ElastiCache Redis (Phase 1)
│   │   ├── azure/          # Azure Cache for Redis (Phase 5)
│   │   └── gcp/            # Memorystore (Phase 5)
│   ├── secret-store/
│   │   ├── aws/            # Secrets Manager (Phase 1)
│   │   ├── azure/          # Key Vault (Phase 5)
│   │   └── gcp/            # Secret Manager (Phase 5)
│   └── kubernetes/
│       ├── aws/            # EKS (Phase 1)
│       ├── azure/          # AKS (Phase 5)
│       └── gcp/            # GKE (Phase 5)
├── environments/
│   ├── aws-dev/
│   │   └── main.tf         # cloud_provider = "aws"
│   ├── aws-prod/
│   │   └── main.tf         # cloud_provider = "aws"
│   ├── azure-prod/         # Phase 5
│   └── gcp-prod/           # Phase 5
└── main.tf                 # Root module with provider selection
```

### Root Module Example

```hcl
# terraform/main.tf
variable "cloud_provider" {
  type    = string
  default = "aws"
  validation {
    condition     = contains(["aws", "azure", "gcp", "alicloud"], var.cloud_provider)
    error_message = "Supported providers: aws, azure, gcp, alicloud"
  }
}

module "document_store" {
  source = "./modules/document-store/${var.cloud_provider}"

  database_name = "mingai"
  environment   = var.environment
  tags          = var.tags
}

module "search_engine" {
  source = "./modules/search-engine/${var.cloud_provider}"

  environment = var.environment
  tags        = var.tags
}

module "object_store" {
  source = "./modules/object-store/${var.cloud_provider}"

  container_name = "mingai-docs"
  environment    = var.environment
  tags           = var.tags
}

module "kubernetes" {
  source = "./modules/kubernetes/${var.cloud_provider}"

  cluster_name = "mingai-${var.environment}"
  node_count   = var.node_count
  node_size    = var.node_size
  tags         = var.tags
}

# Outputs for application configuration
output "cloud_config" {
  value = {
    CLOUD_PROVIDER            = var.cloud_provider
    DOCUMENT_STORE_ENDPOINT   = module.document_store.endpoint
    DOCUMENT_STORE_KEY        = module.document_store.primary_key
    DOCUMENT_STORE_DATABASE   = module.document_store.database_name
    SEARCH_ENGINE_ENDPOINT    = module.search_engine.endpoint
    SEARCH_ENGINE_ADMIN_KEY   = module.search_engine.admin_key
    OBJECT_STORE_CONNECTION   = module.object_store.connection_string
    SECRET_STORE_URL          = module.secret_store.vault_url
    REDIS_URL                 = module.cache.connection_string
  }
}
```

---

## Migration Priority

### Phase 1: Abstraction Layer + AWS Adapters (Launch Platform)

Introduce interfaces in front of all Azure SDK calls. Implement AWS adapters as the primary (and only Phase 1) cloud backend. The application code references interfaces only:

| Service      | Current Import                                         | New Import                                 | Phase 1 Adapter            |
| ------------ | ------------------------------------------------------ | ------------------------------------------ | -------------------------- |
| Cosmos DB    | `from azure.cosmos.aio import CosmosClient`            | `from app.infra import get_document_store` | `PostgreSQLStore` (Aurora) |
| AI Search    | `from azure.search.documents import SearchClient`      | `from app.infra import get_search_engine`  | `OpenSearchEngine`         |
| Blob Storage | `from azure.storage.blob.aio import BlobServiceClient` | `from app.infra import get_object_store`   | `S3Store`                  |
| Key Vault    | `from azure.keyvault.secrets.aio import SecretClient`  | `from app.infra import get_secret_store`   | `AWSSecretsManagerStore`   |

### Phase 5: Azure + GCP + Alibaba Adapters

Implement Azure-specific backends (Cosmos DB, Azure AI Search, Blob Storage, Key Vault) and GCP backends (Firestore, Vertex AI Search, GCS, Secret Manager). At this point, the application is fully cloud-agnostic across all target platforms.

### Services That Stay Cloud-Specific

| Service                     | Reason            | Approach                          |
| --------------------------- | ----------------- | --------------------------------- |
| MS Graph API                | Microsoft-only    | Workspace connector abstraction   |
| SharePoint Sync             | Microsoft-only    | Enterprise connector per cloud    |
| Azure Document Intelligence | Best-in-class OCR | Textract/Document AI alternatives |

---

**Document Version**: 2.0
**Last Updated**: March 4, 2026
**Key Change**: AWS-first deployment strategy. Cloud abstraction layer built from day 1; only AWS adapters implemented in Phase 1. Azure/GCP adapters in Phase 5.
