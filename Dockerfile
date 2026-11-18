FROM node:24-bookworm-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MODEL_DIR=/opt/models
COPY pyproject.toml ./
COPY matchbench ./matchbench
RUN pip install . && python -m matchbench.cli models
COPY data ./data
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=ui /app/frontend/dist ./frontend/dist
RUN useradd --create-home matchbench
USER matchbench
EXPOSE 8000
CMD ["uvicorn", "matchbench.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
