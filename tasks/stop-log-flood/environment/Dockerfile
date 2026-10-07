FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends procps \
 && rm -rf /var/lib/apt/lists/*
COPY svc/ /opt/svc/
COPY boot.sh /usr/local/bin/boot.sh
RUN mkdir -p /var/log/app \
 && printf '2026-09-01 login admin\n2026-09-02 export report\n' > /var/log/app/audit.log
CMD ["sh", "/usr/local/bin/boot.sh"]
