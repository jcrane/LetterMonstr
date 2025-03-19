#!/usr/bin/env python3
"""
Debug Link Extraction for LetterMonstr

This script diagnoses and fixes the issue with link extraction from forwarded emails.
It reads the last processed emails and examines the content to see why links aren't being extracted.
"""

import os
import sys
import json
import logging
from datetime import datetime

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import required modules
from src.database.models import get_session, ProcessedEmail, EmailContent, Link
from src.mail_handling.parser import EmailParser
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def analyze_email_content():
    """Analyze email content to find why links aren't being extracted."""
    # Get database path
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    
    # Create session
    session = get_session(db_path)
    
    try:
        # Get all forwarded emails
        forwarded_emails = session.query(ProcessedEmail).filter(
            ProcessedEmail.subject.like('Fwd:%')
        ).order_by(ProcessedEmail.date_processed.desc()).all()
        
        if not forwarded_emails:
            print("No forwarded emails found in the database.")
            return
        
        print(f"Found {len(forwarded_emails)} forwarded emails in the database.")
        
        # Process each forwarded email
        for idx, email in enumerate(forwarded_emails[:5]):  # Analyze the 5 most recent
            print(f"\n========= Email {idx+1}: {email.subject} =========")
            
            # Get content for this email
            content_entries = session.query(EmailContent).filter_by(email_id=email.id).all()
            
            if not content_entries:
                print(f"  No content entries found for email {email.id}")
                continue
            
            # Get link entries for this email
            links = []
            for content in content_entries:
                link_entries = session.query(Link).filter_by(content_id=content.id).all()
                links.extend(link_entries)
            
            # Print content and link info
            print(f"  Content entries: {len(content_entries)}")
            print(f"  Stored links: {len(links)}")
            
            # Now analyze the content
            parser = EmailParser()
            
            # For each content entry, try to extract links and analyze issues
            for i, content in enumerate(content_entries):
                print(f"\n  --- Content Entry {i+1} ({content.content_type}) ---")
                
                # Check if content appears truncated
                content_length = len(content.content or "")
                print(f"  Content length: {content_length} characters")
                
                # Check if content looks like HTML
                is_html = content.content_type == 'html' or (content.content and '<html' in content.content.lower())
                content_type = 'html' if is_html else 'text'
                print(f"  Content appears to be: {content_type}")
                
                # Try to extract links using our parser
                try:
                    extracted_links = parser.extract_links(content.content, content_type)
                    print(f"  Links extracted by parser: {len(extracted_links)}")
                    
                    # If no links, try direct methods
                    if not extracted_links:
                        print("  No links found by parser, trying direct methods:")
                        
                        # Method 1: Direct regex search
                        if is_html:
                            # Try direct href attribute extraction
                            href_pattern = r'href=[\'"]?([^\'" >]+)'
                            direct_hrefs = re.findall(href_pattern, content.content)
                            valid_urls = [url for url in direct_hrefs if is_valid_url(url)]
                            print(f"  - Direct href extraction found {len(valid_urls)} potential links")
                            
                            if valid_urls:
                                print("    Example URLs:")
                                for url in valid_urls[:3]:  # Show first 3
                                    print(f"    * {url}")
                        
                        # Method 2: Simple URL pattern
                        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
                        direct_urls = re.findall(url_pattern, content.content)
                        valid_direct_urls = [url for url in direct_urls if is_valid_url(url)]
                        print(f"  - Direct URL pattern found {len(valid_direct_urls)} potential links")
                        
                        if valid_direct_urls:
                            print("    Example URLs:")
                            for url in valid_direct_urls[:3]:  # Show first 3
                                print(f"    * {url}")
                    else:
                        print("  Example extracted links:")
                        for link in extracted_links[:3]:  # Show first 3
                            print(f"  * {link['url']} - {link['title'][:30]}...")
                    
                    # Analyze HTML structure if it's HTML
                    if is_html:
                        soup = BeautifulSoup(content.content, 'html.parser')
                        a_tags = soup.find_all('a')
                        print(f"  BeautifulSoup found {len(a_tags)} <a> tags")
                        
                        # Check for problematic HTML structures
                        a_tags_with_href = [a for a in a_tags if a.get('href')]
                        print(f"  <a> tags with href attribute: {len(a_tags_with_href)}")
                        
                        if len(a_tags) > 0 and len(a_tags_with_href) == 0:
                            print("  ISSUE DETECTED: <a> tags exist but none have href attributes")
                            
                        if len(a_tags_with_href) > 0 and len(extracted_links) == 0:
                            print("  ISSUE DETECTED: <a> tags with href exist but no links were extracted")
                            print("  This suggests a bug in the link extraction logic")
                except Exception as e:
                    print(f"  Error analyzing content: {e}")
    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

