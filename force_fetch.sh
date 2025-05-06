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

# Create a temporary Python script that properly imports paths and modules
cat > temp_force_fetch.py << 'EOF'
#!/usr/bin/env python3
import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("force_fetch")

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

try:
    logger.info("Importing force_process_all_emails function...")
    from src.fetch_process import force_process_all_emails
    
    logger.info("Starting force fetch and process operation...")
    result = force_process_all_emails()
    
    if result:
        logger.info("Force fetch and process completed successfully!")
    else:
        logger.warning("Force fetch and process completed with warnings - check logs for details")
        
except Exception as e:
    logger.error(f"Error during force fetch and process: {e}", exc_info=True)
    sys.exit(1)
EOF

# Execute the temporary Python script
python3 temp_force_fetch.py
RESULT=$?

# Clean up the temporary script
rm temp_force_fetch.py

# Check if the script ran successfully
if [ $RESULT -eq 0 ]; then
    echo ""
    echo -e "${GREEN}Fetch and process completed. Check the database for results.${NC}"
else
    echo ""
    echo -e "${RED}Force fetch and process encountered errors. Check the logs for details.${NC}"
fi

echo ""
echo "To check the status and see how many emails were processed, run:"
echo "./status_lettermonstr.sh"

# Make the script executable
chmod +x force_fetch.sh 