#!/usr/bin/env python3
"""
Send pending summaries script for LetterMonstr.

This script finds unsent summaries in the database and sends them immediately.

Usage:
    python send_pending_summaries.py           # Interactive mode
    python send_pending_summaries.py all       # Send all pending summaries
    python send_pending_summaries.py <id>      # Send summary with specific ID
"""

import os
import sys
import logging
from datetime import datetime

# Set up the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("\nWarning: python-dotenv module not found.")
    print("If you have environment variables in a .env file, they won't be loaded.")
    print("Install with: pip install python-dotenv\n")

# Load config
try:
    import yaml
    config_path = os.path.join('config', 'config.yaml')
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
except ImportError:
    print("\nError: PyYAML module not found. Please install it with:")
    print("  pip install pyyaml")
    sys.exit(1)
except FileNotFoundError:
    print(f"\nError: Config file not found at {config_path}")
    sys.exit(1)

# Import necessary components
try:
    from src.database.models import get_session, Summary
    from src.mail_handling.sender import EmailSender
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    print("Please ensure all dependencies are installed.")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'send_pending_summaries.log'))
    ]
)
logger = logging.getLogger(__name__)

def send_pending_summaries(choice=None):
    """Find and send any pending summaries."""
    print("\nLetterMonstr - Sending Pending Summaries")
    print("=====================================")
    
    try:
        # Initialize the email sender
        email_sender = EmailSender(config['summary'])
        
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Query unsent summaries
            unsent_summaries = session.query(Summary).filter_by(sent=False).order_by(Summary.id.desc()).all()
            
            if not unsent_summaries:
                print("\nNo unsent summaries found in the database.")
                return
            
            print(f"\nFound {len(unsent_summaries)} unsent summaries.")
            
            # If a specific choice was provided via command line
            if choice is not None:
                if choice.lower() == 'all':
                    # Send all summaries
                    print("\nSending all unsent summaries...")
                    for summary in unsent_summaries:
                        print(f"\nSending summary ID: {summary.id}...")
                        result = email_sender.send_summary(summary.summary_text, summary.id)
                        if result:
                            print(f"Successfully sent summary ID: {summary.id}")
                        else:
                            print(f"Failed to send summary ID: {summary.id}")
                    return
                elif choice.isdigit():
                    # Send a specific summary by ID
                    summary_id = int(choice)
                    summary = next((s for s in unsent_summaries if s.id == summary_id), None)
                    
                    if not summary:
                        print(f"\nNo unsent summary found with ID: {summary_id}")
                        return
                    
                    print(f"\nSending summary ID: {summary.id}...")
                    result = email_sender.send_summary(summary.summary_text, summary.id)
                    if result:
                        print(f"Successfully sent summary ID: {summary.id}")
                    else:
                        print(f"Failed to send summary ID: {summary.id}")
                    return
            
            # Interactive mode
            print("\nAvailable summaries:")
            for i, summary in enumerate(unsent_summaries):
                summary_type = summary.summary_type
                creation_date = summary.creation_date.strftime('%Y-%m-%d %H:%M')
                print(f"{i+1}. ID: {summary.id} - {summary_type} summary created on {creation_date}")
            
            choice = input("\nEnter the number of the summary to send (or 'a' for all): ")
            
            if choice.lower() == 'a':
                # Send all summaries
                for summary in unsent_summaries:
                    print(f"\nSending summary ID: {summary.id}...")
                    result = email_sender.send_summary(summary.summary_text, summary.id)
                    if result:
                        print(f"Successfully sent summary ID: {summary.id}")
                    else:
                        print(f"Failed to send summary ID: {summary.id}")
            elif choice.isdigit() and 1 <= int(choice) <= len(unsent_summaries):
                # Send the selected summary
                idx = int(choice) - 1
                summary = unsent_summaries[idx]
                print(f"\nSending summary ID: {summary.id}...")
                result = email_sender.send_summary(summary.summary_text, summary.id)
                if result:
                    print(f"Successfully sent summary ID: {summary.id}")
                else:
                    print(f"Failed to send summary ID: {summary.id}")
            else:
                print("Invalid choice. No summaries sent.")
        
        except Exception as e:
            logger.error(f"Error sending pending summaries: {e}", exc_info=True)
            print(f"\nError: {str(e)}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error initializing components: {e}", exc_info=True)
        print(f"\nError: {str(e)}")
        
if __name__ == "__main__":
    # Check if a command line argument was provided
    if len(sys.argv) > 1:
        send_pending_summaries(sys.argv[1])
    else:
        send_pending_summaries() 