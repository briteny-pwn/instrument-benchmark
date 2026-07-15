FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ cmake && rm -rf /var/lib/apt/lists/*
WORKDIR /instance
COPY evaluator /evaluator
COPY instances/iab_0010 /instance
CMD ["bash", "setup.sh"]
