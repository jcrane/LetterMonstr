"""
Email fetcher for LetterMonstr application.

This module handles connecting to Gmail via IMAP and fetching new emails.
"""

import imaplib
import email
import logging
import os
import datetime
from datetime import datetime, timedelta
import sys

# Try different import paths for email header decoding (Python version compatibility)
try:
    from email.header import decode_header
except ImportError:
    # Fallback for Python 3.13+
    try:
        from email import header
        decode_header = header.decode_header
    except ImportError:
        # Last resort fallback
        def decode_header(header_value):
            return [(header_value, None)]

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Import database models
try:
    from src.database.models import get_session, ProcessedEmail
except ImportError as e:
    raise ImportError(f"Could not import database models: {e}. Please ensure SQLAlchemy is installed.")

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
        """Fetch new emails from the configured folders."""
        mail = self.connect()
        session = get_session(self.db_path)
        
        all_emails = []
        
        try:
            # Calculate the date for the lookback period
            since_date = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%d-%b-%Y")
            
            # Process each folder
            for folder in self.folders:
                # Select the mailbox/folder
                mail.select(folder)
                
                # Search for emails within the lookback period
                status, messages = mail.search(None, f'(SINCE {since_date})')
                
                if status != 'OK':
                    logger.warning(f"Failed to search folder {folder}: {messages}")
                    continue
                
                # Get the list of email IDs
                email_ids = messages[0].split()
                
                if not email_ids:
                    logger.info(f"No emails found in folder {folder} since {since_date}")
                    continue
                
                # Process each email
                for e_id in email_ids:
                    # Fetch the email
                    status, msg_data = mail.fetch(e_id, '(RFC822)')
                    
                    if status != 'OK':
                        logger.warning(f"Failed to fetch email {e_id}: {msg_data}")
                        continue
                    
                    # Parse the email message
                    msg = email.message_from_bytes(msg_data[0][1])
                    
                    # Check if this email was already processed
                    message_id = msg.get('Message-ID', '')
                    if self._is_processed(session, message_id):
                        continue
                    
                    # Process the email
                    parsed_email = self._parse_email(msg)
                    
                    if parsed_email:
                        # Mark as processed in the database
                        self._mark_as_processed(session, parsed_email)
                        all_emails.append(parsed_email)
            
            # Close the connection
            mail.close()
            mail.logout()
            
            return all_emails
            
        except Exception as e:
            logger.error(f"Error fetching emails: {e}", exc_info=True)
            raise
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
            try:
                # Try different methods to parse date based on Python version
                try:
                    date = email.utils.parsedate_to_datetime(date_str)
                except AttributeError:
                    # Fallback for different Python versions
                    import time
                    parsed_date = email.utils.parsedate(date_str)
                    if parsed_date:
                        timestamp = time.mktime(parsed_date)
                        date = datetime.fromtimestamp(timestamp)
                    else:
                        date = datetime.now()
            except:
                date = datetime.now()
            
            # Extract message ID
            message_id = msg.get('Message-ID', '')
            
            # Extract content
            content = self._get_email_content(msg)
            
            return {
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'date': date,
                'content': content,
                'raw_message': msg
            }
        except Exception as e:
            logger.error(f"Error parsing email: {e}", exc_info=True)
            return None
    
    def _decode_header(self, header):
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
    
    def _get_email_content(self, msg):
        """Extract content from email message parts."""
        content = {
            'text': '',
            'html': '',
            'attachments': [],
            'raw_email': str(msg)  # Store the entire raw message to ensure we have everything
        }
        
        # The best HTML and text parts we've found
        best_html = ""
        best_text = ""
        
        def process_part(part, level=0):
            """Recursively process message parts for thorough content extraction."""
            nonlocal best_html, best_text
            
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachments in the main content extraction
            if "attachment" in content_disposition:
                try:
                    filename = part.get_filename()
                    if filename:
                        # Get the payload
                        payload = part.get_payload(decode=True)
                        if payload:
                            # Store attachment info for later use
                            content['attachments'].append({
                                'filename': filename,
                                'content_type': content_type,
                                'data': str(payload)[:100] + "..." if len(str(payload)) > 100 else str(payload)  # Limited preview
                            })
                except Exception as e:
                    logger.error(f"Error processing attachment: {e}")
                return
            
            # Extract body content
            try:
                # Check for multipart
                if part.is_multipart():
                    # Process each subpart
                    for subpart in part.get_payload():
                        process_part(subpart, level + 1)
                else:
                    # Extract and decode the content
                    payload = part.get_payload(decode=True)
                    
                    if payload:
                        try:
                            # Handle text content
                            if content_type == "text/plain":
                                text_content = payload.decode("utf-8", errors="replace")
                                if len(text_content) > len(best_text):
                                    best_text = text_content
                            
                            # Handle HTML content
                            elif content_type == "text/html":
                                html_content = payload.decode("utf-8", errors="replace")
                                if len(html_content) > len(best_html):
                                    best_html = html_content
                            
                            # Handle other content types
                            else:
                                logger.debug(f"Found other content type: {content_type}")
                                
                        except Exception as e:
                            logger.error(f"Error decoding content: {e}")
                            # Try to decode with different encodings as fallback
                            try:
                                if content_type.startswith("text/"):
                                    for encoding in ['latin-1', 'ascii', 'cp1252']:
                                        try:
                                            decoded = payload.decode(encoding, errors="replace")
                                            if content_type == "text/plain" and len(decoded) > len(best_text):
                                                best_text = decoded
                                            elif content_type == "text/html" and len(decoded) > len(best_html):
                                                best_html = decoded
                                            break
                                        except:
                                            continue
                            except:
                                pass
            except Exception as e:
                logger.error(f"Error processing message part: {e}")
        
        # Start processing from the root message
        try:
            # Check if this is a forwarded message
            subject = msg.get('Subject', '')
            is_forwarded = subject.startswith('Fwd:') or 'forwarded' in subject.lower()
            if is_forwarded:
                content['is_forwarded'] = True
                logger.info(f"Processing forwarded email: {subject}")
            
            # Process the message
            process_part(msg)
            
            # Set the best content we found
            if best_html:
                content['html'] = best_html
            
            if best_text:
                content['text'] = best_text
            
            # Check content lengths
            html_len = len(content['html'])
            text_len = len(content['text'])
            logger.info(f"Extracted HTML: {html_len} chars, text: {text_len} chars from email: {subject}")
            
            # If we don't have meaningful content, try to extract from raw
            if (html_len < 100 and text_len < 100) and msg.is_multipart():
                logger.warning(f"Limited content extracted, trying alternative methods for: {subject}")
                raw_content = str(msg)
                # Store raw content for later processing
                content['raw_content'] = raw_content
                
                # Try to identify better content in the raw message
                if "<html" in raw_content:
                    # Find complete HTML document if it exists
                    import re
                    html_match = re.search(r'<html[^>]*>.*?</html>', raw_content, re.DOTALL | re.IGNORECASE)
                    if html_match:
                        html_doc = html_match.group(0)
                        if len(html_doc) > html_len:
                            content['html'] = html_doc
                            logger.info(f"Found better HTML content in raw message: {len(html_doc)} chars")
        
        except Exception as e:
            logger.error(f"Error extracting email content: {e}", exc_info=True)
        
        # Ensure we have some content, even if it's minimal
        if not content['html'] and not content['text']:
            logger.warning("No text or HTML content found, using raw email as fallback")
            content['text'] = f"Email received with subject: {msg.get('Subject', 'No Subject')}"
        
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
            processed_email = ProcessedEmail(
                message_id=email_data['message_id'],
                subject=email_data['subject'],
                sender=email_data['sender'],
                date_received=email_data['date'],
                date_processed=datetime.now()
            )
            
            session.add(processed_email)
            session.commit()
        except Exception as e:
            if hasattr(session, 'rollback'):
                session.rollback()
            logger.error(f"Error marking email as processed: {e}", exc_info=True) 