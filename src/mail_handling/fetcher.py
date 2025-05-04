"""
Email fetcher for LetterMonstr application.

This module handles connecting to Gmail via IMAP and fetching new emails.
"""

import imaplib
import logging
import os
import sys
from datetime import datetime, timedelta
import socket
import time
import email as email_lib
from email.header import decode_header
import base64

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Import database models
from src.database.models import get_session, ProcessedEmail, EmailContent

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
        self._mail = None  # Store the IMAP connection
    
    def connect(self):
        """Connect to the IMAP server."""
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Connecting to {self.server}:{self.port} (attempt {attempt+1}/{max_retries})")
                # Create an IMAP4 class with SSL
                self._mail = imaplib.IMAP4_SSL(self.server, self.port)
                
                # Login to the server
                self._mail.login(self.email, self.password)
                
                logger.info(f"Successfully connected to {self.server}")
                return self._mail
                
            except socket.gaierror as e:
                logger.error(f"DNS resolution error connecting to server: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying connection in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to connect after {max_retries} attempts")
                    raise
                    
            except Exception as e:
                logger.error(f"Failed to connect to email server: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying connection in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    raise
    
    def check_connection(self, mail=None):
        """Check if the IMAP connection is still alive and reconnect if needed."""
        try:
            # Use stored connection if none provided
            mail = mail or self._mail
            
            if not mail:
                logger.warning("No IMAP connection found, creating new connection")
                return self.connect()
            
            # Try a simple NOOP command to check connection
            status, response = mail.noop()
            if status == 'OK':
                return mail
            else:
                logger.warning("Connection check failed, attempting to reconnect")
                return self.connect()
        except Exception as e:
            logger.warning(f"Connection error: {e}, attempting to reconnect")
            return self.connect()
    
    def fetch_new_emails(self):
        """Fetch emails from the configured folders, including both unread and recent emails."""
        mail = self.connect()
        session = get_session(self.db_path)
        
        all_emails = []
        processed_email_ids = []
        
        try:
            # Calculate the date for the lookback period
            since_date = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
            
            logger.info(f"Looking for emails since {since_date} in folders: {self.folders}")
            
            # Process each folder
            for folder in self.folders:
                # Before each folder, ensure connection is still good
                mail = self.check_connection(mail)
                
                # Select the mailbox/folder
                status, folder_info = mail.select(folder)
                if status != 'OK':
                    logger.error(f"Failed to select folder {folder}: {folder_info}")
                    continue
                
                # Log how many messages are in the folder total
                message_count = int(folder_info[0])
                logger.info(f"Folder {folder} contains {message_count} total messages")
                
                # First try to get all unread emails
                status, unread_messages = mail.search(None, f'(UNSEEN SINCE {since_date})')
                unread_ids = []
                if status == 'OK' and unread_messages[0]:
                    unread_ids = unread_messages[0].split()
                    logger.info(f"Found {len(unread_ids)} unread emails in {folder}")
                
                # Next get all recent emails (last 7 days)
                status, recent_messages = mail.search(None, f'(SINCE {since_date})')
                recent_ids = []
                if status == 'OK' and recent_messages[0]:
                    recent_ids = recent_messages[0].split()
                    logger.info(f"Found {len(recent_ids)} total recent emails in {folder}")
                
                # Combine the IDs, ensuring no duplicates
                all_ids = list(set(unread_ids + recent_ids))
                
                # If we have a lot of emails, just take the most recent ones
                if len(all_ids) > 20:
                    logger.info(f"Limiting to 20 most recent emails out of {len(all_ids)}")
                    all_ids = sorted(all_ids, reverse=True)[:20]
                
                if not all_ids:
                    logger.info(f"No emails found in folder {folder} since {since_date}")
                    continue
                
                logger.info(f"Processing {len(all_ids)} emails from folder {folder}")
                
                # Process each email
                for e_id in all_ids:
                    # Before each email fetch, check connection again if we've processed a lot
                    if len(all_emails) > 0 and len(all_emails) % 10 == 0:
                        mail = self.check_connection(mail)
                    
                    # Fetch the email
                    status, msg_data = mail.fetch(e_id, '(RFC822)')
                    
                    if status != 'OK':
                        logger.warning(f"Failed to fetch email {e_id}: {msg_data}")
                        continue
                    
                    # Parse the email message
                    msg = email_lib.message_from_bytes(msg_data[0][1])
                    
                    # Get basic info for logging
                    subject = self._decode_header(msg.get('Subject', 'No Subject'))
                    sender = self._decode_header(msg.get('From', 'Unknown'))
                    logger.info(f"Processing email: {subject} from {sender}")
                    
                    # Check if this email was already processed in our database
                    message_id = msg.get('Message-ID', '')
                    if self._is_processed(session, message_id):
                        logger.info(f"Skipping already processed email: {message_id}")
                        continue
                    
                    # Process the email
                    parsed_email = self._parse_email(msg)
                    
                    if parsed_email:
                        # Add to the list of emails to process
                        all_emails.append(parsed_email)
                        # Keep track of email IDs for marking
                        processed_email_ids.append((e_id, parsed_email))
                    else:
                        logger.warning(f"Failed to parse email {subject} - skipping")
            
            # Close the connection
            try:
                mail.close()
                mail.logout()
                self._mail = None  # Clear stored connection
            except Exception as e:
                logger.warning(f"Error closing mail connection: {e}")
            
            # Return the list of fetched emails
            logger.info(f"Successfully fetched {len(all_emails)} new emails for processing")
            return all_emails
            
        except Exception as e:
            logger.error(f"Error fetching emails: {e}", exc_info=True)
            try:
                mail.logout()
                self._mail = None  # Clear stored connection
            except:
                pass
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
        """Extract content from the email message.
        
        Args:
            msg: Email message object
            
        Returns:
            dict: Dictionary with text and html content, as well as the raw message content
        """
        content = {
            'text': '',
            'html': '',
            'attachments': [],
            'raw_message': str(msg)  # Store the entire raw message to ensure we have everything
        }
        
        # The best HTML and text parts we've found
        best_html_part = ""
        best_text_part = ""
        
        def inspect_part(part, level=0):
            """Recursively inspect message parts to extract content."""
            nonlocal best_html_part, best_text_part
            
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachments
            if "attachment" in content_disposition:
                try:
                    filename = part.get_filename()
                    if filename:
                        # Get the payload
                        payload = part.get_payload(decode=True)
                        if payload:
                            # Convert binary data to string representation for storage
                            content['attachments'].append({
                                'filename': filename,
                                'content_type': content_type,
                                'data': base64.b64encode(payload).decode('utf-8')  # Convert binary to base64 string
                            })
                except Exception as e:
                    logger.error(f"Error processing attachment: {e}")
                return
            
            # Extract body content
            try:
                # Check for multipart
                if part.is_multipart():
                    # This is a container, recursively process each subpart
                    for subpart in part.get_payload():
                        inspect_part(subpart, level + 1)
                else:
                    # Extract and decode the content
                    payload = part.get_payload(decode=True)
                    
                    if payload:
                        # Handle text content
                        if content_type == "text/plain":
                            text_content = payload.decode("utf-8", errors="replace")
                            # Store if this is better than what we've found
                            if len(text_content) > len(best_text_part):
                                best_text_part = text_content
                        
                        # Handle HTML content
                        elif content_type == "text/html":
                            html_content = payload.decode("utf-8", errors="replace")
                            # Store if this is better than what we've found
                            if len(html_content) > len(best_html_part):
                                best_html_part = html_content
                        
                        # Handle other content types (like images)
                        else:
                            logger.debug(f"Found other content type: {content_type}")
                            
            except Exception as e:
                logger.error(f"Error processing part: {e}")
        
        # Start inspection at the root
        try:
            # First check if this is a Gmail forwarded message
            is_forwarded = False
            subject = msg.get('Subject', '')
            if subject and subject.startswith('Fwd:'):
                is_forwarded = True
                logger.debug(f"Processing forwarded message: {subject}")
            
            # Store the raw email data for forwarded emails
            if is_forwarded:
                # Get the entire email as string representation
                import email
                from email import policy
                raw_email_string = msg.as_string()
                content['raw_email'] = raw_email_string
                logger.info(f"Stored raw email for forwarded message, length: {len(raw_email_string)}")
                
                # If it's a multipart message, also try to extract the original message
                if msg.is_multipart():
                    # For Gmail forwarded messages, the original is usually in the last part
                    parts = msg.get_payload()
                    if len(parts) > 1:
                        last_part = parts[-1]
                        if last_part.is_multipart():
                            # Look for the html part in the last part
                            for subpart in last_part.get_payload():
                                if subpart.get_content_type() == 'text/html':
                                    orig_html = subpart.get_payload(decode=True)
                                    if orig_html:
                                        orig_html_str = orig_html.decode('utf-8', errors='replace')
                                        content['forwarded_html'] = orig_html_str
                                        logger.info(f"Extracted forwarded HTML content, length: {len(orig_html_str)}")
            
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
                    
                    # Look for common forwarded content markers from different email clients
                    # 1. Gmail forwarded message marker
                    found_content = False
                    
                    # Method 1: Look for Gmail forwarded message marker
                    fw_marker = soup.find(string=lambda s: s and "---------- Forwarded message ---------" in s)
                    
                    if fw_marker:
                        logger.debug("Found Gmail forwarded message marker in HTML")
                        
                        # Try to find the actual forwarded content
                        parent = fw_marker.parent
                        if parent:
                            # Try to find largest div after the marker
                            main_content_div = None
                            divs_after_marker = parent.find_next_siblings('div')
                            if divs_after_marker:
                                largest_div = max(divs_after_marker, key=lambda x: len(str(x)))
                                if len(str(largest_div)) > 200:  # Arbitrary size threshold
                                    main_content_div = largest_div
                                    logger.debug(f"Found main content div after Gmail marker, size: {len(str(main_content_div))}")
                                    content['html'] = str(main_content_div)
                                    found_content = True
                    
                    # Method 2: Look for Apple Mail forwarded message marker
                    if not found_content:
                        fw_marker = soup.find(string=lambda s: s and "Begin forwarded message:" in s)
                        if fw_marker:
                            logger.debug("Found Apple Mail forwarded message marker in HTML")
                            
                            # Try to find the actual forwarded content
                            parent = fw_marker.parent
                            if parent:
                                # Get all content after this marker
                                siblings = list(parent.next_siblings)
                                if siblings:
                                    combined_content = ''.join(str(sibling) for sibling in siblings)
                                    if len(combined_content) > 200:
                                        content['html'] = combined_content
                                        found_content = True
                                        logger.debug(f"Found content after Apple Mail marker, size: {len(combined_content)}")
                    
                    # Method 3: Look for quoted content (standard for many email clients)
                    if not found_content:
                        quotes = soup.select('blockquote')
                        if quotes:
                            largest_quote = max(quotes, key=lambda x: len(str(x)))
                            if len(str(largest_quote)) > 200:
                                content['html'] = str(largest_quote)
                                found_content = True
                                logger.debug(f"Found quoted content, size: {len(str(largest_quote))}")
                    
                    # Add class information to the HTML to make it easier to parse later
                    if found_content:
                        content['forwarded_content_extracted'] = True
                
                except Exception as e:
                    logger.error(f"Error processing forwarded HTML: {e}")
        
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
    
    def _store_email_content(self, email_data, email_id):
        """Store email content in the database"""
        try:
            session = get_session(self.db_path)
            
            # Store HTML content if available
            if 'html_content' in email_data:
                html_content = EmailContent(
                    email_id=email_id,
                    content_type='html'
                )
                html_content.set_content(email_data['html_content'])
                session.add(html_content)
                
            # Store text content if available
            if 'text_content' in email_data:
                text_content = EmailContent(
                    email_id=email_id,
                    content_type='text'
                )
                text_content.set_content(email_data['text_content'])
                session.add(text_content)
                
            # Store raw content if available
            if 'original_full_message' in email_data:
                raw_content = EmailContent(
                    email_id=email_id, 
                    content_type='raw'
                )
                raw_content.set_content(email_data['original_full_message'])
                session.add(raw_content)
                
            # Store main content if available (this could be a dict or complex structure)
            if 'main_content' in email_data:
                main_content = EmailContent(
                    email_id=email_id,
                    content_type='main'
                )
                main_content.set_content(email_data['main_content'])
                session.add(main_content)
                
            # Store raw email content if available
            if 'raw_email' in email_data:
                raw_email_content = EmailContent(
                    email_id=email_id,
                    content_type='raw_email'
                )
                raw_email_content.set_content(email_data['raw_email'])
                session.add(raw_email_content)
                
            # Store raw message content if available
            if 'raw_message' in email_data:
                raw_message_content = EmailContent(
                    email_id=email_id,
                    content_type='raw_message'
                )
                raw_message_content.set_content(email_data['raw_message'])
                session.add(raw_message_content)
                
            # Store content dictionary if available
            if 'content' in email_data:
                content_dict = EmailContent(
                    email_id=email_id,
                    content_type='content_dict'
                )
                content_dict.set_content(email_data['content'])
                session.add(content_dict)
                
            session.commit()
            logger.debug(f"Successfully stored content for email ID: {email_id}")
        except Exception as e:
            logger.error(f"Error storing email content: {e}")
            session.rollback()
            raise
        finally:
            session.close() 