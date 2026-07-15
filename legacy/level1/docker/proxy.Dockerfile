FROM python:3.12-slim

COPY benchmark_harness/model_proxy.py /opt/model_proxy.py
USER 65534:65534
ENTRYPOINT ["python", "/opt/model_proxy.py"]
