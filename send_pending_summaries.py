#!/usr/bin/env python3
"""
Send pending summaries script for LetterMonstr.

This script finds unsent summaries in the database and sends them immediately.

Usage:
    python send_pending_summaries.py           # Interactive mode
    python send_pending_summaries.py all       # Send all pending summaries
    python send_pending_summaries.py <id>      # Send summary with specific ID
"""

import os
import sys
import logging
from datetime import datetime
import json

# Set up the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("\nWarning: python-dotenv module not found.")
    print("If you have environment variables in a .env file, they won't be loaded.")
    print("Install with: pip install python-dotenv\n")

# Load config
try:
    import yaml
    config_path = os.path.join('config', 'config.yaml')
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
except ImportError:
    print("\nError: PyYAML module not found. Please install it with:")
    print("  pip install pyyaml")
    sys.exit(1)
except FileNotFoundError:
    print(f"\nError: Config file not found at {config_path}")
    sys.exit(1)

# Import necessary components
try:
    from src.database.models import get_session, Summary, ProcessedContent
    from src.mail_handling.sender import EmailSender
    from src.summarize.generator import SummaryGenerator
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'send_pending_summaries.log'))
    ]
)
logger = logging.getLogger(__name__)

def send_pending_summaries(choice=None):
    """Find and send any pending summaries."""
    print("\nLetterMonstr - Sending Pending Summaries")
    print("=====================================")
    
    try:
        # Initialize the email sender
        email_sender = EmailSender(config['summary'])
        
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Query unsent summaries
            unsent_summaries = session.query(Summary).filter_by(sent=False).order_by(Summary.id.desc()).all()
            
            if not unsent_summaries:
                print("\nNo unsent summaries found in the database.")
                return
            
            print(f"\nFound {len(unsent_summaries)} unsent summaries.")
            
            # If there's more than one summary, we should merge them
            if len(unsent_summaries) > 1:
                print(f"\nMerging {len(unsent_summaries)} summaries into a single email...")
                
                # Collect all summary texts
                all_summary_texts = []
                summary_ids = []
                
                # Filter out problematic summaries
                problematic_indicators = [
                    "NO MEANINGFUL NEWSLETTER CONTENT TO SUMMARIZE",
                    "No meaningful content",
                    "I'm unable to provide a newsletter summary",
                    "content to summarize",
                    "The only information provided is a subject line"
                ]
                
                # Sort summaries by creation date, newest first
                sorted_summaries = sorted(unsent_summaries, key=lambda x: x.creation_date or datetime.now(), reverse=True)
                
                for summary in sorted_summaries:
                    # Skip problematic summaries
                    if any(indicator in summary.summary_text for indicator in problematic_indicators):
                        print(f"Skipping problematic summary ID {summary.id} - contains error messages")
                        # Mark as sent so it doesn't get included again
                        summary.sent = True
                        summary.sent_date = datetime.now()
                        continue
                    
                    # Skip empty summaries
                    if not summary.summary_text or len(summary.summary_text.strip()) < 100:
                        print(f"Skipping empty or very short summary ID {summary.id}")
                        # Mark as sent so it doesn't get included again
                        summary.sent = True
                        summary.sent_date = datetime.now()
                        continue
                    
                    all_summary_texts.append(summary.summary_text)
                    summary_ids.append(summary.id)
                
                # If we've filtered out all summaries, bail out
                if not all_summary_texts:
                    print("\nAfter filtering, no valid summaries remain to send.")
                    session.commit()
                    return
                
                # Create a merged summary with clear section headers
                merged_summary = "# LetterMonstr Combined Newsletter Summary\n\n"
                
                for i, summary_text in enumerate(all_summary_texts):
                    # Only add section headers if there's more than one summary
                    if len(all_summary_texts) > 1:
                        merged_summary += f"## Summary {i+1}\n\n"
                    
                    merged_summary += summary_text.strip()
                    if i < len(all_summary_texts) - 1:
                        merged_summary += "\n\n" + "-" * 40 + "\n\n"
                
                # Now send the merged summary
                print("\nSending merged summary...")
                result = email_sender.send_summary(merged_summary)
                
                if result:
                    print("Successfully sent merged summary")
                    # Mark all summaries as sent
                    for summary_id in summary_ids:
                        print(f"Marking summary ID {summary_id} as sent...")
                        summary = session.query(Summary).filter_by(id=summary_id).first()
                        if summary:
                            summary.sent = True
                            summary.sent_date = datetime.now()
                    session.commit()
                else:
                    print("Failed to send merged summary")
                
                return
            
            # If a specific choice was provided via command line
            if choice is not None:
                if choice.lower() == 'all':
                    # Send all summaries (just one at a time since we've already handled multiple summaries above)
                    print("\nSending all unsent summaries...")
                    for summary in unsent_summaries:
                        print(f"\nSending summary ID: {summary.id}...")
                        result = email_sender.send_summary(summary.summary_text, summary.id)
                        if result:
                            print(f"Successfully sent summary ID: {summary.id}")
                        else:
                            print(f"Failed to send summary ID: {summary.id}")
                    return
                elif choice.isdigit():
                    # Send a specific summary by ID
                    summary_id = int(choice)
                    summary = next((s for s in unsent_summaries if s.id == summary_id), None)
                    
                    if not summary:
                        print(f"\nNo unsent summary found with ID: {summary_id}")
                        return
                    
                    print(f"\nSending summary ID: {summary.id}...")
                    result = email_sender.send_summary(summary.summary_text, summary.id)
                    if result:
                        print(f"Successfully sent summary ID: {summary.id}")
                    else:
                        print(f"Failed to send summary ID: {summary.id}")
                    return
            
            # Interactive mode
            print("\nAvailable summaries:")
            for i, summary in enumerate(unsent_summaries):
                summary_type = summary.summary_type
                creation_date = summary.creation_date.strftime('%Y-%m-%d %H:%M')
                print(f"{i+1}. ID: {summary.id} - {summary_type} summary created on {creation_date}")
            
            choice = input("\nEnter the number of the summary to send (or 'a' for all): ")
            
            if choice.lower() == 'a':
                # Send all summaries
                for summary in unsent_summaries:
                    print(f"\nSending summary ID: {summary.id}...")
                    result = email_sender.send_summary(summary.summary_text, summary.id)
                    if result:
                        print(f"Successfully sent summary ID: {summary.id}")
                    else:
                        print(f"Failed to send summary ID: {summary.id}")
            elif choice.isdigit() and 1 <= int(choice) <= len(unsent_summaries):
                # Send the selected summary
                idx = int(choice) - 1
                summary = unsent_summaries[idx]
                print(f"\nSending summary ID: {summary.id}...")
                result = email_sender.send_summary(summary.summary_text, summary.id)
                if result:
                    print(f"Successfully sent summary ID: {summary.id}")
                else:
                    print(f"Failed to send summary ID: {summary.id}")
            else:
                print("Invalid choice. No summaries sent.")
        
        except Exception as e:
            logger.error(f"Error sending pending summaries: {e}", exc_info=True)
            print(f"\nError: {str(e)}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error initializing components: {e}", exc_info=True)
        print(f"\nError: {str(e)}")
        
if __name__ == "__main__":
    # Check if a command line argument was provided
    if len(sys.argv) > 1:
        send_pending_summaries(sys.argv[1])
    else:
        send_pending_summaries() 