#!/usr/bin/env python3
"""
Test IMAP connection and list emails in the inbox.
"""

import os
import sys
import yaml
import imaplib
import email
from datetime import datetime, timedelta
from email.header import decode_header

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def load_config():
    """Load configuration from config file."""
    config_path = os.path.join(project_root, 'config', 'config.yaml')
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    return config

def decode_header_text(header):
    """Decode email header."""
    if not header:
        return ""
    try:
        decoded_header = decode_header(header)
        header_parts = []
        
        for part, encoding in decoded_header:
            if isinstance(part, bytes):
                if encoding:
                    try:
                        header_parts.append(part.decode(encoding))
                    except UnicodeDecodeError:
                        header_parts.append(part.decode('utf-8', errors='ignore'))
                else:
                    header_parts.append(part.decode('utf-8', errors='ignore'))
            else:
                header_parts.append(part)
        
        return ' '.join(header_parts)
    except Exception as e:
        print(f"Error decoding header: {e}")
        return header

def test_imap_connection():
    """Test IMAP connection and list emails in the inbox."""
    config = load_config()
    email_config = config['email']
    
    email_address = email_config['fetch_email']
    password = email_config['password']
    imap_server = email_config['imap_server']
    imap_port = email_config['imap_port']
    folders = email_config['folders']
    
    print(f"Testing IMAP connection to {imap_server}:{imap_port} with email {email_address}")
    
    try:
        # Connect to the IMAP server
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        print("Successfully created IMAP4_SSL object")
        
        # Login to the server
        mail.login(email_address, password)
        print("Successfully logged in")
        
        # Process each folder
        for folder in folders:
            print(f"\nExamining folder: {folder}")
            
            # Select the mailbox/folder
            status, folder_info = mail.select(folder)
            if status != 'OK':
                print(f"Failed to select folder {folder}: {folder_info}")
                continue
                
            # Log how many messages are in the folder total
            message_count = int(folder_info[0])
            print(f"Folder {folder} contains {message_count} total messages")
            
            # Calculate lookback period (7 days)
            since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            print(f"Looking for emails since {since_date}")
            
            # Search for ALL emails within the lookback period
            status, all_messages = mail.search(None, f'(SINCE {since_date})')
            if status == 'OK':
                all_email_ids = all_messages[0].split()
                all_email_count = len(all_email_ids)
                print(f"Found {all_email_count} total emails in {folder} since {since_date}")
                
                # Show the subjects of the most recent 5 emails
                if all_email_count > 0:
                    print("\nMost recent emails:")
                    for i, e_id in enumerate(reversed(all_email_ids[:5])):
                        # Fetch the email
                        status, msg_data = mail.fetch(e_id, '(RFC822)')
                        if status == 'OK':
                            # Parse the email message
                            msg = email.message_from_bytes(msg_data[0][1])
                            
                            # Get email info
                            subject = decode_header_text(msg.get('Subject', 'No Subject'))
                            sender = decode_header_text(msg.get('From', 'Unknown'))
                            date_str = msg.get('Date', '')
                            
                            # Check if it's seen (read) or unseen (unread)
                            status, flags_data = mail.fetch(e_id, '(FLAGS)')
                            flags = flags_data[0].decode('utf-8')
                            is_read = "\\Seen" in flags
                            read_status = "READ" if is_read else "UNREAD"
                            
                            print(f"{i+1}. [{read_status}] From: {sender} | Subject: {subject} | Date: {date_str}")
                
            # Search specifically for unread emails
            status, unread_messages = mail.search(None, '(UNSEEN)')
            if status == 'OK':
                unread_email_count = len(unread_messages[0].split()) if unread_messages[0] else 0
                print(f"\nFound {unread_email_count} UNREAD emails in {folder}")
        
        # Close the connection
        mail.close()
        mail.logout()
        print("\nSuccessfully closed connection")
        
    except Exception as e:
        print(f"Error: {e}")
        raise

if __name__ == "__main__":
    test_imap_connection() 