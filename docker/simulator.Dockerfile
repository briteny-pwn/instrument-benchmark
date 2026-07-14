FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/instrument-benchmark
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY evaluations ./evaluations
COPY benchmark_harness ./benchmark_harness
ENTRYPOINT ["python", "-m", "benchmark_harness.simulator_service"]
