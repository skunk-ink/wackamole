###
### Stage 1: Build the indexd_ffi Python wheel with maturin
###
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE} AS sdk-build

# You can pin to a specific tag/commit if you like (e.g., v0.2.2 or a SHA)
ARG INDEXD_SDK_REF=master

WORKDIR /src

# Build prerequisites (Rust toolchain + essentials for building the wheel)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      git \
      build-essential \
      python3-pip \
 && rm -rf /var/lib/apt/lists/*

# Install Rust (minimal profile)
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

# Fetch the SDK sources
RUN git clone --depth 1 --branch ${INDEXD_SDK_REF} https://github.com/SiaFoundation/sia-sdk-rs.git /src

# Build the Python wheel for indexd_ffi
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir maturin

WORKDIR /src/indexd_ffi
RUN maturin build --release -i python3.12

# Show where the wheel landed, then slim down the build artifacts a bit
RUN ls -l /src/target/wheels \
 && rm -fr /src/target/debug

###
### Stage 2: Runtime image
###
FROM ${PYTHON_IMAGE} AS app
WORKDIR /app

# System dependencies for python-magic and TLS
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libmagic1 \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python deps (expects a local requirements.txt in build context)
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r /tmp/requirements.txt

# Install the built indexd_ffi wheel from the builder stage (correct path)
COPY --from=sdk-build /src/target/wheels/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
 && rm -f /tmp/*.whl

# App code
COPY gateway.py /app/gateway.py

ENV PYTHONUNBUFFERED=1

# Runtime defaults; /data is where you'll mount manifest.json
VOLUME ["/data"]
EXPOSE 8787

# By default look for the manifest under /data, bind on 0.0.0.0
CMD ["python", "-u", "/app/gateway.py", "--host", "0.0.0.0", "--port", "8787", "--manifest", "/data/manifest.json"]