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
        
        # Convert markdown to HTML
        html_summary = self._markdown_to_html(summary_text)
        
        # Create HTML version of the message
        html = f"""
        <html>
          <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
              body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }}
              h1 {{ color: #333366; margin-bottom: 20px; font-size: 24px; }}
              h2 {{ color: #333366; margin-top: 25px; margin-bottom: 10px; font-size: 20px; }}
              h3 {{ color: #555; margin-top: 20px; margin-bottom: 10px; font-size: 18px; }}
              h4 {{ color: #555; margin-top: 15px; margin-bottom: 8px; font-size: 16px; }}
              p {{ line-height: 1.6; margin-bottom: 15px; }}
              .summary {{ line-height: 1.6; }}
              .footer {{ margin-top: 30px; font-size: 12px; color: #666; border-top: 1px solid #ddd; padding-top: 20px; }}
              a {{ color: #3366cc; text-decoration: none; }}
              a:hover {{ text-decoration: underline; }}
              ul {{ margin-left: 20px; padding-left: 15px; }}
              li {{ margin-bottom: 10px; }}
              hr {{ border: 0; height: 1px; background: #ddd; margin: 20px 0; }}
              .source-links {{ 
                margin-top: 5px; 
                margin-bottom: 20px;
                background: #f8f8f8; 
                padding: 10px; 
                border-left: 3px solid #ddd;
                font-size: 14px;
              }}
              .source-links h4 {{ 
                margin-top: 0; 
                margin-bottom: 8px; 
                font-size: 14px; 
                color: #666;
                font-weight: normal;
              }}
              .source-links a {{ 
                display: block; 
                margin-bottom: 5px; 
                color: #555;
                font-size: 13px;
              }}
              .source-link {{ 
                color: #666; 
                font-size: 13px; 
                font-style: italic;
                margin-left: 5px;
              }}
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
        
        # Handle markdown links [text](url) and [Source: Title] format
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)
        
        # Handle [Source: Title] format links
        html = re.sub(r'\[Source: (.+?)\]', r'<a href="#" class="source-link">Source: \1</a>', html)
        
        # Convert plain URLs to links, but only if they're not already in an <a> tag
        url_pattern = r'(?<!href=")https?://[^\s<>"]+'
        html = re.sub(url_pattern, lambda m: f'<a href="{m.group(0)}">{self._get_domain(m.group(0))}</a>', html)
        
        # For source links blocks, create a special section
        source_links_pattern = r'SOURCE LINKS:\n(.+?)(?:\n\n|\Z)'
        
        def format_source_links(match):
            links_content = match.group(1)
            links_html = '<div class="source-links">\n<h4>Sources</h4>\n'
            
            # Extract each link
            link_matches = re.finditer(r'(ARTICLE|WEB VERSION): (.+?) - (https?://[^\s]+)', links_content)
            for link_match in link_matches:
                link_type = link_match.group(1)
                link_title = link_match.group(2)
                link_url = link_match.group(3)
                links_html += f'<a href="{link_url}">{link_title}</a>\n'
            
            links_html += '</div>'
            return links_html
        
        html = re.sub(source_links_pattern, format_source_links, html, flags=re.DOTALL)
        
        # Convert remaining newlines to <br> tags
        html = html.replace('\n', '<br>\n')
        
        return html
    
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