#!/usr/bin/env python3
"""
Force Process Unread Emails - LetterMonstr.

This script forces processing of ALL unread emails in the inbox, regardless of whether 
they've been previously processed or not. Use this if emails are being skipped when they
shouldn't be.
"""

import os
import sys
import logging
from datetime import datetime
import json
import hashlib

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
    from src.mail_handling.fetcher import EmailFetcher
    from src.mail_handling.parser import EmailParser
    from src.crawl.crawler import WebCrawler
    from src.summarize.processor import ContentProcessor
    from src.summarize.generator import SummaryGenerator
    from src.mail_handling.sender import EmailSender
    from src.database.models import get_session, Summary, ProcessedEmail, ProcessedContent
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    print("Please ensure all dependencies are installed.")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'force_process_unread.log'))
    ]
)
logger = logging.getLogger(__name__)

def force_process_unread():
    """Force process all unread emails regardless of database status."""
    print("\nLetterMonstr - Force Process Unread Emails")
    print("=========================================")
    
    try:
        # Initialize components
        email_fetcher = EmailFetcher(config['email'])
        email_parser = EmailParser()
        web_crawler = WebCrawler(config['content'])
        content_processor = ContentProcessor(config['content'])
        summary_generator = SummaryGenerator(config['llm'])
        email_sender = EmailSender(config['summary'])
        
        # Modified version of the EmailFetcher fetch_new_emails method to ignore the database
        # and just fetch all unread emails directly
        print("\nFetching all unread emails (ignoring database)...")
        unread_emails = email_fetcher.fetch_raw_unread_emails()
        
        if not unread_emails:
            print("No unread emails found in the inbox. Nothing to process.")
            return
        
        print(f"Found {len(unread_emails)} unread emails.")
        
        # Get user confirmation to continue
        confirm = input(f"\nProcess these {len(unread_emails)} emails? (y/n): ")
        if confirm.lower() != 'y':
            print("Operation cancelled.")
            return
        
        # Process emails in batches
        batch_size = 5
        all_summaries = []
        all_successfully_processed = []
        
        for batch_idx in range(0, len(unread_emails), batch_size):
            batch = unread_emails[batch_idx:batch_idx + batch_size]
            print(f"\nProcessing batch {batch_idx//batch_size + 1} of {(len(unread_emails)-1)//batch_size + 1} ({len(batch)} emails)...")
            
            all_content = []
            successfully_processed = []
            
            for email in batch:
                try:
                    print(f"- Processing: {email['subject']}")
                    
                    # Parse email content
                    parsed_content = email_parser.parse(email)
                    
                    if not parsed_content:
                        print(f"  Warning: No content could be parsed from email: {email['subject']}")
                        continue
                    
                    # Extract and crawl links
                    links = email_parser.extract_links(parsed_content.get('content', ''), 
                                                     parsed_content.get('content_type', 'html'))
                    
                    print(f"  Found {len(links)} links to crawl...")
                    crawled_content = web_crawler.crawl(links)
                    
                    # Combine email content with crawled content
                    combined_content = {
                        'source': email['subject'],
                        'email_content': parsed_content,
                        'crawled_content': crawled_content,
                        'date': email['date']
                    }
                    
                    all_content.append(combined_content)
                    successfully_processed.append(email)
                    print(f"  Successfully processed with {len(crawled_content)} crawled items")
                except Exception as e:
                    logger.error(f"Error processing email {email['subject']}: {e}", exc_info=True)
                    print(f"  Error: {str(e)}")
            
            # Process and deduplicate content for this batch
            print("Deduplicating content...")
            processed_content = content_processor.process_and_deduplicate(all_content)
            
            # Generate summary for this batch
            try:
                print("Generating summary for this batch...")
                batch_summary = summary_generator.generate_summary(processed_content)
                if batch_summary:
                    all_summaries.append(batch_summary)
                    all_successfully_processed.extend(successfully_processed)
                    print("Summary generated successfully!")
            except Exception as e:
                logger.error(f"Error generating summary for batch {batch_idx//batch_size + 1}: {e}", exc_info=True)
                print(f"Error generating summary: {str(e)}")
        
        # Combine all batch summaries into one final summary
        if all_summaries:
            print(f"\nGenerated {len(all_summaries)} batch summaries, combining them...")
            
            # Use the summary generator to combine the summaries
            if len(all_summaries) == 1:
                combined_summary = all_summaries[0]
            else:
                # Use the dedicated combiner for multiple summaries
                combined_summary = summary_generator.combine_summaries(all_summaries)
            
            print("Summary combination complete!")
            
            # Ask if user wants to send summary now
            send_now = input("\nSend summary email now? (y/n): ")
            
            if send_now.lower() == 'y':
                print("\nSending summary email...")
                result = email_sender.send_summary(combined_summary)
                
                if result:
                    print("Summary email sent successfully!")
                    
                    # Mark emails as read and processed
                    update_db = input("\nMark these emails as processed in the database? (y/n): ")
                    
                    if update_db.lower() == 'y':
                        print(f"\nMarking {len(all_successfully_processed)} emails as processed...")
                        email_fetcher.mark_emails_as_processed(all_successfully_processed)
                        print("Emails marked as processed in the database.")
                    else:
                        print("Emails will remain unread and unprocessed in the database.")
                else:
                    print("Failed to send summary email.")
                    
                    # Save the summary to database
                    save_db = input("\nSave summary to database for later sending? (y/n): ")
                    
                    if save_db.lower() == 'y':
                        db_path = os.path.join('data', 'lettermonstr.db')
                        session = get_session(db_path)
                        
                        try:
                            # Save summary
                            summary = Summary(
                                summary_type="force_processed",
                                summary_text=combined_summary,
                                creation_date=datetime.now(),
                                sent=False,
                                is_forced=True  # Mark as a forced summary
                            )
                            session.add(summary)
                            session.commit()
                            print(f"\nSummary saved to database with ID: {summary.id}")
                            print("You can try sending it later with the send_pending_summaries.py script.")
                        except Exception as e:
                            logger.error(f"Error saving summary to database: {e}", exc_info=True)
                            print("Error saving summary to database.")
                        finally:
                            session.close()
            else:
                # Save summary to database
                print("\nSaving summary to database...")
                db_path = os.path.join('data', 'lettermonstr.db')
                session = get_session(db_path)
                
                try:
                    # Save summary
                    summary = Summary(
                        summary_type="force_processed",
                        summary_text=combined_summary,
                        creation_date=datetime.now(),
                        sent=False,
                        is_forced=True  # Mark as a forced summary
                    )
                    session.add(summary)
                    session.commit()
                    print(f"Summary saved to database with ID: {summary.id}")
                    print("You can send it later with the send_pending_summaries.py script.")
                except Exception as e:
                    logger.error(f"Error saving summary to database: {e}", exc_info=True)
                    print("Error saving summary to database.")
                finally:
                    session.close()
        else:
            print("\nNo summaries were generated. Please check the logs for errors.")
        
    except Exception as e:
        logger.error(f"Error force processing unread emails: {e}", exc_info=True)
        print(f"\nError: {str(e)}")

if __name__ == "__main__":
    force_process_unread() 