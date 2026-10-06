#!/bin/sh
pkill -f metrics_exporter.py
sleep 1
nohup python3 /app/server.py > /tmp/server.log 2>&1 &
sleep 1
