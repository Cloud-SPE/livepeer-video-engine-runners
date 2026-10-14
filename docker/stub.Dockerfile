# Runner + CPU stub engine: exercises the whole Livepeer path without a GPU.
FROM python:3.12-slim

# Flush stdout/stderr immediately so output isn't block-buffered in `docker logs`.
ENV PYTHONUNBUFFERED=1

# The locked versions from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /tmp/runner/
RUN uv export --project /tmp/runner --frozen --no-dev --no-emit-project \
        --output-file /tmp/runner/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/runner/requirements.txt

WORKDIR /app
COPY engines.py runner.py stub_engine.py ./
COPY models ./models
COPY configs ./configs

ENTRYPOINT ["python", "runner.py"]
