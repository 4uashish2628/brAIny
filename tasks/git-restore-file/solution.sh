#!/bin/sh
set -e
cd /app/repo
deleted_in=$(git log --diff-filter=D --format=%H -1 -- pricing.csv)
git checkout "$deleted_in^" -- pricing.csv
git commit -q -m "restore pricing.csv"
