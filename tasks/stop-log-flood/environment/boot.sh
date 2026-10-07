#!/bin/sh
mkdir -p /var/log/app
sh /opt/svc/run-collector.sh &
python3 /opt/svc/heartbeat.py &
exec sleep infinity
