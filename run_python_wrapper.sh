#!/bin/bash
# Python wrapper script to ensure proper environment setup

# Activate virtual environment
source venv/bin/activate

# Print environment information for debugging
echo "=== Python Environment ===" >> "$2"
echo "Python: $(which python3)" >> "$2"
echo "Python Version: $(python3 --version 2>&1)" >> "$2"
echo "PYTHONPATH before: $PYTHONPATH" >> "$2"

# Get Python's standard library path
PYTHON_STDLIB=$(python3 -c "import sys; print(next((p for p in sys.path if 'python3' in p and 'site-packages' not in p), ''))")
echo "Python stdlib path: $PYTHON_STDLIB" >> "$2"

# Set PYTHONPATH to include the standard library first, then the project
if [ -n "$PYTHON_STDLIB" ]; then
    export PYTHONPATH="$PYTHON_STDLIB:$PYTHONPATH"
    echo "Added stdlib to PYTHONPATH" >> "$2"
fi

echo "PYTHONPATH after: $PYTHONPATH" >> "$2"
echo "===================" >> "$2"

# Run the actual Python script
exec python3 "$1" 