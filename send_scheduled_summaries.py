#!/usr/bin/env python3
"""
Send Scheduled Summaries - LetterMonstr.

This script checks if it's time to send any pending summaries and sends them
according to the configured schedule. This can be run on system startup.
"""

import os
import sys
import time
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
        logging.FileHandler(os.path.join('data', 'send_scheduled_summaries.log'))
    ]
)
logger = logging.getLogger(__name__)

def should_send_summary():
    """Determine if it's time to send a summary based on configuration."""
    current_time = datetime.now()
    frequency = config['summary']['frequency']
    delivery_time_str = config['summary']['delivery_time']
    
    # Parse delivery time
    delivery_hour, delivery_minute = map(int, delivery_time_str.split(':'))
    
    # Check if we're at or past the delivery time
    time_check = (current_time.hour > delivery_hour) or \
                 (current_time.hour == delivery_hour and current_time.minute >= delivery_minute)
    
    # Check if it's the right day based on frequency
    if frequency == 'daily':
        return time_check
    elif frequency == 'weekly':
        delivery_day = config['summary']['weekly_day']
        return current_time.weekday() == delivery_day and time_check
    elif frequency == 'monthly':
        delivery_day = config['summary']['monthly_day']
        return current_time.day == delivery_day and time_check
    
    return False

def check_and_send_scheduled_summaries():
    """Check if it's time to send scheduled summaries and send them."""
    print("\nLetterMonstr - Scheduled Summary Sender")
    print("=======================================")
    
    try:
        # Only proceed if it's time to send summaries
        if not should_send_summary():
            print("It's not time to send summaries yet according to the schedule.")
            print(f"Current schedule: {config['summary']['frequency']} at {config['summary']['delivery_time']}")
            return
        
        # Initialize the email sender
        email_sender = EmailSender(config['summary'])
        
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Query unsent summaries
            unsent_summaries = session.query(Summary).filter_by(sent=False).order_by(Summary.id.desc()).all()
            
            if not unsent_summaries:
                print("No unsent summaries found in the database.")
                return
            
            print(f"Found {len(unsent_summaries)} unsent summaries.")
            
            # Get today's date (for logging)
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Process the most recent summary for today
            for summary in unsent_summaries:
                summary_date = summary.creation_date.strftime('%Y-%m-%d')
                
                # Skip if we already processed a summary for today
                print(f"Sending summary ID: {summary.id} created on {summary_date}...")
                
                result = email_sender.send_summary(summary.summary_text, summary.id)
                
                if result:
                    print(f"Successfully sent summary ID: {summary.id}")
                    # Only need to send the most recent one
                    break
                else:
                    print(f"Failed to send summary ID: {summary.id}")
            
        except Exception as e:
            logger.error(f"Error sending scheduled summaries: {e}", exc_info=True)
            print(f"Error: {str(e)}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error initializing components: {e}", exc_info=True)
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    check_and_send_scheduled_summaries() 