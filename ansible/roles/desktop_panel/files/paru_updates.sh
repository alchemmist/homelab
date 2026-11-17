#!/usr/bin/env bash

echo "0"

while true; do
    sleep 60
    count=$(paru -Qu | wc -l) || true
    echo "${count}"
done
