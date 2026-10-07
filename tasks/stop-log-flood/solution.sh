#!/bin/sh
# Stop the supervisor loop first, or it restarts the collector.
pkill -f run-collector.sh
pkill -f collector.py
sleep 1
rm -f /var/log/app/collector.log
