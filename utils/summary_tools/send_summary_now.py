#!/usr/bin/env python3
"""
Send Summary Now - LetterMonstr.

This script immediately processes all unread emails in the inbox,
generates a summary, and sends it right away, without changing the scheduled settings.
"""

import os
import sys
import logging
from datetime import datetime

# Set up the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Load config
import yaml
config_path = os.path.join('config', 'config.yaml')
with open(config_path, 'r') as file:
    config = yaml.safe_load(file)

# Import necessary components
from src.mail_handling.fetcher import EmailFetcher
from src.mail_handling.parser import EmailParser
from src.crawl.crawler import WebCrawler
from src.summarize.processor import ContentProcessor
from src.summarize.generator import SummaryGenerator
from src.mail_handling.sender import EmailSender
from src.database.models import get_session, Summary, ProcessedEmail

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'send_summary_now.log'))
    ]
)
logger = logging.getLogger(__name__)

def process_and_send_now():
    """Process all unread emails and send a summary immediately."""
    print("\nLetterMonstr - Send Summary Now")
    print("==============================")
    
    try:
        # Initialize components
        email_fetcher = EmailFetcher(config['email'])
        email_parser = EmailParser()
        web_crawler = WebCrawler(config['content'])
        content_processor = ContentProcessor(config['content'])
        summary_generator = SummaryGenerator(config['llm'])
        email_sender = EmailSender(config['summary'])
        
        # Fetch all unread emails
        print("\nFetching unread emails...")
        unread_emails = email_fetcher.fetch_new_emails()
        
        if not unread_emails:
            print("No unread emails found in the inbox. Nothing to process.")
            return
        
        print(f"Found {len(unread_emails)} unread emails.")
        
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
            
            # Send the summary
            print("\nSending summary email...")
            result = email_sender.send_summary(combined_summary)
            
            if result:
                print("Summary email sent successfully!")
                
                # Mark emails as read and processed
                if all_successfully_processed:
                    print(f"\nMarking {len(all_successfully_processed)} emails as read...")
                    email_fetcher.mark_emails_as_processed(all_successfully_processed)
                    print("All emails marked as read.")
            else:
                print("Failed to send summary email.")
                
                # Save the summary to database even if sending fails
                db_path = os.path.join('data', 'lettermonstr.db')
                session = get_session(db_path)
                
                try:
                    # Save summary
                    summary = Summary(
                        summary_type=f"{config['summary']['frequency']}_manual",
                        summary_text=combined_summary,
                        creation_date=datetime.now(),
                        sent=False
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
            print("\nNo summaries were generated. Please check the logs for errors.")
        
    except Exception as e:
        logger.error(f"Error processing and sending summary: {e}", exc_info=True)
        print(f"\nError: {str(e)}")

if __name__ == "__main__":
    process_and_send_now() 