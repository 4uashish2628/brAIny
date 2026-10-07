#!/bin/sh
# Keeps the collector alive: restarts it a second after it exits.
while true; do
  python3 /opt/svc/collector.py
  sleep 1
done
