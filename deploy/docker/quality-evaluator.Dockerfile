# Optional, short-lived evaluator. Shared CUDA/PyTorch layers are already used by
# the pinned vLLM engine; no evaluator dependencies enter the serving images.
ARG EVALUATOR_BASE_IMAGE=vllm/vllm-omni@sha256:5cba1538c6f8ee81e8bea6708c24e68d7b2640f466a9fbf2ef15e68f2168b48b
FROM ${EVALUATOR_BASE_IMAGE}
ARG VBENCH_COMMIT=fd18b3d055cb0fc6f066ca90fe2c3c8cbb698490
RUN git init /opt/vbench \
    && git -C /opt/vbench remote add origin https://github.com/Vchitect/VBench.git \
    && git -C /opt/vbench fetch --depth 1 origin ${VBENCH_COMMIT} \
    && git -C /opt/vbench checkout --detach FETCH_HEAD \
    && python -m venv --system-site-packages /opt/quality-venv \
    && /opt/quality-venv/bin/pip install --no-cache-dir \
      openai-clip==1.0.1 decord==0.6.0 easydict==1.13 timm==1.0.12 pyiqa==0.1.16
# Upstream setup.py requires a visible GPU even when building metadata. Import
# its unmodified pinned source instead; verify the Git revision at evaluation.
ENV PYTHONPATH=/opt/vbench
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget unzip \
    && rm -rf /var/lib/apt/lists/*
COPY src/video_runners/tools/quality_vbench.py /app/quality_vbench.py
ENTRYPOINT ["/opt/quality-venv/bin/python", "/app/quality_vbench.py"]
