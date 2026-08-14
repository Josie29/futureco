# syntax=docker/dockerfile:1
#
# Build context is the repo root, because the image needs both backend/ and
# data/: settings.py derives every data path from REPO_ROOT, so the repo layout
# has to survive into the image.

# onnxruntime, which fastembed depends on, publishes manylinux wheels only.
# Alpine is musl, finds no wheel, and falls back to compiling from source — so
# the base stays glibc.
ARG PYTHON_IMAGE=python:3.13-slim
ARG NODE_IMAGE=node:22-alpine
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ARG MODEL_CACHE_DIR=/opt/models


# The console is a static bundle, so the API can serve it and `docker compose
# up` is one command rather than one plus a second terminal on Vite. Node is
# needed to build it and never to run it, which is the whole reason this is a
# build stage and not a service.
FROM ${NODE_IMAGE} AS console

WORKDIR /web
# Same split as the Python layer below: the lockfile alone decides the install,
# so editing a component leaves the dependency layer cached.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
# `npm run build` is `tsc -b && vite build`, so a type error fails the image
# rather than shipping a console that only breaks in the browser.
RUN npm run build


FROM ${PYTHON_IMAGE} AS deps

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend
# Dependencies resolve from these two files alone, so editing source leaves
# this layer — the expensive one — cached.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev


FROM deps AS model
ARG EMBEDDING_MODEL
ARG MODEL_CACHE_DIR

# Bake the 87 MB of ONNX weights now. Without this the image downloads them on
# its first vector lookup, which means a cold `docker compose up` needs network
# at runtime — the one thing this whole stack was chosen to avoid. fastembed's
# own default cache lives under the system temp dir, which is the wrong place
# to leave 87 MB in a container.
RUN /opt/venv/bin/python -c "\
from fastembed import TextEmbedding; \
TextEmbedding(model_name='${EMBEDDING_MODEL}', cache_dir='${MODEL_CACHE_DIR}')"


FROM ${PYTHON_IMAGE} AS runtime
ARG EMBEDDING_MODEL
ARG MODEL_CACHE_DIR

# Ownership is set at copy time, never with a later `chown -R`: rewriting the
# mode bits on an existing layer duplicates every file it touches, which cost
# an extra 174 MB when this image was measured both ways. fastembed writes a
# tree-cache file beside the weights on load, so the model dir cannot stay
# root-owned.
RUN useradd --create-home --uid 1000 app
COPY --from=model --chown=app:app /opt/venv /opt/venv
COPY --from=model --chown=app:app ${MODEL_CACHE_DIR} ${MODEL_CACHE_DIR}

WORKDIR /app
COPY --chown=app:app backend/src /app/backend/src
COPY --chown=app:app data /app/data
COPY --from=console --chown=app:app /web/dist /app/web/dist

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/backend/src \
    PYTHONUNBUFFERED=1 \
    MODEL_CACHE_DIR=${MODEL_CACHE_DIR} \
    CONSOLE_DIR=/app/web/dist

# The model name is written three times — the build argument above and a
# constant in each module that embeds. Assert they all agree, so a change to
# one that misses the others fails the build instead of silently
# re-downloading at first request.
RUN python -c "\
from graph.vocabulary import EMBEDDING_MODEL as build_model; \
from resolver.index import EMBEDDING_MODEL as resolver_model; \
assert build_model == resolver_model == '${EMBEDDING_MODEL}', (build_model, resolver_model)"

USER app

EXPOSE 8000
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
