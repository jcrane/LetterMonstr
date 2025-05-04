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
        
        # Process summary text - check if it's already HTML
        is_html = bool(re.search(r'<html|<body|<h[1-6]|<p>|<div', summary_text))
        
        if is_html:
            # If it already has substantial HTML, just wrap it in our template
            # But first clean up any problematic markdown-like elements
            html = self._ensure_proper_html(summary_text)
        else:
            # Convert markdown to HTML
            html = self._markdown_to_html(summary_text)
        
        # Create the complete HTML email with styling
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
                
                # Add class="read-more" to links containing "Read more" if they don't have it
                if "read more" in link.text.lower() and not link.get('class'):
                    link['class'] = 'read-more'
        
        # Remove any Markdown-style headers that might have been mixed with HTML
        for tag in soup.find_all(text=re.compile(r'^#+\s+')):
            clean_text = re.sub(r'^#+\s+', '', tag.string)
            tag.replace_with(clean_text)
        
        # Get the final HTML
        html = str(soup)
        
        # Create plain text version (simpler)
        text = "LetterMonstr Newsletter Summary\n\n"
        # Extract text from HTML
        try:
            text_soup = BeautifulSoup(html, 'html.parser')
            text += text_soup.get_text(separator='\n\n')
        except:
            text += "A formatted HTML newsletter summary is available. Please view in an HTML-compatible email client."
        
        # Attach parts - text first, then HTML
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
    
    def _ensure_proper_html(self, html_content):
        """Ensure content is proper HTML, fixing any markdown remnants."""
        if not html_content:
            return "<h1>LetterMonstr Newsletter Summary</h1><p>No content available</p>"
            
        # Check if we have a basic structure already
        has_title = bool(re.search(r'<h1', html_content))
        
        if not has_title:
            html_content = f"<h1>LetterMonstr Newsletter Summary</h1>\n{html_content}"
            
        # Replace any remaining markdown headers
        html_content = re.sub(r'^#\s+(.+?)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^##\s+(.+?)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^###\s+(.+?)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
        
        # Replace markdown bullets
        html_content = re.sub(r'^\*\s+(.+?)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^-\s+(.+?)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
        
        # Wrap adjacent list items in ul tags
        html_content = re.sub(r'(<li>.+?</li>)\s*(<li>.+?</li>)', r'<ul>\1\2</ul>', html_content, flags=re.DOTALL)
        
        # Fix lone list items
        html_content = re.sub(r'(<li>.+?</li>)(?!<li>|</ul>)', r'<ul>\1</ul>', html_content)
        
        # Ensure paragraphs are wrapped in p tags
        paragraphs = re.split(r'\n\n+', html_content)
        processed_paragraphs = []
        
        for p in paragraphs:
            # Skip if it's already in a tag
            if re.match(r'^\s*<(h[1-6]|p|ul|ol|li|div|table)', p.strip()):
                processed_paragraphs.append(p)
            else:
                # Skip empty lines
                if not p.strip():
                    continue
                # Wrap in p tags unless it's just one line with a special tag
                if not re.match(r'^\s*<([a-z][a-z0-9]*)\b[^>]*>(.*?)</\1>', p.strip()):
                    processed_paragraphs.append(f"<p>{p}</p>")
                else:
                    processed_paragraphs.append(p)
        
        # Join everything back
        html_content = '\n'.join(processed_paragraphs)
        
        # Clean up with BeautifulSoup
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Fix any remaining Markdown-style headers
            for tag in soup.find_all(text=re.compile(r'^#+\s+')):
                header_level = len(re.match(r'^(#+)\s+', tag.string).group(1))
                header_text = re.sub(r'^#+\s+', '', tag.string)
                
                # Create a new header tag
                new_tag = soup.new_tag(f"h{min(header_level, 6)}")
                new_tag.string = header_text
                
                # Replace the text with the header tag
                tag.replace_with(new_tag)
            
            # Ensure Read more links have the right class
            for link in soup.find_all('a'):
                if "read more" in link.text.lower() and not link.get('class'):
                    link['class'] = 'read-more'
            
            return str(soup)
        except Exception as e:
            logger.error(f"Error cleaning HTML with BeautifulSoup: {e}")
            return html_content
    
    def _markdown_to_html(self, markdown_text):
        """Convert markdown-like text to clean HTML."""
        if not markdown_text:
            return "<h1>LetterMonstr Newsletter Summary</h1><p>No content available</p>"
            
        # If the content already has full HTML structure, return it after cleaning
        if markdown_text.strip().startswith('<html') or markdown_text.strip().startswith('<!DOCTYPE html'):
            return self._ensure_proper_html(markdown_text)
            
        # First, clean any existing HTML tags
        # Replace <br> with newlines for consistent processing
        markdown_text = re.sub(r'<br\s*/?>', '\n', markdown_text)
        
        # Replace </p><p> with double newlines
        markdown_text = re.sub(r'</p>\s*<p>', '\n\n', markdown_text)
        
        # Strip other common tags for clean processing
        markdown_text = re.sub(r'</?(?:p|div|span)>', '', markdown_text)
        
        # Convert markdown headers to HTML
        html = markdown_text
        
        # h1 - match lines like # Header or == Header == or HEADER:
        html = re.sub(r'^#\s+(.+?)$|^==\s*(.+?)\s*==|^([A-Z][A-Z\s&]+[A-Z])(?::|\s*$)',
                      lambda m: f'<h1>{m.group(1) or m.group(2) or m.group(3)}</h1>', 
                      html, flags=re.MULTILINE)
        
        # h2 - match lines like ## Header or -- Header --
        html = re.sub(r'^##\s+(.+?)$|^--\s*(.+?)\s*--',
                      lambda m: f'<h2>{m.group(1) or m.group(2)}</h2>', 
                      html, flags=re.MULTILINE)
        
        # h3 - match lines like ### Header
        html = re.sub(r'^###\s+(.+?)$',
                      lambda m: f'<h3>{m.group(1)}</h3>', 
                      html, flags=re.MULTILINE)
        
        # Convert bold and italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Process bullet lists
        lines = html.split('\n')
        in_list = False
        processed_lines = []
        
        for line in lines:
            # Check if this is a list item
            list_match = re.match(r'^\s*[-*•]\s+(.+)$', line)
            
            if list_match:
                item_content = list_match.group(1)
                if not in_list:
                    # Start a new list
                    processed_lines.append('<ul>')
                    in_list = True
                # Add the list item
                processed_lines.append(f'<li>{item_content}</li>')
            else:
                # Not a list item
                if in_list:
                    # End the current list
                    processed_lines.append('</ul>')
                    in_list = False
                processed_lines.append(line)
        
        # Close any open list at the end
        if in_list:
            processed_lines.append('</ul>')
        
        html = '\n'.join(processed_lines)
        
        # Handle links - multiple formats
        # Convert markdown links [text](url)
        html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)
        
        # Handle "Read more" links
        html = re.sub(r'\[Read more\]\s*\((https?://[^)]+)\)', 
                     r'<a href="\1" class="read-more">Read more</a>', html)
        
        # Handle existing HTML links that should have the read-more class
        html = re.sub(r'<a\s+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?Read more.*?)</a>', 
                     r'<a href="\1" class="read-more">\2</a>', html)
        
        # Wrap text in paragraphs by splitting on double newlines
        paragraphs = re.split(r'\n\n+', html)
        processed_paragraphs = []
        
        for p in paragraphs:
            # Skip if it's empty or already in a tag
            if not p.strip() or re.match(r'^\s*<(h[1-6]|ul|ol|li|div|p)', p.strip()):
                if p.strip():  # Only add if not empty
                    processed_paragraphs.append(p)
            else:
                # Replace single newlines with <br> within paragraphs
                p_with_br = re.sub(r'\n', '<br>\n', p)
                processed_paragraphs.append(f'<p>{p_with_br}</p>')
        
        html = '\n'.join(processed_paragraphs)
        
        # Final cleanup with BeautifulSoup to ensure valid HTML
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Fix any standalone list items
            standalone_items = soup.find_all('li', recursive=False)
            if standalone_items:
                # Create a ul and move them inside
                ul = soup.new_tag('ul')
                for item in standalone_items:
                    item.extract()
                    ul.append(item)
                soup.append(ul)
            
            # Fix tags that got nested incorrectly (p inside p, etc.)
            for p in soup.find_all('p'):
                if p.find('p'):
                    # Find all nested paragraphs
                    nested_ps = p.find_all('p')
                    for nested_p in nested_ps:
                        # Replace with its contents
                        nested_p.replace_with(nested_p.decode_contents())
            
            # If there's no h1, add a title
            if not soup.find('h1'):
                title = soup.new_tag('h1')
                title.string = "LetterMonstr Newsletter Summary"
                soup.insert(0, title)
            
            return str(soup)
        except Exception as e:
            logger.error(f"Error cleaning HTML with BeautifulSoup: {e}")
            # Fallback - add minimal HTML structure
            if not re.search(r'<h1', html):
                html = "<h1>LetterMonstr Newsletter Summary</h1>\n" + html
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