#!/usr/bin/env python3
"""
Simple email content examination tool.
Just reads the stored email content and prints details about links.
"""

import os
import sys
from bs4 import BeautifulSoup

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from src.database.models import get_session, ProcessedEmail, EmailContent

def examine_email():
    """Directly examine the email content in the database."""
    db_path = os.path.join(current_dir, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    
    try:
        # Get the most recent forwarded email
        email = session.query(ProcessedEmail).filter(
            ProcessedEmail.subject.like('Fwd:%')
        ).order_by(ProcessedEmail.date_processed.desc()).first()
        
        if not email:
            print("No forwarded emails found.")
            return
        
        print(f"Examining email: {email.subject}")
        
        # Get email content
        content_entry = session.query(EmailContent).filter_by(email_id=email.id).first()
        
        if not content_entry:
            print("No content found for this email.")
            return
        
        print(f"Content type: {content_entry.content_type}")
        print(f"Content length: {len(content_entry.content or '')}")
        
        # Check if it's HTML
        if content_entry.content_type == 'html' or (content_entry.content and '<html' in content_entry.content.lower()):
            print("\nExamining HTML content...")
            soup = BeautifulSoup(content_entry.content, 'html.parser')
            
            # Print all <a> tags
            a_tags = soup.find_all('a')
            print(f"Found {len(a_tags)} <a> tags in the HTML")
            
            if a_tags:
                print("\nExamining <a> tags:")
                for i, tag in enumerate(a_tags):
                    href = tag.get('href')
                    text = tag.get_text()
                    print(f"{i+1}. Tag: {tag}")
                    print(f"   href: {href}")
                    print(f"   text: {text}")
                    print()
            
            # Also check for inline URLs
            print("\nChecking for URLs in text:")
            text_content = soup.get_text()
            import re
            url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            urls = re.findall(url_pattern, text_content)
            print(f"Found {len(urls)} potential URLs in text")
            for url in urls[:10]:  # Show first 10
                print(f"URL: {url}")
        else:
            # For text content
            print("\nText content preview:")
            preview = content_entry.content[:500] + "..." if len(content_entry.content or '') > 500 else content_entry.content
            print(preview)
            
            # Check for URLs
            import re
            url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            urls = re.findall(url_pattern, content_entry.content or '')
            print(f"\nFound {len(urls)} potential URLs in text")
            for url in urls[:10]:  # Show first 10
                print(f"URL: {url}")
    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    examine_email() 