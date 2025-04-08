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
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from src.database.models import get_session, Summary

logger = logging.getLogger(__name__)

def replace_list(match):
    """Replace list items with HTML list format."""
    content = match.group(2)
    return f'</p><ul><li>{content}</li></ul><p>'
    
def save_link(match):
    """Format markdown links as HTML."""
    text, url = match.groups()
    return f'<a href="{url}">{text}</a>'

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
                .read-more {{
                    display: inline-block;
                    margin-top: 8px;
                    margin-bottom: 16px;
                    font-weight: 500;
                    color: #0066cc;
                    text-decoration: none;
                }}
                .read-more::after {{
                    content: " →";
                }}
                .read-more:hover {{
                    text-decoration: underline;
                }}
                .read-more-missing {{
                    color: #999;
                    font-style: italic;
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
        
        # Clean up any problematic domains in HTML with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        problematic_domains = [
            'beehiiv.com', 'media.beehiiv.com', 'link.mail.beehiiv.com',
            'mailchimp.com', 'substack.com', 'bytebytego.com',
            'sciencealert.com', 'leapfin.com', 'cutt.ly',
            'genai.works', 'link.genai.works'
        ]
        
        for link in soup.find_all('a'):
            href = link.get('href')
            if href:
                # Check if the link is to a problematic domain root (no specific article)
                parsed_url = urlparse(href)
                domain = parsed_url.netloc.lower()
                
                if any(prob_domain in domain for prob_domain in problematic_domains) and (
                   not parsed_url.path or parsed_url.path == '/' or len(parsed_url.path) < 5):
                    # Replace the link with just its text
                    link.replace_with(link.text)
        
        # Get the final HTML
        html = str(soup)
        
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
        """Convert markdown-like text to HTML with improved formatting."""
        if not markdown_text:
            return ""
            
        # If the content already has full HTML structure, return it as is
        if markdown_text.strip().startswith('<html') and markdown_text.strip().endswith('</html>'):
            return markdown_text
            
        # Check if the content already has substantial HTML
        has_html_tags = re.search(r'<h[1-6]>|<p>|<div>|<ul>|<ol>|<li>|<table>', markdown_text)
        
        if has_html_tags:
            # Content already has HTML structure, just ensure it has proper paragraphs
            html = markdown_text
            
            # Ensure links are properly formatted with our classes
            html = re.sub(r'<a\s+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?Read more.*?)</a>', 
                         r'<a href="\1" class="read-more">\2</a>', html)
                         
            # Fix up any broken HTML
            soup = BeautifulSoup(html, 'html.parser')
            return str(soup)
        
        # Clean any HTML that might be present in raw form
        markdown_text = re.sub(r'<br\s*/?>', '\n', markdown_text)
        markdown_text = re.sub(r'</p>\s*<p>', '\n\n', markdown_text)
        markdown_text = re.sub(r'</?p>', '', markdown_text)
        
        # Replace newlines with <br> tags
        html = markdown_text.replace('\n\n', '</p><p>').replace('\n', '<br>')
        
        # Wrap in paragraph tags if not already wrapped
        if not html.startswith('<p>'):
            html = '<p>' + html
        if not html.endswith('</p>'):
            html += '</p>'
        
        # Replace headers
        # h1 - match lines like # Header or == Header == or HEADER:
        html = re.sub(r'^#\s+(.+?)$|^==\s*(.+?)\s*==|^([A-Z][A-Z\s&]+[A-Z])(?::|\s*$)',
                      lambda m: f'</p><h1>{m.group(1) or m.group(2) or m.group(3)}</h1><p>', 
                      html, flags=re.MULTILINE)
        
        # h2 - match lines like ## Header or -- Header --
        html = re.sub(r'^##\s+(.+?)$|^--\s*(.+?)\s*--',
                      lambda m: f'</p><h2>{m.group(1) or m.group(2)}</h2><p>', 
                      html, flags=re.MULTILINE)
        
        # h3 - match lines like ### Header
        html = re.sub(r'^###\s+(.+?)$',
                      lambda m: f'</p><h3>{m.group(1)}</h3><p>', 
                      html, flags=re.MULTILINE)
                      
        # Replace **bold** with <strong>bold</strong>
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        
        # Replace *italic* with <em>italic</em>
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Replace lists
        html = re.sub(r'(<br>|<p>)\s*[-•]\s+(.+?)(?=<br>|</p>)', replace_list, html)
        
        # Handle "Read more" links
        # First, convert direct reference style
        html = re.sub(r'\[Read more\]\s*\((https?://[^)]+)\)', r'<a href="\1" class="read-more">Read more →</a>', html)
        
        # Handle inline HTML links that contain "Read more"
        html = re.sub(r'<a\s+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?Read more.*?)</a>', 
                     r'<a href="\1" class="read-more">\2</a>', html)
        
        # Fix links that point to problematic domains (root domains without proper articles)
        problematic_domains = [
            'beehiiv.com', 'media.beehiiv.com', 'link.mail.beehiiv.com',
            'mailchimp.com', 'substack.com', 'bytebytego.com',
            'sciencealert.com', 'leapfin.com', 'cutt.ly',
            'genai.works', 'link.genai.works'
        ]
        
        for domain in problematic_domains:
            # Find links to problematic root domains and remove them
            pattern = f'<a href=[\'"]https?://(?:www\\.)?{domain}/?[\'"][^>]*>([^<]+)</a>'
            html = re.sub(pattern, r'\1', html)  # Replace with just the text content
        
        # Special case for "Read more" links without href
        html = re.sub(r'(?<![\'"])Read more(?![\'"]\s*\])',
                     r'<span class="read-more-missing">Read more</span>', html)
        
        # Handle other links - save links
        html = re.sub(r'\[([^\]]+)\]\s*\((https?://[^)]+)\)', save_link, html)
        
        # Fix any broken paragraphs
        html = html.replace('</p><br><p>', '</p><p>')
        html = re.sub(r'<p>\s*</p>', '', html)
        
        # Fix nested paragraphs
        html = re.sub(r'<p>(\s*<p>)', r'\1', html)
        html = re.sub(r'(</p>\s*)</p>', r'\1', html)
        
        # Final cleanup with BeautifulSoup to ensure valid HTML
        try:
            soup = BeautifulSoup(html, 'html.parser')
            return str(soup)
        except Exception as e:
            logger.error(f"Error cleaning HTML: {e}")
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