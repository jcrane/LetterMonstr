#!/bin/bash
# Force fetch and process emails

# Define terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}LetterMonstr - Force Fetch Emails${NC}"
echo "====================================="
echo "This script will force fetch and process all emails."
echo ""

# Run test_imap.py to verify connection first
echo -e "${YELLOW}Step 1: Testing IMAP connection...${NC}"
echo ""
python3 utils/test_imap.py
if [ $? -ne 0 ]; then
    echo -e "${RED}IMAP connection test failed! Check your IMAP settings.${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2: Forcing fetch and process...${NC}"
echo ""

# Call the Python fetch script directly with force flag
python3 -c "
import os
import sys
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
from src.fetch_process import run_periodic_fetch, force_process_all_emails
print('Running force fetch and process...')
force_process_all_emails()
"

echo ""
echo -e "${GREEN}Fetch and process completed. Check the database for results.${NC}"
echo ""
echo "To check the status and see how many emails were processed, run:"
echo "./status_lettermonstr.sh"

# Make the script executable
chmod +x force_fetch.sh 