FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 runner
WORKDIR /workspace
COPY benchmark_harness/solution_runner.py /opt/solution_runner.py
COPY benchmark_harness/forbidden_imports.py /opt/forbidden_imports.py
USER runner
ENTRYPOINT ["python", "/opt/solution_runner.py"]
