#!/bin/bash
# Setup script for UnityScraper Enhanced
# For Windows, save as setup.bat and replace first line with: @echo off

echo "================================"
echo "UnityScraper Enhanced - Setup"
echo "================================"
echo ""

# Check Python installation
echo "Checking Python installation..."
python --version
if [ $? -ne 0 ]; then
    echo "ERROR: Python not found. Please install Python 3.9 or higher."
    exit 1
fi

# Install requirements
echo ""
echo "Installing requirements..."
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install requirements."
    exit 1
fi

echo ""
echo "================================"
echo "Setup Complete!"
echo "================================"
echo ""
echo "Quick Start:"
echo "  CLI:  python main.py 555308C5"
echo "  GUI:  python GUI.py"
echo "  Test: python tests.py"
echo ""
echo "See README.md for full documentation."