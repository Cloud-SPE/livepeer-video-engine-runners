# Runner + CPU stub engine: exercises the whole Livepeer path without a GPU.
FROM python:3.15-slim

# Flush stdout/stderr immediately so output isn't block-buffered in `docker logs`.
ENV PYTHONUNBUFFERED=1

# The locked versions from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /tmp/runner/
RUN uv export --project /tmp/runner --frozen --no-dev --group stub --no-emit-project \
        --output-file /tmp/runner/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/runner/requirements.txt

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install --system --no-cache --no-deps .
COPY models ./models
COPY configs ./configs

ENTRYPOINT ["video-runner"]
