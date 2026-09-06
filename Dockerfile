FROM python:3.12-slim

RUN sed -i \
    -e 's|http://deb.debian.org/debian-security|https://mirrors.ustc.edu.cn/debian-security|g' \
    -e 's|http://deb.debian.org/debian|https://mirrors.ustc.edu.cn/debian|g' \
    /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        ffmpeg \
        libportaudio2 \
        dnsutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY miair.py ./
COPY miair/ ./miair/
ARG PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple"
RUN pip install --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    . --root-user-action=ignore

# Verify the installed wheel contains the complete production console. Run
# away from /app so the source tree cannot accidentally mask package defects.
RUN cd /tmp && python -c "from importlib.resources import files; root = files('miair.web').joinpath('static'); html = root.joinpath('index.html').read_text(encoding='utf-8'); assert html.lstrip().lower().startswith('<!doctype html>'); assert all(root.joinpath(name).is_file() for name in ('console.css', 'console.js', 'castfabric-mark.svg', 'github-mark.svg', 'THIRD_PARTY_NOTICES.md'))"

COPY config-example.json .env.example ./
RUN mkdir -p /app/conf

ARG BUILD_DATE=""
ARG VCS_REF=""
LABEL org.opencontainers.image.title="CastFabric" \
      org.opencontainers.image.description="Open-source multi-protocol casting fabric for LAN audio devices" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="https://github.com/DjangoAILab/CastFabric"

EXPOSE 8200/tcp 8300/tcp 8899/tcp 5353/udp 56666/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/api/status', timeout=3)" || exit 1

ENTRYPOINT ["/bin/sh", "-c", "if [ ! -f /app/conf/config.json ]; then cp /app/config-example.json /app/conf/config.json; fi && if [ ! -f /app/conf/.env ]; then cp /app/.env.example /app/conf/.env; fi && exec castfabric --conf-path /app/conf"]
