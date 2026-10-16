# Engine only. The CPU runner is deployed independently.
# Upstream's CUDA 13.0 image with RTX 5090 fixes, pinned by digest.
ARG LIGHTX2V_IMAGE=lightx2v/lightx2v@sha256:fdfebaded08f8d68f1ea86e19d3f8804206479a82076ef12dba414f58a452761
FROM ${LIGHTX2V_IMAGE}
ARG LIGHTX2V_COMMIT=8e86555809efd20138d3a4e1f937ee306cdf0ee0
RUN git init /opt/lightx2v \
    && git -C /opt/lightx2v remote add origin https://github.com/ModelTC/LightX2V.git \
    && git -C /opt/lightx2v fetch --depth 1 origin ${LIGHTX2V_COMMIT} \
    && git -C /opt/lightx2v checkout --detach FETCH_HEAD \
    && rm -rf /opt/lightx2v/.git
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/opt/lightx2v HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /app
COPY configs/lightx2v ./configs/lightx2v
ENTRYPOINT ["python3", "-m", "lightx2v.server"]
