"""
Email fetcher for LetterMonstr application.

This module handles connecting to Gmail via IMAP and fetching new emails.
"""

import imaplib
import logging
import os
import sys
from datetime import datetime, timedelta

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Reset sys.path to ensure standard library is first
sys_paths = [p for p in sys.path if p not in (current_dir, project_root)]
sys.path = sys_paths + [project_root, current_dir]

# Import standard library email modules with explicit imports
import email as email_lib
from email.header import decode_header

# Import database models
from src.database.models import get_session, ProcessedEmail

logger = logging.getLogger(__name__)

class EmailFetcher:
    """Fetches emails from a Gmail account via IMAP."""
    
    def __init__(self, config):
        """Initialize with email configuration."""
        self.email = config['fetch_email']
        self.password = config['password']
        self.server = config['imap_server']
        self.port = config['imap_port']
        self.folders = config['folders']
        self.lookback_days = config['initial_lookback_days']
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'lettermonstr.db')
    
    def connect(self):
        """Connect to the IMAP server."""
        try:
            # Create an IMAP4 class with SSL
            mail = imaplib.IMAP4_SSL(self.server, self.port)
            
            # Login to the server
            mail.login(self.email, self.password)
            
            return mail
        except Exception as e:
            logger.error(f"Failed to connect to email server: {e}")
            raise
    
    def fetch_new_emails(self):
        """Fetch unread emails from the configured folders."""
        mail = self.connect()
        session = get_session(self.db_path)
        
        all_emails = []
        processed_email_ids = []
        
        try:
            # Calculate the date for the lookback period
            since_date = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
            
            # Process each folder
            for folder in self.folders:
                # Select the mailbox/folder
                mail.select(folder)
                
                # Search for unread emails within the lookback period
                # Use UNSEEN flag to only get unread emails
                status, messages = mail.search(None, f'(UNSEEN SINCE {since_date})')
                
                if status != 'OK':
                    logger.warning(f"Failed to search folder {folder}: {messages}")
                    continue
                
                # Get the list of email IDs
                email_ids = messages[0].split()
                
                if not email_ids:
                    logger.info(f"No unread emails found in folder {folder} since {since_date}")
                    continue
                
                logger.info(f"Found {len(email_ids)} unread emails in folder {folder}")
                
                # Process each email
                for e_id in email_ids:
                    # Fetch the email
                    status, msg_data = mail.fetch(e_id, '(RFC822)')
                    
                    if status != 'OK':
                        logger.warning(f"Failed to fetch email {e_id}: {msg_data}")
                        continue
                    
                    # Parse the email message
                    msg = email_lib.message_from_bytes(msg_data[0][1])
                    
                    # Check if this email was already processed in our database
                    message_id = msg.get('Message-ID', '')
                    if self._is_processed(session, message_id):
                        logger.info(f"Skipping already processed email: {message_id}")
                        # Mark as read in Gmail since we've already processed it
                        mail.store(e_id, '+FLAGS', '\\Seen')
                        continue
                    
                    # Process the email
                    parsed_email = self._parse_email(msg)
                    
                    if parsed_email:
                        # Add to the list of emails to process
                        all_emails.append(parsed_email)
                        # Keep track of email IDs to mark as read later
                        processed_email_ids.append((e_id, parsed_email))
            
            # Close the connection
            mail.close()
            mail.logout()
            
            # Return the list of fetched emails
            logger.info(f"Successfully fetched {len(all_emails)} new unread emails for processing")
            return all_emails
            
        except Exception as e:
            logger.error(f"Error fetching emails: {e}", exc_info=True)
            raise
        finally:
            session.close()
    
    def fetch_raw_unread_emails(self):
        """Fetch ALL unread emails, ignoring database processed status.
        
        This method is similar to fetch_new_emails but it ignores the database check
        for processed emails. This is useful for forcing processing of emails that
        were incorrectly marked as processed.
        """
        mail = self.connect()
        
        all_emails = []
        
        try:
            # Calculate the date for the lookback period
            since_date = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
            
            # Process each folder
            for folder in self.folders:
                # Select the mailbox/folder
                mail.select(folder)
                
                # Search for unread emails within the lookback period
                # Use UNSEEN flag to only get unread emails
                status, messages = mail.search(None, f'(UNSEEN SINCE {since_date})')
                
                if status != 'OK':
                    logger.warning(f"Failed to search folder {folder}: {messages}")
                    continue
                
                # Get the list of email IDs
                email_ids = messages[0].split()
                
                if not email_ids:
                    logger.info(f"No unread emails found in folder {folder} since {since_date}")
                    continue
                
                logger.info(f"Found {len(email_ids)} unread emails in folder {folder}")
                
                # Process each email
                for e_id in email_ids:
                    # Fetch the email
                    status, msg_data = mail.fetch(e_id, '(RFC822)')
                    
                    if status != 'OK':
                        logger.warning(f"Failed to fetch email {e_id}: {msg_data}")
                        continue
                    
                    # Parse the email message
                    msg = email_lib.message_from_bytes(msg_data[0][1])
                    
                    # Process the email without checking the database
                    parsed_email = self._parse_email(msg)
                    
                    if parsed_email:
                        # Add to the list of emails to process
                        all_emails.append(parsed_email)
            
            # Close the connection
            mail.close()
            mail.logout()
            
            # Return the list of fetched emails
            logger.info(f"Successfully fetched {len(all_emails)} raw unread emails")
            return all_emails
            
        except Exception as e:
            logger.error(f"Error fetching raw emails: {e}", exc_info=True)
            raise
    
    def mark_emails_as_processed(self, processed_emails):
        """Mark emails as processed in both Gmail and the database."""
        if not processed_emails:
            return
            
        logger.info(f"Marking {len(processed_emails)} emails as read and processed")
        mail = self.connect()
        session = get_session(self.db_path)
        
        try:
            # Process each folder
            for folder in self.folders:
                mail.select(folder)
                
                # Mark each email as processed in database and read in Gmail
                for email in processed_emails:
                    # Mark as processed in database
                    self._mark_as_processed(session, email)
                    
                    # Search for the email in this folder by Message-ID
                    status, messages = mail.search(None, f'(HEADER Message-ID "{email["message_id"]}")')
                    if status != 'OK' or not messages[0]:
                        continue
                        
                    # Get email IDs and mark as read
                    email_ids = messages[0].split()
                    for e_id in email_ids:
                        mail.store(e_id, '+FLAGS', '\\Seen')
                        logger.debug(f"Marked email {email['subject']} as read in Gmail")
            
            # Close the connection
            mail.close()
            mail.logout()
            
        except Exception as e:
            logger.error(f"Error marking emails as processed: {e}", exc_info=True)
        finally:
            session.close()
    
    def _parse_email(self, msg):
        """Parse an email message into a dictionary of relevant fields."""
        try:
            # Extract subject
            subject = msg.get('Subject', '')
            if subject:
                subject = self._decode_header(subject)
            
            # Extract sender
            sender = msg.get('From', '')
            if sender:
                sender = self._decode_header(sender)
            
            # Extract date
            date_str = msg.get('Date', '')
            date = datetime.now()
            if date_str:
                try:
                    # Try parsing with email.utils
                    date_tuple = email_lib.utils.parsedate(date_str)
                    if date_tuple:
                        date = datetime(*date_tuple[:6])
                    else:
                        # Try with parsedate_to_datetime
                        date = email_lib.utils.parsedate_to_datetime(date_str)
                except:
                    logger.warning(f"Could not parse date: {date_str}")
            
            # Extract message ID
            message_id = msg.get('Message-ID', '')
            
            # Extract content
            content = self._get_email_content(msg)
            
            return {
                'subject': subject,
                'sender': sender,
                'date': date,
                'message_id': message_id,
                'content': content
            }
            
        except Exception as e:
            logger.error(f"Error parsing email: {e}", exc_info=True)
            return None
    
    def _decode_header(self, header):
        """Decode email header."""
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
            logger.error(f"Error decoding header: {e}", exc_info=True)
            return header
    
    def _get_email_content(self, msg):
        """Extract content from the email message."""
        content = {'html': '', 'text': ''}
        best_html_part = None
        best_text_part = None
        
        # For deep inspection of the email structure
        def inspect_part(part, depth=0, path=""):
            nonlocal best_html_part, best_text_part
            
            if depth > 10:  # Prevent infinite recursion
                return
                
            content_type = part.get_content_type()
            new_path = f"{path}/{content_type}" if path else content_type
            
            # Log part details for debugging
            if depth == 0:
                logger.debug(f"Root content type: {content_type}")
            
            if content_type.startswith('multipart/'):
                # Process multipart/* content recursively
                for idx, subpart in enumerate(part.get_payload()):
                    inspect_part(subpart, depth + 1, f"{new_path}[{idx}]")
            else:
                # Log leaf content parts
                disp = part.get('Content-Disposition', '')
                charset = part.get_content_charset()
                logger.debug(f"Part {new_path}: {content_type}, disposition: {disp}, charset: {charset}")
                
                # Process based on content type and disposition
                if 'attachment' not in disp:
                    if content_type == 'text/html':
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                try:
                                    decoded = payload.decode(charset or 'utf-8', errors='replace')
                                    # Update best HTML part if this one is larger
                                    if not best_html_part or len(decoded) > len(best_html_part):
                                        best_html_part = decoded
                                        logger.debug(f"Found HTML part, length: {len(decoded)} chars at {new_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to decode HTML with charset {charset}: {e}")
                        except Exception as e:
                            logger.warning(f"Error getting payload for HTML part: {e}")
                    
                    elif content_type == 'text/plain':
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                try:
                                    decoded = payload.decode(charset or 'utf-8', errors='replace')
                                    # Update best text part if this one is larger
                                    if not best_text_part or len(decoded) > len(best_text_part):
                                        best_text_part = decoded
                                        logger.debug(f"Found text part, length: {len(decoded)} chars at {new_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to decode text with charset {charset}: {e}")
                        except Exception as e:
                            logger.warning(f"Error getting payload for text part: {e}")
        
        # Start inspection at the root
        try:
            # First check if this is a Gmail forwarded message
            is_forwarded = False
            subject = msg.get('Subject', '')
            if subject and subject.startswith('Fwd:'):
                is_forwarded = True
                logger.debug(f"Processing forwarded message: {subject}")
            
            # Inspect the message structure
            inspect_part(msg)
            
            # Use the best parts we found
            if best_html_part:
                content['html'] = best_html_part
            
            if best_text_part:
                content['text'] = best_text_part
            
            # Log the lengths of what we found
            html_len = len(content['html'])
            text_len = len(content['text'])
            logger.debug(f"Extracted HTML content: {html_len} chars, text content: {text_len} chars")
            
            # For forwarded messages, try to extract the actual content from the HTML
            if is_forwarded and html_len > 0:
                from bs4 import BeautifulSoup
                
                try:
                    soup = BeautifulSoup(content['html'], 'html.parser')
                    
                    # Look for Gmail forwarded content markers
                    fw_marker = soup.find(string=lambda s: s and "---------- Forwarded message ---------" in s)
                    
                    if fw_marker:
                        logger.debug("Found forwarded message marker in HTML")
                        
                        # Try to find the actual forwarded content
                        parent = fw_marker.parent
                        if parent:
                            # Method 1: Try to find largest div after the marker
                            main_content_div = None
                            divs_after_marker = parent.find_next_siblings('div')
                            if divs_after_marker:
                                largest_div = max(divs_after_marker, key=lambda x: len(str(x)))
                                if len(str(largest_div)) > 200:  # Arbitrary size threshold
                                    main_content_div = largest_div
                                    logger.debug(f"Found main content div after marker, size: {len(str(main_content_div))}")
                            
                            # Method 2: Try to find a blockquote which often contains the forwarded content
                            if not main_content_div:
                                blockquotes = soup.find_all('blockquote')
                                if blockquotes:
                                    largest_blockquote = max(blockquotes, key=lambda x: len(str(x)))
                                    if len(str(largest_blockquote)) > 200:
                                        main_content_div = largest_blockquote
                                        logger.debug(f"Found main content in blockquote, size: {len(str(main_content_div))}")
                            
                            # If we found the main content, update the HTML content
                            if main_content_div:
                                content['html'] = str(main_content_div)
                                logger.debug(f"Updated HTML content from forwarded email, new size: {len(content['html'])}")
                except Exception as e:
                    logger.warning(f"Error processing forwarded HTML content: {e}")
            
            # Final content length check
            if len(content['html']) < 100 and len(content['text']) < 100:
                logger.warning(f"Both HTML and text content are very short. HTML: {len(content['html'])} chars, Text: {len(content['text'])} chars")
            
            return content
            
        except Exception as e:
            logger.error(f"Error extracting email content: {e}", exc_info=True)
            return content
    
    def _is_processed(self, session, message_id):
        """Check if an email was already processed."""
        if not message_id:
            return False
        
        try:
            existing = session.query(ProcessedEmail).filter_by(message_id=message_id).first()
            return existing is not None
        except Exception as e:
            logger.error(f"Error checking if email is processed: {e}")
            return False
    
    def _mark_as_processed(self, session, email_data):
        """Mark an email as processed in the database."""
        try:
            # First check if this email is already in the database
            existing = None
            if 'message_id' in email_data:
                existing = session.query(ProcessedEmail).filter_by(message_id=email_data['message_id']).first()
            
            if existing:
                # If it exists, update the date_processed field
                existing.date_processed = datetime.now()
                logger.debug(f"Updated existing email {email_data['subject']} as processed")
            else:
                # If it doesn't exist, create a new record
                processed_email = ProcessedEmail(
                    message_id=email_data['message_id'],
                    subject=email_data['subject'],
                    sender=email_data['sender'],
                    date_received=email_data['date'],
                    date_processed=datetime.now()
                )
                session.add(processed_email)
                logger.debug(f"Marked new email {email_data['subject']} as processed in database")
            
            session.commit()
        except Exception as e:
            if hasattr(session, 'rollback'):
                session.rollback()
            logger.error(f"Error marking email as processed: {e}", exc_info=True) 