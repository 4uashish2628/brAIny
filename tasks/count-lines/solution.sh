#!/bin/sh
wc -l < /app/data.txt | tr -d ' ' > /app/answer.txt
