#!/usr/bin/env python3
"""
Fix Summary Sending - LetterMonstr.

This script addresses issues with unsent summaries by checking summary generation
and delivery configurations, and providing options to fix or resend summaries.
"""

import os
import sys
import yaml
import logging
from datetime import datetime
import sqlite3
import traceback

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('data', 'fix_summary_sending.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """Load configuration from YAML file."""
    config_path = os.path.join('config', 'config.yaml')
    
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def get_unsent_summaries():
    """Get all unsent summaries from the database."""
    db_path = os.path.join('data', 'lettermonstr.db')
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, summary_type, creation_date, summary_text, sent, sent_date 
            FROM summaries 
            WHERE sent = 0
            ORDER BY id DESC
        """)
        
        summaries = cursor.fetchall()
        conn.close()
        
        return summaries
    except Exception as e:
        logger.error(f"Error getting unsent summaries: {e}")
        return []

def update_summary_sent_status(summary_id, sent=True):
    """Update a summary's sent status in the database."""
    db_path = os.path.join('data', 'lettermonstr.db')
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE summaries
            SET sent = ?, sent_date = ?
            WHERE id = ?
        """, (1 if sent else 0, datetime.now().isoformat() if sent else None, summary_id))
        
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        logger.error(f"Error updating summary {summary_id}: {e}")
        return False

def check_scheduled_sending_config():
    """Check the configuration for scheduled summary sending."""
    config = load_config()
    
    print("\nChecking scheduled sending configuration...")
    print(f"Summary frequency: {config['summary'].get('frequency', 'Not set')}")
    print(f"Delivery time: {config['summary'].get('delivery_time', 'Not set')}")
    
    # Validate email configuration
    print("\nEmail sending configuration:")
    print(f"SMTP server: {config['summary'].get('smtp_server', 'Not set')}")
    print(f"SMTP port: {config['summary'].get('smtp_port', 'Not set')}")
    print(f"Sender email: {config['summary'].get('sender_email', 'Not set')}")
    print(f"Recipient email: {config['summary'].get('recipient_email', 'Not set')}")
    
    # Check if password is set (don't print it)
    email_password = config['email'].get('password', '')
    if email_password:
        print("Email password: Set")
    else:
        print("Email password: Not set (this will prevent sending)")
    
    # Make configuration recommendations
    issues = []
    
    if config['summary'].get('smtp_server') != 'smtp.gmail.com':
        issues.append("SMTP server should be 'smtp.gmail.com' for Gmail")
    
    if config['summary'].get('smtp_port') != 587:
        issues.append("SMTP port should be 587 for Gmail with TLS")
    
    if not config['summary'].get('recipient_email'):
        issues.append("Recipient email is not set")
    
    if not email_password:
        issues.append("Email password is not set")
    
    return issues

def test_email_connection():
    """Test the SMTP connection."""
    config = load_config()
    
    try:
        import smtplib
        import ssl
        
        smtp_server = config['summary']['smtp_server']
        smtp_port = config['summary']['smtp_port']
        sender_email = config['summary']['sender_email']
        password = config['email']['password']
        
        print(f"\nTesting connection to {smtp_server}:{smtp_port}...")
        
        context = ssl.create_default_context()
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender_email, password)
            
            print("SMTP connection successful!")
            return True
    except Exception as e:
        print(f"SMTP connection failed: {str(e)}")
        logger.error(f"SMTP connection error: {traceback.format_exc()}")
        return False

def fix_unsent_summaries():
    """Fix unsent summaries by marking them as sent or attempting to resend them."""
    print("\nLetterMonstr - Fix Summary Sending")
    print("================================\n")
    
    # Check configuration
    issues = check_scheduled_sending_config()
    
    if issues:
        print("\nConfiguration issues found:")
        for i, issue in enumerate(issues):
            print(f"{i+1}. {issue}")
    else:
        print("\nConfiguration appears to be correct.")
    
    # Test email connection
    connection_ok = test_email_connection()
    
    if not connection_ok:
        print("\nEmail connection failed. Please check your email credentials.")
        print("For Gmail, make sure you're using an App Password instead of your regular password.")
        print("You can generate an App Password at: https://myaccount.google.com/apppasswords")
        
        fix_config = input("\nWould you like to update your email password? (y/n): ")
        if fix_config.lower() == 'y':
            new_password = input("Enter your new App Password: ")
            config = load_config()
            config['email']['password'] = new_password
            
            with open(os.path.join('config', 'config.yaml'), 'w') as file:
                yaml.dump(config, file)
            
            print("Password updated. Let's test the connection again.")
            connection_ok = test_email_connection()
    
    # Get unsent summaries
    summaries = get_unsent_summaries()
    
    if not summaries:
        print("\nNo unsent summaries found in the database.")
        if connection_ok:
            print("\nYour configuration seems correct and there are no pending summaries.")
            print("The system should send new summaries automatically when they are generated.")
            print("To generate a new summary, you can run: python send_summary_now.py")
        return
    
    print(f"\nFound {len(summaries)} unsent summaries:")
    
    for i, summary in enumerate(summaries):
        created = summary['creation_date']
        summary_type = summary['summary_type']
        summary_id = summary['id']
        
        print(f"{i+1}. ID: {summary_id}, Type: {summary_type}, Created: {created}")
    
    if connection_ok:
        action = input("\nWould you like to attempt to (r)esend these summaries or just (m)ark them as sent? (r/m): ")
        
        if action.lower() == 'r':
            # Import components for sending
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from src.mail_handling.sender import EmailSender
            
            # Initialize email sender
            config = load_config()
            email_sender = EmailSender(config['summary'])
            
            for summary in summaries:
                summary_id = summary['id']
                summary_text = summary['summary_text']
                
                print(f"\nAttempting to send summary {summary_id}...")
                result = email_sender.send_summary(summary_text, summary_id)
                
                if result:
                    print(f"Summary {summary_id} sent successfully!")
                else:
                    print(f"Failed to send summary {summary_id}. See log for details.")
                    mark_anyway = input("Mark as sent anyway? (y/n): ")
                    if mark_anyway.lower() == 'y':
                        update_summary_sent_status(summary_id)
                        print(f"Summary {summary_id} marked as sent.")
        else:
            # Just mark as sent
            for summary in summaries:
                update_summary_sent_status(summary['id'])
                print(f"Summary {summary['id']} marked as sent.")
            
            print("\nAll summaries marked as sent. The scheduler should now work correctly.")
    else:
        print("\nEmail connection failed. Unable to resend summaries.")
        
        mark_as_sent = input("Would you like to mark these summaries as sent anyway? (y/n): ")
        if mark_as_sent.lower() == 'y':
            for summary in summaries:
                update_summary_sent_status(summary['id'])
            print("All summaries marked as sent.")
    
    print("\nTo monitor future summary sending, check:")
    print("1. data/lettermonstr_periodic_runner.log for scheduled sending logs")
    print("2. Run debug_summaries.py if you suspect issues")
    print("3. Run ./status_lettermonstr.sh to check overall system status")

if __name__ == "__main__":
    fix_unsent_summaries() 