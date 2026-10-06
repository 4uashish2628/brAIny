FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*
COPY app/ /app/
COPY legacy/ /opt/legacy/
COPY boot.sh /usr/local/bin/boot.sh
CMD ["sh", "/usr/local/bin/boot.sh"]
