#!/usr/bin/env python3
"""
LetterMonstr Gmail connection test

A standalone script to test Gmail connection without SQLAlchemy dependencies.
"""

import os
import sys
import yaml
import logging
import imaplib
from datetime import datetime, timedelta

# Import standard library email modules with explicit imports
import email as email_lib
from email.header import decode_header

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """Load configuration from YAML file."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                             'config', 'config.yaml')
    
    # Check if config file exists
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found at {config_path}")
        print(f"\nError: Configuration file not found at {config_path}")
        print("\nPlease run the setup script first:")
        print("  python3 setup_config.py")
        sys.exit(1)
        
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def decode_header_value(header):
    """Decode email header."""
    try:
        decoded_header = decode_header(header)
        header_parts = []
        
        for value, charset in decoded_header:
            if isinstance(value, bytes):
                try:
                    if charset:
                        value = value.decode(charset)
                    else:
                        value = value.decode('utf-8', errors='replace')
                except:
                    value = value.decode('utf-8', errors='replace')
            header_parts.append(str(value))
        
        return " ".join(header_parts)
    except Exception as e:
        logger.error(f"Error decoding header: {e}")
        return header

def get_email_content(msg):
    """Extract content from email message parts."""
    content = {
        'text': '',
        'html': '',
        'attachments': []
    }
    
    if msg.is_multipart():
        # Iterate through email parts
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            try:
                # Get the content
                body = part.get_payload(decode=True)
                
                if body:
                    # Handle text parts
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        content['text'] += body.decode('utf-8', errors='replace')
                    
                    # Handle HTML parts
                    elif content_type == "text/html" and "attachment" not in content_disposition:
                        content['html'] += body.decode('utf-8', errors='replace')
                    
                    # Handle attachments
                    elif "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            content['attachments'].append({
                                'filename': filename,
                                'content_type': content_type,
                                'data': body
                            })
            except Exception as e:
                logger.error(f"Error processing email part: {e}", exc_info=True)
    else:
        # Handle non-multipart messages
        content_type = msg.get_content_type()
        body = msg.get_payload(decode=True)
        
        if body:
            if content_type == "text/plain":
                content['text'] = body.decode('utf-8', errors='replace')
            elif content_type == "text/html":
                content['html'] = body.decode('utf-8', errors='replace')
    
    return content

def connect_to_gmail(config):
    """Connect to Gmail IMAP server."""
    try:
        # Create an IMAP4 class with SSL
        mail = imaplib.IMAP4_SSL(config['imap_server'], config['imap_port'])
        
        # Login to the server
        mail.login(config['fetch_email'], config['password'])
        
        print(f"Successfully connected to Gmail as {config['fetch_email']}")
        return mail
    except Exception as e:
        logger.error(f"Failed to connect to email server: {e}")
        raise

def fetch_recent_emails(mail, config):
    """Fetch recent emails from Gmail."""
    all_emails = []
    
    # Only look at emails from the last few days
    lookback_days = config.get('initial_lookback_days', 3)
    since_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    
    # Process each folder
    for folder in config['folders']:
        print(f"\nChecking folder: {folder}")
        
        # Select the mailbox/folder
        status, folder_info = mail.select(folder)
        
        if status != 'OK':
            print(f"Unable to open folder {folder}: {folder_info}")
            continue
            
        # Get message count
        message_count = int(folder_info[0])
        print(f"Found {message_count} total messages in folder")
        
        # Search for emails within the lookback period
        status, messages = mail.search(None, f'(SINCE {since_date})')
        
        if status != 'OK':
            print(f"Failed to search folder {folder}: {messages}")
            continue
        
        # Get the list of email IDs
        email_ids = messages[0].split()
        
        if not email_ids:
            print(f"No emails found in folder {folder} since {since_date}")
            continue
        
        print(f"Found {len(email_ids)} emails from the last {lookback_days} days")
        
        # Only process the 5 most recent emails
        limit = min(5, len(email_ids))
        for i, e_id in enumerate(email_ids[-limit:]):
            print(f"\nFetching email {i+1}/{limit}...")
            
            # Fetch the email
            status, msg_data = mail.fetch(e_id, '(RFC822)')
            
            if status != 'OK':
                print(f"Failed to fetch email {e_id}: {msg_data}")
                continue
            
            # Parse the email message
            msg = email_lib.message_from_bytes(msg_data[0][1])
            
            # Extract basic info
            subject = decode_header_value(msg.get('Subject', ''))
            sender = decode_header_value(msg.get('From', ''))
            date_str = msg.get('Date', '')
            
            print(f"Subject: {subject}")
            print(f"From: {sender}")
            print(f"Date: {date_str}")
            
            # Extract message ID
            message_id = msg.get('Message-ID', '')
            
            # Get content summary
            content = get_email_content(msg)
            text_preview = content['text'][:150] + '...' if len(content['text']) > 150 else content['text']
            print(f"Content preview: {text_preview}")
            
            # Store the email
            all_emails.append({
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'date': date_str,
                'content': content
            })
    
    return all_emails

def main():
    """Main entry point for the script."""
    print("\nLetterMonstr Gmail Connection Test")
    print("----------------------------------")
    
    # Load configuration
    config = load_config()
    
    if 'email' not in config:
        print("Error: Email configuration not found in config file")
        sys.exit(1)
    
    try:
        # Connect to Gmail
        mail = connect_to_gmail(config['email'])
        
        # Fetch recent emails
        emails = fetch_recent_emails(mail, config['email'])
        
        # Close the connection
        mail.close()
        mail.logout()
        
        # Show summary
        print(f"\nSuccessfully fetched {len(emails)} recent emails")
        print("Gmail connection test completed successfully!")
        
    except Exception as e:
        print(f"\nError testing Gmail connection: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 