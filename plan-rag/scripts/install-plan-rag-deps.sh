#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${PLAN_RAG_CONDA_ENV:-codex}"

command -v mamba >/dev/null 2>&1 || {
  printf 'mamba is required to install Plan RAG dependencies.\n' >&2
  exit 1
}

mamba install -n "${ENV_NAME}" -y -c conda-forge watchdog numpy

# conda-forge chromadb pins FastAPI 0.115.9, which can downgrade or remove
# LiteLLM in the shared codex environment. Plan RAG supplies embeddings through
# its configured backend, so install Chroma without its unused default ONNX
# embedding stack and add only the runtime packages needed by PersistentClient.
mamba install -n "${ENV_NAME}" -y -c conda-forge --no-deps \
  chromadb=1.5.9 \
  overrides pypika bcrypt mmh3 posthog pybase64 tenacity \
  grpcio libgrpc libprotobuf libre2-11 re2 protobuf \
  opentelemetry-api opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-common \
  opentelemetry-exporter-otlp-proto-grpc \
  opentelemetry-proto opentelemetry-semantic-conventions \
  googleapis-common-protos deprecated wrapt backoff

mamba run -n "${ENV_NAME}" python -c \
  "import chromadb, mcp, pydantic, watchdog"

mamba run -n "${ENV_NAME}" python -c \
  "import chromadb,tempfile; p=tempfile.mkdtemp(); c=chromadb.PersistentClient(path=p); x=c.get_or_create_collection('smoke',embedding_function=None); x.add(ids=['x'],embeddings=[[1.0,0.0]],documents=['plan']); assert x.query(query_embeddings=[[1.0,0.0]],n_results=1)['ids']==[['x']]"
