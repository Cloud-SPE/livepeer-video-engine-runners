# Runner + LightX2V. The base image carries LightX2V's CUDA dependencies but not
# LightX2V itself, so it is cloned at a pinned commit and run from source.
# Pick a base tag for your GPU and driver from https://hub.docker.com/r/lightx2v/lightx2v/tags
# (the cu130 builds target Blackwell / RTX 50; cu128 also covers Ada / RTX 40).
ARG LIGHTX2V_IMAGE=lightx2v/lightx2v:26011201-cu128
FROM ${LIGHTX2V_IMAGE}

ENV PYTHONUNBUFFERED=1

ARG LIGHTX2V_COMMIT=8e86555809efd20138d3a4e1f937ee306cdf0ee0
RUN git clone https://github.com/ModelTC/LightX2V.git /opt/lightx2v \
    && git -C /opt/lightx2v checkout ${LIGHTX2V_COMMIT}

# The runner gets its own Python 3.12 environment so its packages never touch
# the engine's torch stack. `python` on PATH stays the engine's interpreter.
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
