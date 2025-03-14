#!/bin/bash
# LetterMonstr Runner Script
# This script runs LetterMonstr as a background process

# Configuration
LOG_FILE="data/lettermonstr_runner.log"
PERIODIC_LOG_FILE="data/lettermonstr_periodic_runner.log"
PID_FILE="data/lettermonstr.pid"
PERIODIC_PID_FILE="data/lettermonstr_periodic.pid"

# Create data directory if it doesn't exist
mkdir -p data

# Ensure we're in the project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if the virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Check if configuration exists
if [ ! -f "config/config.yaml" ]; then
    echo "Configuration file not found. Running setup script..."
    python3 setup_config.py
    
    # If setup failed, exit
    if [ $? -ne 0 ]; then
        echo "Configuration setup failed. Exiting."
        exit 1
    fi
fi

# Run database migration if needed
echo "Running database migration..."
python3 src/db_migrate.py

# Check if periodic fetching is enabled in the config
PERIODIC_FETCH=$(python3 -c "
import yaml
try:
    with open('config/config.yaml', 'r') as f:
        config = yaml.safe_load(f)
        print(config.get('email', {}).get('periodic_fetch', False))
except Exception as e:
    print('False')
")

# Check if either process is already running
check_process() {
    local pid_file=$1
    local process_name=$2
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p $PID > /dev/null; then
            echo "$process_name is already running with PID $PID"
            echo "To stop it, run: ./stop_lettermonstr.sh"
            return 1
        else
            echo "Stale PID file found for $process_name. Previous instance may have crashed."
            rm "$pid_file"
            return 0
        fi
    fi
    return 0
}

# Start a process in the background
start_process() {
    local command=$1
    local log_file=$2
    local pid_file=$3
    local process_name=$4
    
    echo "Starting $process_name..."
    
    # First, create a diagnostic script to check the Python environment
    cat > python_diagnostic.py << 'EOL'
#!/usr/bin/env python3
import sys
import os

print("=== Python Environment Diagnostic ===")
print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")

# Check if we can import email.header
try:
    import email.header
    print("✓ Successfully imported email.header")
except ImportError as e:
    print(f"✗ FAILED to import email.header: {e}")
    
    # Try to find the email module location
    import importlib.util
    spec = importlib.util.find_spec("email")
    if spec:
        print(f"email module location: {spec.origin}")
    else:
        print("email module not found!")
    
    # Try to find pythons standard library location
    import sysconfig
    stdlib_path = sysconfig.get_path('stdlib')
    print(f"Standard library path: {stdlib_path}")
    
    email_dir = os.path.join(stdlib_path, "email")
    if os.path.exists(email_dir):
        print(f"email directory exists at: {email_dir}")
        header_file = os.path.join(email_dir, "header.py")
        if os.path.exists(header_file):
            print(f"header.py exists at: {header_file}")
        else:
            print(f"header.py DOES NOT exist at: {header_file}")
    else:
        print(f"email directory DOES NOT exist at: {email_dir}")

print("=== End Diagnostic ===\n")
EOL

    chmod +x python_diagnostic.py
    
    # Run the diagnostic script with the same Python that will run the application
    echo "Running Python diagnostic check..."
    python3 python_diagnostic.py >> "$log_file" 2>&1
    
    # Export PYTHONPATH to ensure Python can find all modules
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
    
    # Run the actual command
    nohup $command > "$log_file" 2>&1 &
    PID=$!
    
    # Store the PID
    echo $PID > "$pid_file"
    echo "$process_name started with PID $PID"
    echo "Logs are available at $log_file"
}

# Test for email.header module
echo "Testing Python environment..."
if python3 -c "import email.header; print('✓ email.header module found!')" 2>/dev/null; then
    echo "Python environment looks good."
else
    echo "WARNING: email.header module not found in Python environment."
    echo "This could cause issues with email processing."
    echo "Trying to repair Python environment..."
    
    # Try to reinstall the dependencies
    pip install -r requirements.txt
    
    # Check Python version and configuration
    echo "Python version: $(python3 --version)"
    echo "Python executable: $(which python3)"
    echo "PYTHONPATH: $PYTHONPATH"
fi

# Main execution
if [ "$PERIODIC_FETCH" = "True" ]; then
    echo "Periodic fetching mode is enabled in config."
    
    # Check if periodic process is already running
    check_process "$PERIODIC_PID_FILE" "LetterMonstr Periodic Fetcher" || exit 0
    
    # Start the periodic runner
    start_process "python3 src/periodic_runner.py" "$PERIODIC_LOG_FILE" "$PERIODIC_PID_FILE" "LetterMonstr Periodic Fetcher"
    
    echo "LetterMonstr is running in periodic fetching mode."
    echo "The system will periodically fetch and process emails throughout the day."
    echo "Summaries will be generated and sent at the scheduled delivery time."
    echo "To check status, run: ./status_lettermonstr.sh"
    echo "To stop, run: ./stop_lettermonstr.sh"
else
    echo "Running in traditional mode (periodic fetching not enabled in config)."
    
    # Check if traditional process is already running
    check_process "$PID_FILE" "LetterMonstr" || exit 0
    
    # Start LetterMonstr in the background (traditional mode)
    start_process "python3 src/main.py" "$LOG_FILE" "$PID_FILE" "LetterMonstr"
    
    echo "LetterMonstr started in traditional mode."
    echo "To check status, run: ./status_lettermonstr.sh"
    echo "To stop, run: ./stop_lettermonstr.sh"
fi 