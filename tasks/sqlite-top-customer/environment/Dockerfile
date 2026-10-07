FROM python:3.12-slim
WORKDIR /app
COPY make_db.py /tmp/make_db.py
RUN python3 /tmp/make_db.py && rm /tmp/make_db.py
CMD ["sleep", "infinity"]
