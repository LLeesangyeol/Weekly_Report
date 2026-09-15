FROM node:22-bookworm-slim AS web-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM node:22-bookworm-slim AS parser-builder
WORKDIR /build/parser
COPY parser/package.json parser/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-impress nodejs fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY --from=web-builder /build/frontend/dist ./frontend/dist
COPY parser/parse.mjs parser/package.json ./parser/
COPY --from=parser-builder /build/parser/node_modules ./parser/node_modules
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
