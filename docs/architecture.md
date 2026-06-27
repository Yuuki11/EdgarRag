# Architecture

FinEdgar is a local-first SEC filing question-answering system. The app keeps
filing data, indexes, chat history, auth state, and model serving under the
operator's control. Cloud services are not required for the default workflow.

The codebase has four main layers:

- `backend/data`: filing ingestion, XBRL lookup, retrieval, scoring, and answer
  orchestration.
- `webapp/backend`: FastAPI routes, auth, sessions, chat persistence, health,
  metrics, and admin APIs.
- `webapp/frontend`: React interface for auth, company selection, chat,
  conversation history, and admin status.
- `docker`, `charts`, and `scripts`: local runtime, jobs, image builds, and the
  optional Kubernetes lab.

## System View

```mermaid
flowchart LR
    Browser[Browser] --> React[React app<br/>webapp/frontend]
    React --> API[FastAPI<br/>webapp/backend]

    API --> Auth[(Postgres<br/>users, sessions,<br/>chat history)]
    API --> Pipeline[Answer pipeline<br/>backend/data/answer_pipeline.py]
    API --> Admin[Admin overview<br/>/api/admin/overview]
    API --> Metrics[/metrics]

    Pipeline --> Planner[Question planning<br/>benchmarking.py]
    Planner --> XBRL[XBRL route<br/>xbrl_fetcher.py<br/>xbrl_reasoning.py]
    Planner --> RAG[RAG route<br/>retrieval.py<br/>embeddings.py<br/>reranker.py]

    XBRL --> XBRLCache[(data/xbrl_cache)]
    RAG --> Chunks[(data/chunks)]
    RAG --> VectorIndex[(data/vector_index)]
    RAG --> Ollama[Ollama<br/>local model server]

    Admin --> DataFiles[(data artifacts)]
    Admin --> Auth
```

## Chat Request Flow

The chat path starts in React, crosses FastAPI once, then runs the synchronous
answer pipeline in a worker thread so the event loop stays available for other
requests.

```mermaid
sequenceDiagram
    participant U as User
    participant UI as React Chat
    participant API as POST /api/chat
    participant Auth as current_user
    participant Pipe as answer_question
    participant X as XBRL logic
    participant R as Retrieval logic
    participant O as Ollama
    participant DB as Postgres

    U->>UI: Ask a question
    UI->>API: question, optional ticker/year/conversation
    API->>Auth: Validate session cookie
    Auth->>DB: Load active user/session
    API->>Pipe: Run in worker thread
    Pipe->>Pipe: Infer route, metrics, years, operation
    alt Structured metric question
        Pipe->>X: Fetch fact or compute ratio
        X-->>Pipe: ComputedAnswer with evidence
    else Narrative filing question
        Pipe->>R: Retrieve and curate passages
        R-->>Pipe: Ranked evidence
        Pipe->>O: Generate grounded answer
        O-->>Pipe: Response text
    end
    Pipe-->>API: PipelineResult
    API->>DB: Persist user and assistant messages
    API-->>UI: ChatResponse
    UI-->>U: Answer, route, citations, evidence
```

## Data Pipeline

The data pipeline produces the artifacts consumed by both the CLI evaluation
scripts and the web app. SEC HTTP calls are rate-limited and require a clear
`SEC_USER_AGENT`.

```mermaid
flowchart TD
    Companies[data/companies.json] --> Bootstrap[scripts/bootstrap_data.py]
    Manifest[data/benchmarks/financebench/manifest.json] --> Bootstrap

    Bootstrap --> Resolver[ticker_resolver.py<br/>ticker to CIK]
    Resolver --> Facts[xbrl_fetcher.py<br/>companyfacts]
    Resolver --> Filings[filing_downloader.py<br/>10-K, 10-Q, 8-K, proxy, exhibits]

    Facts --> XBRLCache[(data/xbrl_cache)]
    Filings --> Raw[(data/filings)]
    Raw --> Parser[section_parser.py<br/>document_parser.py<br/>table_extractor.py]
    Parser --> Parsed[(data/parsed)]
    Parsed --> Chunker[chunker.py]
    Chunker --> Chunks[(data/chunks)]
    Chunks --> Indexer[scripts/build_vector_index.py]
    Indexer --> FAISS[(data/vector_index)]
```

## Answering Strategy

FinEdgar deliberately separates deterministic financial calculations from
narrative synthesis:

- XBRL lookups and ratios use SEC companyfacts and explicit formulas.
- RAG answers use filing chunks, section hints, retrieval scoring, optional
  reranking, and an Ollama generation step.
- Hybrid behavior lets a structured answer fall back to RAG when a filing fact
  is unavailable or when the question is narrative by nature.

```mermaid
flowchart TD
    Q[Question] --> Plan[Build question plan]
    Plan --> Route{Route}

    Route -->|xbrl| XPlan[Metric/year/period/operation plan]
    XPlan --> Compute[compute_xbrl_answer]
    Compute --> XOK{Answer found?}
    XOK -->|yes| Format[Format numeric answer<br/>with fact evidence]
    XOK -->|no| MaybeRAG[Fallback if allowed]

    Route -->|rag or hybrid| Retrieve[retrieve_documents<br/>retrieve_passages]
    MaybeRAG --> Retrieve
    Retrieve --> Curate[curate_evidence]
    Curate --> Extract[LLM extraction prompt]
    Extract --> Synthesize[LLM synthesis prompt]
    Synthesize --> Verify[Basic answer guardrails]

    Format --> Result[PipelineResult]
    Verify --> Result
```

