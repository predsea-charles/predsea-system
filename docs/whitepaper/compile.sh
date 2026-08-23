#!/bin/bash

# PredSea Technical White Paper Compiler (Publication Grade v5)
# Generates publication-ready PDF via Typst and Python master builder

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Building PredSea White Paper PDF..."
python3 build_whitepaper_v5.py

echo "Build complete: PredSea_White_Paper.pdf"
