FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY telemetry/ telemetry/
COPY engine/ engine/
COPY explain/ explain/
COPY app/ app/
# Evidence comes from the evidence bucket, verified on load; none is baked into the image.
ENV EVIDENCE_SOURCE=gcs
# Cloud Run provides $PORT (default 8080).
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