## Web Application Boundaries

```mermaid
flowchart LR
    subgraph Frontend[webapp/frontend]
        App[App.tsx]
        AuthScreen[AuthScreen]
        Sidebar[ConversationSidebar]
        Chat[Chat]
        AdminUI[AdminDashboard]
        APIClient[api.ts]
    end

    subgraph FastAPI[webapp/backend]
        Main[main.py]
        AuthRoutes[routes/auth.py]
        ChatRoutes[routes/chat.py]
        ConversationRoutes[routes/conversations.py]
        AdminRoutes[routes/admin.py]
        HealthRoutes[routes/health.py]
    end

    subgraph Services[webapp/backend/services]
        AuthService[auth.py]
        ConversationService[conversations.py]
        PipelineAdapter[pipeline.py]
        CompanyService[companies.py]
    end

    APIClient --> AuthRoutes
    APIClient --> ChatRoutes
    APIClient --> ConversationRoutes
    APIClient --> AdminRoutes
    APIClient --> HealthRoutes

    Main --> AuthRoutes
    Main --> ChatRoutes
    Main --> ConversationRoutes
    Main --> AdminRoutes
    Main --> HealthRoutes

    AuthRoutes --> AuthService
    ChatRoutes --> PipelineAdapter
    ChatRoutes --> ConversationService
    ConversationRoutes --> ConversationService
    AdminRoutes --> AuthService
    AdminRoutes --> CompanyService
```

## Persistence Model

```mermaid
erDiagram
    users ||--o{ sessions : owns
    users ||--o{ email_verification_tokens : receives
    users ||--o{ password_reset_tokens : receives
    users ||--o{ conversations : owns
    conversations ||--o{ messages : contains
    users ||--o{ auth_events : produces

    users {
        string id
        string email
        string password_hash
        boolean is_active
        boolean is_verified
        datetime created_at
        datetime updated_at
    }

    sessions {
        string id
        string user_id
        string token_hash
        datetime expires_at
        datetime revoked_at
    }

    conversations {
        string id
        string user_id
        string title
        datetime deleted_at
    }

    messages {
        string id
        string conversation_id
        string role
        text content
        json response_json
    }
```

## Runtime Modes

```mermaid
flowchart TD
    Dev[Compose dev<br/>scripts/docker/compose.sh dev] --> Vite[Vite dev server]
    Dev --> FastReload[Reloadable FastAPI]
    Dev --> Postgres[Postgres]
    Dev --> Ollama[Ollama]

    Inference[Compose inference<br/>scripts/docker/compose.sh inference] --> WebImage[Docker web target<br/>built React + FastAPI]
    Inference --> Postgres
    Inference --> Ollama

    K8s[Kubernetes lab<br/>scripts/k8s/deploy.sh] --> Helm[charts/finedgar]
    Helm --> WebDeployment[web Deployment]
    Helm --> CNPG[CloudNativePG Cluster]
    Helm --> OllamaStatefulSet[Ollama StatefulSet]
    Helm --> Jobs[Migration/data/index/eval Jobs]
```

## Kubernetes Workload View

```mermaid
flowchart LR
    Browser --> Gateway[Gateway API]
    Gateway --> Route[HTTPRoute<br/>finedgar.localhost]
    Route --> WebSvc[web Service]
    WebSvc --> WebPods[web Deployment pods]

    WebPods --> PgSvc[CloudNativePG service]
    PgSvc --> PgCluster[(Postgres cluster)]

    WebPods --> OllamaSvc[Ollama Service]
    OllamaSvc --> OllamaSS[Ollama StatefulSet]

    WebPods --> DataPVC[(data PVC)]
    WebPods --> OutputsPVC[(outputs PVC)]
    OllamaSS --> OllamaPVC[(ollama PVC)]

    Jobs[Helm Jobs<br/>migrate/bootstrap/index/eval] --> DataPVC
    Jobs --> PgSvc
    Jobs --> OllamaSvc
```

## CI Verification

The GitHub Actions workflow is intentionally verification-only. It runs after a
push to `main` and never pushes images or deploys.

```mermaid
flowchart TD
    Push[Push to main] --> CI[.github/workflows/main-verify.yml]
    CI --> Py[Install Python deps<br/>pytest backend/tests]
    CI --> Node[npm ci<br/>npm run build]
    CI --> Helm[helm lint<br/>helm template profiles]
    Py --> Docker[Docker Buildx]
    Node --> Docker
    Helm --> Docker
    Docker --> Runtime[Build runtime target<br/>push false]
    Docker --> Web[Build web target<br/>push false]
```

## Operational Boundaries

- The default app is local-first. Do not assume public TLS, SMTP, or cloud
  storage unless those are explicitly configured.
- `data/` artifacts are part of the runtime contract. If they are missing, RAG
  quality and company coverage drop even when the API itself is healthy.
- Ollama is a separate dependency. `/healthz` reports whether it is reachable,
  but the app can still start while model serving is down.
- Postgres is required for authenticated web usage. The data pipeline remains
  file-based.
- GPU support is optional. The CPU path is the default for local demos and CI.
