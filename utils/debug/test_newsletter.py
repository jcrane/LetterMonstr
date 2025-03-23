#!/usr/bin/env python3
"""
Test Newsletter Generator for LetterMonstr

This script simulates a newsletter being received by sending a test email
to the configured Gmail account. It helps with testing the pipeline
without waiting for real newsletters.
"""

import os
import sys
import yaml
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import random

def load_config():
    """Load configuration from file."""
    config_path = os.path.join("config", "config.yaml")
    
    if not os.path.exists(config_path):
        print(f"Configuration file not found at {config_path}")
        print("Please run the setup script first: python setup_config.py")
        sys.exit(1)
    
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        sys.exit(1)

def create_test_newsletter():
    """Create a test newsletter with realistic content."""
    # Create random newsletter content
    topics = ["Technology", "Science", "Business", "Health", "Politics"]
    selected_topic = random.choice(topics)
    
    # Create HTML content with some links
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
            h1 {{ color: #2a5885; }}
            h2 {{ color: #4a76a8; }}
            .content {{ line-height: 1.6; }}
            .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <h1>Test {selected_topic} Newsletter</h1>
        <p>This is a test newsletter generated for LetterMonstr testing.</p>
        
        <div class="content">
            <h2>Latest in {selected_topic}</h2>
            <p>Here are some of the latest developments in {selected_topic}:</p>
            
            <h3>Major Breakthrough</h3>
            <p>Researchers have discovered a new approach to solving a long-standing problem in the field. 
            Read more details <a href="https://en.wikipedia.org/wiki/{selected_topic}">here</a>.</p>
            
            <h3>Industry News</h3>
            <p>Leading companies are adopting new strategies to address challenges. 
            Check out the analysis <a href="https://github.com/topics/{selected_topic.lower()}">here</a>.</p>
            
            <h3>Opinion Piece</h3>
            <p>Expert opinions suggest that the future of {selected_topic} will be shaped by current trends. 
            <a href="https://www.google.com/search?q={selected_topic}+trends">Learn more</a>.</p>
        </div>
        
        <div class="footer">
            <p>This is a test newsletter sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>To unsubscribe from these tests, update your test configuration.</p>
            <p><small>This email contains some <span style="color:#999">sponsored</span> content for testing ad filtering.</small></p>
        </div>
    </body>
    </html>
    """
    
    # Create plain text version
    text_content = f"""
    Test {selected_topic} Newsletter
    ===============================
    
    This is a test newsletter generated for LetterMonstr testing.
    
    Latest in {selected_topic}
    -----------------------
    
    Here are some of the latest developments in {selected_topic}:
    
    Major Breakthrough
    -----------------
    Researchers have discovered a new approach to solving a long-standing problem in the field.
    Read more details at: https://en.wikipedia.org/wiki/{selected_topic}
    
    Industry News
    ------------
    Leading companies are adopting new strategies to address challenges.
    Check out the analysis at: https://github.com/topics/{selected_topic.lower()}
    
    Opinion Piece
    ------------
    Expert opinions suggest that the future of {selected_topic} will be shaped by current trends.
    Learn more: https://www.google.com/search?q={selected_topic}+trends
    
    ---
    This is a test newsletter sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    To unsubscribe from these tests, update your test configuration.
    This email contains some sponsored content for testing ad filtering.
    """
    
    return {
        "subject": f"Test Newsletter: {selected_topic} Update {datetime.now().strftime('%Y-%m-%d')}",
        "html": html_content,
        "text": text_content
    }

def send_test_newsletter(config, newsletter_content):
    """Send a test newsletter to the configured email."""
    # Get email configuration
    recipient_email = config['email']['fetch_email']
    sender_email = config['summary']['recipient_email']
    
    # If no sender email is configured, use the recipient email
    if not sender_email:
        sender_email = recipient_email
    
    # Get password
    password = config['email']['password']
    
    if not password:
        print("No email password found in configuration")
        return False
    
    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = newsletter_content['subject']
    msg['From'] = sender_email
    msg['To'] = recipient_email
    
    # Add message ID with a unique format for testing
    msg['Message-ID'] = f"<test-{datetime.now().strftime('%Y%m%d%H%M%S')}@lettermonstr-test.local>"
    
    # Attach parts
    part1 = MIMEText(newsletter_content['text'], 'plain')
    part2 = MIMEText(newsletter_content['html'], 'html')
    msg.attach(part1)
    msg.attach(part2)
    
    # Send email
    try:
        # Create a secure SSL context
        context = ssl.create_default_context()
        
        # Connect to server
        server = smtplib.SMTP(config['summary']['smtp_server'], config['summary']['smtp_port'])
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        
        # Login
        server.login(sender_email, password)
        
        # Send email
        server.sendmail(sender_email, recipient_email, msg.as_string())
        
        # Close connection
        server.close()
        
        print(f"Test newsletter sent successfully to {recipient_email}")
        print(f"Subject: {newsletter_content['subject']}")
        return True
        
    except Exception as e:
        print(f"Failed to send test newsletter: {e}")
        return False

def main():
    """Main function."""
    print("LetterMonstr Test Newsletter Generator")
    print("====================================")
    
    # Load configuration
    config = load_config()
    
    # Create test newsletter
    newsletter = create_test_newsletter()
    
    # Ask for confirmation
    print(f"\nReady to send a test newsletter to: {config['email']['fetch_email']}")
    print(f"Subject: {newsletter['subject']}")
    
    confirm = input("\nSend this test newsletter? (y/n): ").strip().lower()
    
    if confirm == 'y':
        # Send newsletter
        success = send_test_newsletter(config, newsletter)
        
        if success:
            print("\nTest newsletter sent successfully!")
            print("It should be processed the next time LetterMonstr runs.")
            print("You can manually trigger processing by running: python src/main.py")
        else:
            print("\nFailed to send test newsletter. Check the error message above.")
    else:
        print("\nTest newsletter sending cancelled.")

if __name__ == "__main__":
    main() 