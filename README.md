# Agnes Mini - CPG Swap Agent for Raw Material Replacement

Spherecast is a backend-first hackathon project that helps teams evaluate raw material or component replacements in CPG products. It combines internal product and supplier data with external evidence gathering to validate a request, find alternative suppliers, extract technical specifications, and rank possible substitutes.

This repository is the main submission. It focuses on the backend, orchestration logic, and supplier evaluation workflow. A separate frontend demo exists, but this README keeps the attention on the backend system.

## Why This Matters

Replacing a raw material is rarely a simple search problem.

Teams need to answer practical questions fast:
- Is the requested replacement valid for this product?
- Which suppliers offer comparable components?
- What technical evidence can we find about those alternatives?
- Which option looks like the best fit?

Our goal was to turn that process into a guided AI-assisted workflow.

## General Approach

The system is built as a FastAPI backend with a LangGraph orchestration flow.

At a high level, the workflow is:
1. Accept a user request about replacing a component.
2. Detect intent and extract missing details.
3. Validate the request against internal product, BOM, and supplier data.
4. Classify the component into a route vector and metadata structure.
5. Find alternative suppliers and similar components from internal data.
6. Gather external evidence and fill a comparable spec matrix.
7. Rank alternatives against the current supplier.

This combines two kinds of knowledge:
- Internal structured data from the company database.
- External evidence gathered from supplier-facing web sources.

## Architecture Overview

### Backend API

The backend is built with:
- FastAPI
- Uvicorn
- Python

The API exposes endpoints for:
- conversational agent requests
- validation of replacement inputs
- supplier and product lookup
- route-vector inspection for components

### Orchestration Layer

LangGraph coordinates the main decision flow:
- intent detection
- missing field collection
- validation
- component classification
- supplier filtering
- spec filling
- supplier ranking

The graph structure is generated in this repo and saved as `langgraph_structure.png`.

### Data Layer

Postgres is used for:
- validating products, suppliers, and BOM relationships
- storing assistant thread state
- optionally storing run logs for spec filling and ranking

### External Evidence Layer

The crawler and spec-filling flow use Google tooling and `google-genai` to:
- search for supplier-specific product evidence
- read technical pages
- extract structured specifications

This is where internal structuring and external evidence meet. The internal schema defines what we want to compare, and the external evidence layer tries to populate those fields with real supplier-specific data.

## What Worked

The main success was that the end-to-end backend flow worked well enough to demonstrate the full concept.

What worked best:
- The FastAPI backend and LangGraph orchestration were connected into a single working pipeline.
- The system could collect missing request fields over multiple turns.
- Validation against internal product, BOM, and supplier data worked as a strong first filter.
- Supplier and component lookup from internal data gave the workflow a solid foundation.
- The route-vector approach gave us a practical prototype for deciding which product structure to use.
- The spec-filling and ranking pipeline showed that we could move from a natural-language replacement request to a ranked list of alternatives.

In short, we proved the backend concept from request intake to ranked recommendation.

## What Did Not Work

Some important parts worked only partially or were hard to operationalize in hackathon time.

### 1. Sparse External Supplier Data

The crawler depends on supplier-facing technical information being available online.

That was a major limitation:
- Many suppliers did not publish enough usable technical data.
- Even when pages existed, the evidence was often incomplete for the fields we wanted to compare.
- This reduced the quality of the filled spec matrix.

> **Warning**
> The biggest practical weakness of the crawler was not just model quality. It was missing or inconsistent supplier data on the open web.

### 2. Deployment Friction for the Crawler

We used Google-based tooling and `google-genai` for the evidence layer.

That introduced deployment pain:
- Cloud credentials and environment setup were hard to get right.
- Vertex AI and service-account configuration added extra operational complexity.
- This made the crawler much harder to deploy than the rest of the backend.

> **Important**
> The Google cloud credential flow was one of the biggest engineering obstacles during the hackathon.

### 3. Limited LLM Observability

We did not build enough logging and evaluation around model decisions.

That made it harder to answer questions like:
- Why was a request routed a certain way?
- Why was a component assigned to a given structure?
- How reliable was a ranking result?

The prototype works, but the decision trail is not strong enough yet.

### 4. Weak Metrics and Evaluation

We did not have enough time to build strong evaluation metrics.

That affects several parts of the system:
- intent detection quality
- route-vector classification quality
- crawler evidence quality
- ranking confidence

Without better benchmarks, it is difficult to measure how reliable each stage really is.

### 5. Component Structure Tree Is Useful, but Temporary

The current Component Structure Tree and question-sequence logic gave us a working prototype.

But it is not our preferred long-term solution:
- it is rule-based and relatively rigid
- it does not scale as naturally as a learned similarity-based approach
- it can become harder to maintain as new component types appear

We see it as a good hackathon scaffold, not the final architecture.

## How We Would Improve It

The next version should focus on making the system more reliable, more explainable, and easier to scale.

