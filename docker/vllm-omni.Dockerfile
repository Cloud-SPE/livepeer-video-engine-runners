# Runner + vLLM-Omni (`vllm serve ... --omni`). The image has no default
# entrypoint of its own; pin the tag you have validated.
ARG VLLM_OMNI_IMAGE=vllm/vllm-omni:v0.26.0
FROM ${VLLM_OMNI_IMAGE}

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
COPY engines.py runner.py ./
COPY models ./models
COPY configs ./configs

ENTRYPOINT ["/opt/runner/bin/python", "runner.py"]
