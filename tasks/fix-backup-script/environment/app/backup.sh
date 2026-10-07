#!/bin/sh
SRC=$1
DEST=$2
count=0
for f in $(ls $SRC/*.txt); do
  cp $f $DEST
  count=$((count+1))
done
echo "copied $count files"