### 1. Build a Hybrid Evidence Layer

The strongest next step is to improve how we combine internal and external information.

We would:
- fuse internal structured product data with external supplier evidence
- attach confidence scores to extracted values
- keep clearer provenance for each filled field
- use that confidence in downstream ranking

This would make the spec matrix more trustworthy and easier to audit.

### 2. Replace or Augment the Component Tree

Instead of relying only on a fixed question-sequence tree, we would move toward a metadata-based classifier.

A strong next option is:
- use KNN over known component metadata
- assign a new raw material to the class of its nearest known neighbors

That would make classification:
- easier to scale
- easier to improve over time
- less dependent on a rigid handcrafted tree

### 3. Improve LLM Observability

We would add better tracing and logging for:
- intent decisions
- extracted fields
- route-vector assignments
- evidence selection
- ranking explanations

This would make debugging much easier and help us understand failure modes faster.

### 4. Add Proper Evaluation Metrics

We would define clear metrics for each stage of the pipeline.

Examples include:
- intent classification accuracy
- component classification accuracy
- evidence coverage per supplier
- spec extraction precision
- ranking agreement with expert judgment

This would turn the prototype into a system we can improve systematically.

### 5. Improve the Crawler Pipeline

We would make the crawler more robust by:
- adding better fallback handling for missing supplier evidence
- improving PDF and difficult-page support
- reducing deployment friction around cloud credentials
- making external retrieval easier to configure and monitor

## Tech Stack

- Python
- FastAPI
- Uvicorn
- LangGraph
- LangChain
- Postgres
- `google-genai`
- Pydantic
- Docker

## Setup

### Prerequisites

Before starting, make sure you have:
1. Python 3.12 or a compatible local Python environment.
2. A running Postgres database.
3. Either:
   - a `GEMINI_API_KEY`, or
   - Vertex AI access with valid Google Cloud credentials.

### Environment Variables

Create a `.env` file based on `.env.example`.

Required and optional variables:
- `DATABASE_URL`
- `GEMINI_API_KEY` for AI Studio mode
- `USE_VERTEX_AI`
- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`
- `SPEC_LOG_DATABASE_URL` optional

Example:

```env
DATABASE_URL=postgresql://user:pass@host:port/products_db
GEMINI_API_KEY=your_gemini_api_key_here
USE_VERTEX_AI=false
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
SPEC_LOG_DATABASE_URL=postgresql://user:pass@host:port/agent_logs_db
```

> **Important**
> Postgres is required for core app behavior because the backend uses it both for validation and for assistant thread state.

### Local Setup

1. Create and activate a virtual environment.
2. Install dependencies.
3. Configure your `.env` file.
4. Start the API server.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Run the Project

### Run Locally

1. Make sure your environment variables are set.
2. Start the FastAPI app.
3. Send requests to `http://127.0.0.1:8000`.

```powershell
python main.py
```

You can also run it with Uvicorn directly:

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### Run with Docker

1. Build the image.
2. Run the container.
3. Pass the required environment variables.

```powershell
docker build -t spherecast .
docker run -p 8000:8000 --env-file .env spherecast
```

## API Overview

### Main Endpoints

- `POST /agent/request`
- `POST /agent/route-vector`
- `GET /companies`
- `POST /companies/validate`
- `GET /companies/product/{product_id}/suppliers`
- `GET /companies/supplier/{supplier_id}/products`
- `GET /companies/product/{product_name}/supplier-components`

### Example: Agent Request

```bash
curl -X POST http://127.0.0.1:8000/agent/request \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "demo-thread-1",
    "message": "I want to replace calcium citrate in product ABC from supplier XYZ"
  }'
```

### Example: Route Vector Inspection

```bash
curl -X POST http://127.0.0.1:8000/agent/route-vector \
  -H "Content-Type: application/json" \
  -d '{
    "component_name": "Calcium citrate",
    "product_name": "ABC",
    "supplier_name": "XYZ"
  }'
```

### Example: Validate a Replacement Request

```bash
curl -X POST http://127.0.0.1:8000/companies/validate \
  -H "Content-Type: application/json" \
  -d '{
    "product_name": "ABC",
    "component_name": "Calcium citrate",
    "supplier_name": "XYZ"
  }'
```

## Important Notes and Assumptions

> **Assumption**
> This repository is the main hackathon submission narrative and should be read as the technical core of the project.

> **Assumption**
> The current Component Structure Tree is a prototype decision layer, not the final classification approach.

> **Warning**
> The external evidence pipeline depends heavily on supplier data availability and on correct Google cloud credential setup.

> **Note**
> The ranking output is meaningful as a prototype, but it should not yet be treated as production-grade procurement advice.

## Frontend Note

A separate frontend repository exists for demo and UI purposes:

- `https://github.com/EgorPichugin/makeathon-client`

This backend repository is still the main focus of the submission. The core logic, orchestration, validation, evidence gathering, and ranking all live here.
