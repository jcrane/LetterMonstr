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
        """Create an email message with the summary."""
        msg = MIMEMultipart('alternative')
        
        # Set email headers
        msg['From'] = self.sender_email
        msg['To'] = self.recipient_email
        
        # Set current date for the email
        today = datetime.now()
        current_date = today.strftime('%Y-%m-%d')
        
        # Create subject line
        msg['Subject'] = f'[LetterMonstr] Newsletter Summary {current_date}'
        
        # Process summary text as HTML with improved formatting
        # First check if summary_text already has HTML formatting
        if '<html' in summary_text or '<body' in summary_text:
            html = summary_text
        else:
            html = self._markdown_to_html(summary_text)
        
        # Create the complete HTML email with styling
        html = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.4;
                    color: #333333;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                h1, h2, h3, h4, h5, h6 {{
                    color: #222222;
                    margin-top: 20px;
                    margin-bottom: 10px;
                }}
                h1 {{ font-size: 24px; }}
                h2 {{ font-size: 22px; color: #0056b3; }}
                h3 {{ font-size: 18px; color: #0056b3; }}
                p {{ margin-bottom: 10px; }}
                a {{ color: #0066cc; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
                .source-link {{
                    font-size: 14px;
                    color: #666;
                    display: block;
                    margin-top: 5px;
                    margin-bottom: 15px;
                }}
                a[href]:after {{
                    content: attr(href);
                    display: none;
                }}
                a:has(text="Read more"):after,
                a:has(text="Read more →"):after {{
                    content: " →";
                }}
                a:has(text="Read more") {{
                    display: inline-block;
                    margin-top: 8px;
                    margin-bottom: 16px;
                    font-weight: 500;
                }}
                hr {{ 
                    border: 0;
                    height: 1px;
                    background: #ddd;
                    margin: 20px 0;
                }}
                ul {{ 
                    margin-top: 5px; 
                    margin-bottom: 10px; 
                    padding-left: 25px;
                }}
                li {{ margin-bottom: 5px; }}
                .footer {{ 
                    margin-top: 30px;
                    padding-top: 10px;
                    border-top: 1px solid #ddd;
                    font-size: 12px;
                    color: #777;
                }}
            </style>
        </head>
        <body>
            <h1>LetterMonstr Newsletter Summary</h1>
            {html}
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
    
    def _markdown_to_html(self, markdown_text):
        """Convert markdown to HTML with better formatting."""
        html = markdown_text
        
        # Handle headers (# Header 1, ## Header 2, etc.)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        
        # Handle section dividers (---------)
        html = re.sub(r'^-{3,}$', r'<hr>', html, flags=re.MULTILINE)
        
        # Handle bolding (**text**)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        
        # Handle italics (*text*)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Handle lists
        # Convert unordered list items
        html = re.sub(r'^\* (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        
        # Group list items into <ul> tags
        list_pattern = r'(<li>.+</li>\n)+'
        
        def replace_list(match):
            list_content = match.group(0)
            return f'<ul>\n{list_content}</ul>'
        
        html = re.sub(list_pattern, replace_list, html)
        
        # Handle paragraphs (lines followed by blank lines)
        html = re.sub(r'([^\n]+)\n\n', r'<p>\1</p>\n\n', html)
        
        # Preserve existing HTML links
        # First identify existing <a> tags and replace with placeholders
        links = []
        
        def save_link(match):
            links.append(match.group(0))
            return f"__LINK_PLACEHOLDER_{len(links)-1}__"
            
        html = re.sub(r'<a\s+href="[^"]*"[^>]*>[^<]*</a>', save_link, html)
        
        # Handle markdown links [text](url)
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)
        
        # Handle HTML link syntax that might be in text directly 
        html = re.sub(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', r'<a href="\1">\2</a>', html)
        
        # Make sure source links are properly formatted
        html = re.sub(r'\[Source: ([^\]]+)\]', r'<a href="\1" class="source-link">Source: \1</a>', html)
        
        # Ensure all URLs are proper links - make http URLs clickable
        url_pattern = r'(?<!href=")(https?://[^\s<>"]+)'
        html = re.sub(url_pattern, r'<a href="\1">\1</a>', html)
        
        # Restore original link placeholders
        for i, link in enumerate(links):
            placeholder = f"__LINK_PLACEHOLDER_{i}__"
            html = html.replace(placeholder, link)
        
        # Convert remaining newlines to <br> tags, but avoid adding between HTML tags
        # First split by lines
        lines = html.split('\n')
        
        # Then join with <br> tags, skipping certain cases
        result = ""
        for i, line in enumerate(lines):
            if i > 0:  # Skip adding <br> before the first line
                # Don't add <br> after opening tags or before closing tags
                if (line.strip().startswith('<') and not line.strip().startswith('</')) or \
                   (i < len(lines)-1 and lines[i+1].strip().startswith('</')) or \
                   line.strip() == '':
                    result += '\n' + line
                else:
                    result += '<br>\n' + line
            else:
                result += line
        
        return result
    
    def _get_domain(self, url):
        """Extract domain name from URL for display purposes."""
        try:
            domain = re.search(r'https?://(?:www\.)?([^/]+)', url).group(1)
            # Limit domain length
            if len(domain) > 30:
                domain = domain[:27] + '...'
            return domain
        except:
            # If domain extraction fails, return a shortened URL
            if len(url) > 40:
                return url[:37] + '...'
            return url 