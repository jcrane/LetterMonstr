#!/usr/bin/env python3
"""
Debug Summaries - LetterMonstr.

This script checks for unsent summaries and attempts to resend them with detailed error logging.
"""

import os
import sys
import logging
import yaml
import traceback
from datetime import datetime

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import components
from src.database.models import get_session, Summary
from src.mail_handling.sender import EmailSender

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG level for maximum verbosity
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(current_dir, 'data', 'debug_summaries.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """Load configuration from YAML file."""
    config_path = os.path.join(current_dir, 'config', 'config.yaml')
    
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def debug_smtp_connection(config):
    """Test SMTP connection with detailed logging."""
    import smtplib
    import ssl
    
    logger.info("Testing SMTP connection...")
    logger.info(f"SMTP Server: {config['summary']['smtp_server']}")
    logger.info(f"SMTP Port: {config['summary']['smtp_port']}")
    logger.info(f"Sender Email: {config['summary']['sender_email']}")
    
    # Create a secure SSL context
    context = ssl.create_default_context()
    
    try:
        logger.info("Attempting to connect to SMTP server...")
        with smtplib.SMTP(config['summary']['smtp_server'], config['summary']['smtp_port']) as server:
            server.set_debuglevel(2)  # Enable detailed debug output
            logger.info("Starting TLS...")
            server.starttls(context=context)
            logger.info("Logging in...")
            server.login(config['summary']['sender_email'], config['email']['password'])
            logger.info("SMTP login successful!")
            return True
    except Exception as e:
        logger.error(f"SMTP connection error: {str(e)}")
        logger.error(f"Full stack trace: {traceback.format_exc()}")
        return False

def check_and_debug_unsent_summaries():
    """Check for unsent summaries and attempt to debug sending issues."""
    
    print("\nLetterMonstr - Debug Summaries")
    print("==============================\n")
    
    # Load configuration
    config = load_config()
    
    # Get database session
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    
    try:
        # Get all unsent summaries
        unsent_summaries = session.query(Summary).filter_by(sent=False).all()
        
        if not unsent_summaries:
            print("No unsent summaries found in the database.")
            
            # Check configuration
            print("\nVerifying email configuration...")
            if debug_smtp_connection(config):
                print("Email configuration appears correct.")
                print("\nScheduled sending should work with the next new content.")
            return
        
        print(f"Found {len(unsent_summaries)} unsent summaries.\n")
        
        # First, test the SMTP connection
        print("\nTesting SMTP connection...")
        smtp_ok = debug_smtp_connection(config)
        
        if not smtp_ok:
            print("\nSMTP connection failed. Please check your email credentials and server settings.")
            print("Common issues:")
            print("  1. Gmail password: Make sure you're using an App Password, not your regular password")
            print("  2. Gmail security: Check if 'Less secure app access' is enabled or use App Passwords")
            print("  3. Connection: Verify your internet connection and that gmail.com is accessible")
            return
        
        # Initialize email sender
        email_sender = EmailSender(config['summary'])
        
        # Try to send each unsent summary
        for i, summary in enumerate(unsent_summaries):
            print(f"\nAttempting to send summary #{summary.id} (created: {summary.creation_date})...")
            
            try:
                # Get the summary text
                summary_text = summary.summary_text
                
                # Only output the first few chars for privacy
                if summary_text:
                    print(f"Summary preview: {summary_text[:50]}...")
                else:
                    print("Warning: Empty summary text")
                
                # Attempt to send
                result = email_sender.send_summary(summary_text, summary.id)
                
                if result:
                    print(f"Summary #{summary.id} sent successfully!")
                    
                    # Update database
                    summary.sent = True
                    summary.sent_date = datetime.now()
                    session.commit()
                else:
                    print(f"Failed to send summary #{summary.id}")
            except Exception as e:
                print(f"Error sending summary #{summary.id}: {str(e)}")
                logger.error(f"Error sending summary #{summary.id}: {str(e)}")
                logger.error(traceback.format_exc())
        
        print("\nDebug Summary:")
        print(f"  - Found {len(unsent_summaries)} unsent summaries")
        sent_count = session.query(Summary).filter_by(sent=True).count()
        print(f"  - {sent_count} summaries have been sent successfully")
        
        print("\nCheck the debug_summaries.log file for detailed error information.")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        logger.error(f"Error in debug script: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        session.close()

if __name__ == "__main__":
    check_and_debug_unsent_summaries() 