#!/bin/bash

battery=$(upower -e | grep BAT) || true
if [[ -n ${battery} ]]; then
    ratio=$(upower -i "${battery}" | awk '\
        /energy-full:/ {ef=$2}\
        /energy-full-design:/ {efd=$2}\
        END {print ef/efd}') || true
else
    ratio=$(upower -i | awk '\
        /energy-full:/ {ef=$2}\
        /energy-full-design:/ {efd=$2}\
        END {print ef/efd}') || true
fi
expr=$(printf '%s\n' "(1 - ${ratio}) * 100 + 0.5" | bc) || true
whole=$(printf '%s\n' "${expr}" | cut -d'.' -f1) || true
printf '%s\n' "${whole}"
