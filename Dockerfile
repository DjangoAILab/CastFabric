FROM python:3.12-slim

LABEL maintainer="MiAir"
LABEL description="DLNA/AirPlay receiver for Xiaomi AI Speaker"

# 安装系统依赖
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

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    --index-url https://mirrors.aliyun.com/pypi/simple \
    . --root-user-action=ignore

# 这里明确把示例配置文件也拷贝进镜像的备用区
COPY config-example.json .env.example ./
COPY miair.py ./
COPY miair/ ./miair/

RUN mkdir -p /app/conf

EXPOSE 8200 8300

# 【核心修改】智能启动命令：
# 1. 检查 /app/conf/config.json 是否存在，不存在就复制一份示例文件过去
# 2. 检查 /app/conf/.env 是否存在，不存在也复制过去
# 3. 最后使用 exec 移交进程控制权并启动真正的 Python 服务
ENTRYPOINT ["/bin/sh", "-c", "if [ ! -f /app/conf/config.json ]; then cp /app/config-example.json /app/conf/config.json; fi && if [ ! -f /app/conf/.env ]; then cp /app/.env.example /app/conf/.env; fi && exec python miair.py --conf-path /app/conf"]
