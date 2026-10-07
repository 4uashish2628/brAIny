FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system user.name "Dev" && git config --system user.email "dev@example.com"
COPY make_repo.sh /tmp/make_repo.sh
RUN sh /tmp/make_repo.sh && rm /tmp/make_repo.sh
CMD ["sleep", "infinity"]
