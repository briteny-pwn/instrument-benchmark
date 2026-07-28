FROM python:3.11.9-slim-bookworm@sha256:2856e6af199e8128161abd320575eb9b341f3b76f017b5d0c9cd364f60d8a050

ARG SOURCE_DATE_EPOCH
ENV PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}

COPY wheelhouse /build/wheels
COPY evaluator-requirements.lock /build/evaluator-requirements.lock
RUN python -m pip install --no-index --require-hashes \
      --find-links=/build/wheels -r /build/evaluator-requirements.lock

COPY evaluator /build/evaluator
RUN python -m pip install --no-index --no-deps --no-build-isolation /build/evaluator \
 && groupadd --gid 11001 evaluator \
 && useradd --uid 11001 --gid 11001 --no-create-home evaluator \
 && rm -rf /build /root/.cache

WORKDIR /run/evaluator
USER 11001:11001
ENTRYPOINT ["python", "-m", "instrument_benchmark_evaluator.cli"]
