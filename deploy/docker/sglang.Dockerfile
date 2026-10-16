# Runner + SGLang Diffusion (`sglang serve`). The official image includes the
# diffusion dependencies; pin a release tag or digest instead of `latest`.
ARG SGLANG_IMAGE=lmsysorg/sglang:latest
FROM ${SGLANG_IMAGE}

ENV PYTHONUNBUFFERED=1

# The runner gets its own Python 3.12 environment so its packages never touch
# the engine's torch stack.
# Its dependencies are the locked versions from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock /tmp/runner/
RUN uv venv /opt/runner --python 3.12 \
    && uv export --project /tmp/runner --frozen --no-dev --no-emit-project \
        --output-file /tmp/runner/requirements.txt \
    && uv pip install --python /opt/runner/bin/python --no-cache \
        -r /tmp/runner/requirements.txt

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install --python /opt/runner/bin/python --no-cache --no-deps .
COPY models ./models
COPY configs ./configs

ENTRYPOINT ["/opt/runner/bin/video-runner"]
