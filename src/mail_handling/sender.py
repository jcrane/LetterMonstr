"""
Email sender for LetterMonstr application.

This module handles sending summary emails to the recipient.
"""

import os
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import re

from src.database.models import get_session, Summary

logger = logging.getLogger(__name__)

class EmailSender:
    """Sends summary emails to the recipient."""
    
    def __init__(self, config):
        """Initialize with summary delivery configuration."""
        self.recipient_email = config['recipient_email']
        self.sender_email = config['sender_email']
        self.smtp_server = config['smtp_server']
        self.smtp_port = config['smtp_port']
        self.subject_prefix = config['subject_prefix']
        # Password will come from the email config section
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                'data', 'lettermonstr.db')
    
    def send_summary(self, summary_text, summary_id=None):
        """Send a summary email to the recipient."""
        # If no recipient email is configured, log and return
        if not self.recipient_email:
            logger.warning("No recipient email configured, skipping summary delivery")
            return False
        
        try:
            # Get the summary from the database if only ID is provided
            if summary_id and not summary_text:
                summary_text, summary_id = self._get_summary_by_id(summary_id)
                
                if not summary_text:
                    logger.error(f"Summary with ID {summary_id} not found")
                    return False
            
            # Create email message
            msg = self._create_email_message(summary_text)
            
            # Get password from config
            password = self._get_email_password()
            
            if not password:
                logger.error("No email password found in configuration")
                return False
            
            # Send the email
            self._send_email(msg, password)
            
            # Mark as sent in the database if we have a summary ID
            if summary_id:
                self._mark_as_sent(summary_id)
            
            logger.info(f"Summary email sent to {self.recipient_email}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending summary email: {e}", exc_info=True)
            return False
    
    def _create_email_message(self, summary_text):
        """Create an email message with the summary content."""
        # Create message container
        msg = MIMEMultipart('alternative')
        
        # Create subject line
        current_date = datetime.now().strftime('%Y-%m-%d')
        msg['Subject'] = f"{self.subject_prefix}Newsletter Summary {current_date}"
        msg['From'] = self.sender_email
        msg['To'] = self.recipient_email
        
        # Process summary text to convert markdown-style links to HTML
        # This handles links in the format [text](url)
        html_summary = summary_text
        
        # Convert plain URLs to HTML links
        url_pattern = r'(https?://[^\s]+)'
        html_summary = re.sub(url_pattern, r'<a href="\1" target="_blank">\1</a>', html_summary)
        
        # Replace newlines with HTML breaks and preserve spacing
        html_summary = html_summary.replace('\n', '<br>')
        
        # Enhance header formatting (lines with all caps)
        html_summary = re.sub(r'<br>([A-Z][A-Z\s]+[A-Z])<br>', r'<br><h2>\1</h2><br>', html_summary)
        
        # Format section headers with underlines (======)
        html_summary = re.sub(r'<br>([^<]+)<br>(=+)<br>', r'<br><h3>\1</h3><br>', html_summary)
        
        # Format asterisk bullet points 
        html_summary = re.sub(r'<br>\s*\*\s*([^<]+)<br>', r'<br><ul><li>\1</li></ul><br>', html_summary)
        
        # Format dividers
        html_summary = re.sub(r'<br>-{5,}<br>', r'<br><hr><br>', html_summary)
        
        # Create HTML version of the message
        html = f"""
        <html>
          <head>
            <style>
              body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
              h1 {{ color: #333366; margin-bottom: 20px; }}
              h2 {{ color: #333366; margin-top: 25px; margin-bottom: 10px; }}
              h3 {{ color: #555; margin-top: 20px; margin-bottom: 10px; }}
              .summary {{ line-height: 1.6; white-space: pre-wrap; }}
              .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
              a {{ color: #3366cc; text-decoration: none; }}
              a:hover {{ text-decoration: underline; }}
              ul {{ margin-left: 20px; padding-left: 15px; }}
              li {{ margin-bottom: 10px; }}
              hr {{ border: 0; height: 1px; background: #ddd; margin: 20px 0; }}
            </style>
          </head>
          <body>
            <h1>LetterMonstr Newsletter Summary</h1>
            <div class="summary">
              {html_summary}
            </div>
            <div class="footer">
              <p>This summary was generated by LetterMonstr on {current_date}.</p>
              <p>To change your delivery preferences, please update your configuration.</p>
            </div>
          </body>
        </html>
        """
        
        # Create plain text version
        text = f"""
        LetterMonstr Newsletter Summary
        ===============================
        
        {summary_text}
        
        ---
        This summary was generated by LetterMonstr on {current_date}.
        To change your delivery preferences, please update your configuration.
        """
        
        # Attach parts
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        
        msg.attach(part1)
        msg.attach(part2)
        
        return msg
    
    def _send_email(self, msg, password):
        """Send email via SMTP."""
        # Create a secure SSL context
        context = ssl.create_default_context()
        
        # Try to log in to server and send email
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.ehlo()  # Can be omitted
            server.starttls(context=context)
            server.ehlo()  # Can be omitted
            server.login(self.sender_email, password)
            server.sendmail(self.sender_email, self.recipient_email, msg.as_string())
    
    def _get_summary_by_id(self, summary_id):
        """Get a summary from the database by ID."""
        session = get_session(self.db_path)
        
        try:
            summary = session.query(Summary).filter_by(id=summary_id).first()
            
            if summary:
                return summary.summary_text, summary.id
            
            return None, None
            
        except Exception as e:
            logger.error(f"Error getting summary by ID: {e}", exc_info=True)
            return None, None
        finally:
            session.close()
    
    def _mark_as_sent(self, summary_id):
        """Mark a summary as sent in the database."""
        session = get_session(self.db_path)
        
        try:
            summary = session.query(Summary).filter_by(id=summary_id).first()
            
            if summary:
                summary.sent = True
                summary.sent_date = datetime.now()
                session.commit()
                logger.info(f"Marked summary {summary_id} as sent")
            
        except Exception as e:
            logger.error(f"Error marking summary as sent: {e}", exc_info=True)
            session.rollback()
        finally:
            session.close()
    
    def _get_email_password(self):
        """Get email password from configuration."""
        try:
            # Load the config file to get the password
            import yaml
            
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                                     'config', 'config.yaml')
            
            with open(config_path, 'r') as file:
                config = yaml.safe_load(file)
                
            # Get password from email section
            return config['email']['password']
            
        except Exception as e:
            logger.error(f"Error getting email password: {e}", exc_info=True)
            return None 