# Publisher image with python + build tools (use only if you want a hermetic publisher)
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates build-essential curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /work

# Publisher deps only
RUN pip install --no-cache-dir httpx tqdm

# If you have a wheel or shared lib for indexd_ffi, copy and install here:
# COPY wheels/indexd_ffi-*.whl /tmp/
# RUN pip install --no-cache-dir /tmp/indexd_ffi-*.whl

COPY publish_static.py /work/publish_static.py

CMD ["python", "publish_static.py"]