def fix_link_extraction():
    """Fix the link extraction issue by updating the parser code."""
    parser_file = os.path.join(current_dir, 'src', 'mail_handling', 'parser.py')
    
    try:
        # Read the current parser file
        with open(parser_file, 'r') as f:
            parser_code = f.read()
        
        # Check if the bug is present
        if 'if href and self._is_valid_url(href):' in parser_code:
            print("\nFound potential issue in the parser code.")
            print("The current code only extracts URLs that pass strict validation.")
            print("This might be excluding valid URLs that don't match the validation pattern.")
            
            # Make a backup
            backup_file = f"{parser_file}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            with open(backup_file, 'w') as f:
                f.write(parser_code)
            print(f"Created backup of parser file at {backup_file}")
            
            # Update the code to be more permissive
            fixed_code = parser_code.replace(
                'if href and self._is_valid_url(href):',
                'if href and (href.startswith("http") or href.startswith("https") or href.startswith("www")):'
            )
            
            # Also fix the extract_links_with_regex method to better handle common URL patterns
            if 'url_pattern = r\'https?://[^\\s<>"]+|www\\.[^\\s<>"]+\'' in fixed_code:
                fixed_code = fixed_code.replace(
                    'url_pattern = r\'https?://[^\\s<>"]+|www\\.[^\\s<>"]+\'',
                    'url_pattern = r\'https?://[^\\s<>"\')]+|www\\.[^\\s<>"\')]+\''
                )
            
            # Fix the _is_valid_url method to be more permissive
            if 'return all([result.scheme, result.netloc]) and result.scheme in [\'http\', \'https\']' in fixed_code:
                fixed_code = fixed_code.replace(
                    'return all([result.scheme, result.netloc]) and result.scheme in [\'http\', \'https\']',
                    'return (result.scheme in [\'http\', \'https\'] and result.netloc) or (not result.scheme and result.netloc.startswith("www."))'
                )
            
            # Add an improved URL extraction method
            if 'def _extract_links_with_regex' in fixed_code and 'def _improved_extract_links' not in fixed_code:
                # Find the end of the _extract_links_with_regex method
                regex_method_end = fixed_code.find('def _clean_html', fixed_code.find('def _extract_links_with_regex'))
                
                # Insert the new method
                improved_method = '''
    def _improved_extract_links(self, content):
        """Extract links with multiple methods for maximum coverage."""
        links = []
        seen_urls = set()
        
        # Ensure content is a string
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        
        try:
            # Method 1: Extract from HTML using BeautifulSoup
            if '<html' in content.lower() or '<a' in content.lower():
                soup = BeautifulSoup(content, 'html.parser')
                
                # Find all links
                for a_tag in soup.find_all('a'):
                    href = a_tag.get('href', '').strip()
                    text = a_tag.get_text().strip()
                    
                    if href and href not in seen_urls:
                        # Accept any http/https URL or www URL
                        if (href.startswith('http') or href.startswith('https') or href.startswith('www')):
                            seen_urls.add(href)
                            links.append({
                                'url': href,
                                'title': text if text else href
                            })
            
            # Method 2: Regex extraction of URLs
            # This pattern will catch most URLs with or without "http://" prefix
            url_patterns = [
                r'https?://[^\\s<>"\')]+',  # http:// or https:// URLs
                r'www\\.[^\\s<>"\')]+',     # www URLs
                r'[\\w-]+\\.[\\w.-]+\\.[^\\s<>"\')]+(?=(?:[^<]|$))'  # domain.tld URLs
            ]
            
            for pattern in url_patterns:
                found_urls = re.findall(pattern, content)
                for url in found_urls:
                    url = url.strip(',.:;"\')>')  # Clean up ending punctuation
                    if url not in seen_urls:
                        seen_urls.add(url)
                        # Prepend http:// to www URLs if needed
                        if url.startswith('www.') and not url.startswith('http'):
                            url = 'http://' + url
                        links.append({
                            'url': url,
                            'title': url
                        })
            
            return links
        except Exception as e:
            logger.error(f"Error in improved link extraction: {e}", exc_info=True)
            return []
'''
                fixed_code = fixed_code[:regex_method_end] + improved_method + fixed_code[regex_method_end:]
            
            # Update the extract_links method to use our improved method
            if 'links = self._extract_links_with_regex(content)' in fixed_code:
                fixed_code = fixed_code.replace(
                    'links = self._extract_links_with_regex(content)',
                    'links = self._improved_extract_links(content)'
                )
                
                # Also update the first method to use the improved version
                fixed_code = fixed_code.replace(
                    'links.extend(self._extract_links_with_regex(content))',
                    'links.extend(self._improved_extract_links(content))'
                )
            
            # Ask for confirmation
            confirm = input("\nDo you want to update the parser code with improved link extraction? (yes/y): ")
            
            if confirm.lower() in ['yes', 'y']:
                with open(parser_file, 'w') as f:
                    f.write(fixed_code)
                print("Successfully updated the parser code with improved link extraction.")
                print("The changes will take effect the next time the application runs.")
                print("You may need to restart LetterMonstr for the changes to take effect.")
            else:
                print("Operation cancelled. No changes were made.")
            
        else:
            print("\nCould not identify the issue in the parser code.")
            print("The parser code may have been already updated or the issue is elsewhere.")
    
    except Exception as e:
        print(f"Error fixing link extraction: {e}")

def is_valid_url(url):
    """Check if a URL is valid."""
    if not url:
        return False
    
    # Accept "www." URLs too
    if url.startswith('www.'):
        url = 'http://' + url
    
    try:
        result = urlparse(url)
        return (result.scheme in ['http', 'https'] and result.netloc) or (not result.scheme and result.netloc.startswith("www."))
    except:
        return False

if __name__ == "__main__":
    print("\nLetterMonstr Link Extraction Debugger")
    print("===================================\n")
    print("This tool analyzes why links aren't being extracted from forwarded emails.")
    print("Options:")
    print("1. Analyze email content and link extraction")
    print("2. Fix link extraction issues")
    print("3. Exit without making changes\n")
    
    while True:
        try:
            choice = input("Enter your choice (1/2/3): ")
            if choice == '1':
                analyze_email_content()
                break
            elif choice == '2':
                fix_link_extraction()
                break
            elif choice == '3':
                print("Exiting without making changes.")
                sys.exit(0)
            else:
                print("Invalid choice. Please try again.")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"\nAn error occurred: {e}")
            sys.exit(1) 