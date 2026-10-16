# Common CPU adapter/controller; the stub is a separate optional build target.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS base
ENV PYTHONUNBUFFERED=1
COPY --from=ghcr.io/astral-sh/uv:0.9.5@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /tmp/runner/
RUN uv export --project /tmp/runner --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install --system --no-cache --no-deps .
COPY models ./models

FROM base AS stub-engine
RUN uv export --project /tmp/runner --frozen --no-dev --group stub --no-emit-project -o /tmp/stub.txt \
    && uv pip install --system --no-cache -r /tmp/stub.txt
USER 65532:65532
ENTRYPOINT ["video-stub-engine"]

FROM base AS controller
RUN mkdir /state /leases && chown 65532:65532 /state /leases
USER 65532:65532
ENTRYPOINT ["video-controller"]

FROM base AS model-tools
RUN uv export --project /tmp/runner --frozen --no-dev --group assets --no-emit-project -o /tmp/assets.txt \
    && uv pip install --system --no-cache -r /tmp/assets.txt
COPY src/video_runners/tools/prepare_weights.py /app/prepare-weights.py
COPY configs/model-assets.json /app/model-assets.json
ENTRYPOINT ["python", "/app/prepare-weights.py"]

FROM base AS runner
USER 65532:65532
ENTRYPOINT ["video-runner"]
