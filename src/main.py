#!/usr/bin/env python3
"""
LetterMonstr - Newsletter aggregator and summarizer

This is the main entry point for the LetterMonstr application.
"""

import os
import sys
import logging
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Make sure the correct Python path is set
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)

# Ensure Python looks in standard library first
# and then in our project directory
sys.path = [p for p in sys.path if p not in (current_dir, project_root)]
sys.path.append(project_root)
sys.path.append(current_dir)

# Import standard library modules first to avoid conflicts
import email as email_lib
from email.header import decode_header

# Handle optional dependency imports with better error messages
try:
    import yaml
except ImportError:
    print("Error: PyYAML package is missing. Please install it with:")
    print("  pip install pyyaml")
    sys.exit(1)

try:
    import schedule
except ImportError:
    print("Error: schedule package is missing. Please install it with:")
    print("  pip install schedule")
    sys.exit(1)

# Database imports
try:
    from src.database.models import init_db, get_session, ProcessedEmail, Summary, ProcessedContent
except ImportError as e:
    print(f"Error: Database module is missing: {e}")
    print("  pip install sqlalchemy")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Local imports
from src.mail_handling.fetcher import EmailFetcher
from src.mail_handling.parser import EmailParser
from src.crawl.crawler import WebCrawler
from src.summarize.processor import ContentProcessor
from src.summarize.generator import SummaryGenerator
from src.mail_handling.sender import EmailSender
from src.fetch_process import run_periodic_fetch  # Import our new function

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('data', 'lettermonstr.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global config
config = None

def load_config():
    """Load configuration from YAML file."""
    global config
    config_path = os.path.join('config', 'config.yaml')
    
    try:
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def process_newsletters():
    """Process newsletters and generate summaries."""
    if not config:
        load_config()
    
    logger.info("Starting newsletter processing")
    
    try:
        # Check if we're using periodic fetching mode
        if config['email'].get('periodic_fetch', False):
            logger.info("Using periodic fetching mode - processing accumulated content")
            process_accumulated_content()
        else:
            logger.info("Using traditional mode - fetching all emails at once")
            process_traditional()
            
    except Exception as e:
        logger.error(f"Error processing newsletters: {e}", exc_info=True)

def process_accumulated_content():
    """Process content that has been accumulated through periodic fetching."""
    try:
        # Initialize required components
        content_processor = ContentProcessor(config['content'])
        summary_generator = SummaryGenerator(config['llm'])
        email_sender = EmailSender(config['summary'])
        email_fetcher = EmailFetcher(config['email'])
        
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Get all unsummarized content
            unsummarized = session.query(ProcessedContent).filter_by(is_summarized=False).all()
            
            if not unsummarized:
                logger.info("No unsummarized content found")
                return False
            
            logger.info(f"Found {len(unsummarized)} unsummarized content items")
            
            # Prepare content for summarization
            all_content = []
            emails_to_mark = set()  # Use a set to avoid duplicates
            
            for item in unsummarized:
                try:
                    # Add processed content to the list
                    all_content.append(item.processed_content)
                    
                    # Track emails to mark as read if configured to do so
                    if not config['email'].get('mark_read_after_summarization', True):
                        continue
                        
                    # If content is associated with an email, track it for marking as read
                    if item.email_id:
                        email = item.email
                        if email and email.message_id:
                            emails_to_mark.add((
                                email.message_id,
                                email.subject,
                                email.sender,
                                email.date_received
                            ))
                except Exception as e:
                    logger.error(f"Error processing content item {item.id}: {e}", exc_info=True)
            
            # Convert set back to list of dicts for processing
            emails_to_mark_list = [
                {
                    'message_id': msg_id,
                    'subject': subject,
                    'sender': sender,
                    'date': date
                }
                for msg_id, subject, sender, date in emails_to_mark
            ]
            
            # Process and deduplicate content
            processed_content = content_processor.process_and_deduplicate(all_content)
            
            # Generate summary
            logger.info("Generating summary...")
            combined_summary = summary_generator.generate_summary(processed_content)
            
            if not combined_summary:
                logger.error("Failed to generate summary")
                return False
            
            # Send the combined summary if it's time
            if should_send_summary():
                # Send the email
                email_sender.send_summary(combined_summary)
                logger.info("Summary email sent successfully")
                
                # Mark all emails as read if configured to do so
                if emails_to_mark_list and config['email'].get('mark_read_after_summarization', True):
                    email_fetcher.mark_emails_as_processed(emails_to_mark_list)
                    logger.info(f"Marked {len(emails_to_mark_list)} emails as processed")
                
                # Mark all processed content as summarized
                for item in unsummarized:
                    item.is_summarized = True
                
                session.commit()
                logger.info(f"Marked {len(unsummarized)} content items as summarized")
            else:
                # Save the summary for later sending but don't mark emails as read
                logger.info("Not sending summary yet - waiting for scheduled delivery time")
                try:
                    # Save summary to database
                    summary = Summary(
                        summary_type=config['summary']['frequency'],
                        summary_text=combined_summary,
                        creation_date=datetime.now(),
                        sent=False
                    )
                    session.add(summary)
                    session.commit()
                    summary_id = summary.id
                    
                    logger.info(f"Summary saved to database with ID: {summary_id} for later sending")
                    logger.info("Emails will remain unread until the summary is sent")
                except Exception as e:
                    logger.error(f"Error saving summary to database: {e}", exc_info=True)
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error processing accumulated content: {e}", exc_info=True)

def process_traditional():
    """Process newsletters using the traditional approach (all at once)."""
    try:
        # Initialize all components
        email_fetcher = EmailFetcher(config['email'])
        email_parser = EmailParser(config['content'])
        web_crawler = WebCrawler(config['content'])
        content_processor = ContentProcessor(config['content'])
        summary_generator = SummaryGenerator(config['llm'])
        email_sender = EmailSender(config['summary'])
        
        # Fetch new emails
        emails = email_fetcher.fetch_new_emails()
        
        if not emails:
            logger.info("No new emails to process")
            return
        
        logger.info(f"Fetched {len(emails)} new emails")
        
        # Process emails in batches
        batch_size = config.get('processing', {}).get('batch_size', 5)
        
        # Find already processed emails
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Filtering out already processed emails
            emails_to_process = []
            for email in emails:
                message_id = email.get('message_id', '')
                if not message_id:
                    # If no message ID, we can't track it, so process anyway
                    emails_to_process.append(email)
                    continue
                
                # Check if we've already processed this email
                processed = session.query(ProcessedEmail).filter_by(message_id=message_id).first()
                if not processed:
                    emails_to_process.append(email)
                    
                    # Create a database record for this email
                    processed_email = ProcessedEmail(
                        message_id=message_id,
                        subject=email.get('subject', 'No Subject'),
                        sender=email.get('sender', 'Unknown'),
                        date_received=email.get('date', datetime.now()),
                        processed=False
                    )
                    session.add(processed_email)
                    session.commit()
                    
                    # Add the database ID to the email object for reference
                    email['db_id'] = processed_email.id
            
            # If we're in limited functionality mode, just return after email fetching
            if config.get('limited_functionality', False):
                # Just test email fetching
                logger.info(f"Found {len(emails_to_process)} new emails to process (limited functionality mode)")
                
                # Print summary of fetched emails
                for email in emails_to_process:
                    logger.info(f"Email: {email['subject']} from {email['sender']}")
                
                return
            
            # Process the emails that haven't been processed yet
            if not emails_to_process:
                logger.info("All fetched emails have already been processed")
                return
            
            logger.info(f"Processing {len(emails_to_process)} new emails")
            
            # Split emails into batches
            batches = [emails_to_process[i:i + batch_size] for i in range(0, len(emails_to_process), batch_size)]
            logger.info(f"Split into {len(batches)} batches of size {batch_size}")
            
            all_summaries = []
            all_successfully_processed = []
            
            # Process each batch
            for batch_idx, batch in enumerate(batches):
                logger.info(f"Processing batch {batch_idx+1} of {len(batches)} with {len(batch)} emails")
                
                all_content = []
                successfully_processed = []
                
                for email in batch:
                    try:
                        # Parse email content (now with DB ID)
                        parsed_content = email_parser.parse(email)
                        
                        if parsed_content:
                            # Log the content size for debugging
                            content_size = len(parsed_content.get('content', ''))
                            logger.debug(f"Parsed content size for '{email['subject']}': {content_size} characters")
                            
                            if content_size < 100:
                                logger.warning(f"Parsed content is very small for '{email['subject']}': only {content_size} characters")
                        else:
                            logger.warning(f"No parsed content returned for '{email['subject']}'")
                            continue
                        
                        # Extract and crawl links
                        links = email_parser.extract_links(parsed_content.get('content', ''), 
                                                          parsed_content.get('content_type', 'html'))
                        crawled_content = web_crawler.crawl(links)
                        
                        # Combine email content with crawled content
                        combined_content = {
                            'source': email['subject'],
                            'email_content': parsed_content,
                            'crawled_content': crawled_content,
                            'date': email['date']
                        }
                        
                        # Log the combined content for debugging
                        logger.debug(f"Combined content created for '{email['subject']}' with email content and {len(crawled_content)} crawled items")
                        
                        all_content.append(combined_content)
                        
                        # Mark this email as successfully processed
                        successfully_processed.append(email)
                    except Exception as e:
                        logger.error(f"Error processing email {email['subject']}: {e}", exc_info=True)
                
                # Process and deduplicate content for this batch
                processed_content = content_processor.process_and_deduplicate(all_content)
                
                # Generate summary for this batch
                try:
                    batch_summary = summary_generator.generate_summary(processed_content)
                    if batch_summary:
                        all_summaries.append(batch_summary)
                        # Add successfully processed emails to the overall list
                        all_successfully_processed.extend(successfully_processed)
                except Exception as e:
                    logger.error(f"Error generating summary for batch {batch_idx+1}: {e}", exc_info=True)
            
            # Combine all batch summaries into one final summary
            if all_summaries:
                logger.info(f"Generated {len(all_summaries)} batch summaries, combining them")
                
                # Use the summary generator to combine the summaries
                if len(all_summaries) == 1:
                    combined_summary = all_summaries[0]
                else:
                    # Use the dedicated combiner for multiple summaries
                    combined_summary = summary_generator.combine_summaries(all_summaries)
                
                # Send the combined summary if it's time
                if should_send_summary():
                    email_sender.send_summary(combined_summary)
                    logger.info("Summary email sent successfully")
                    
                    # Mark all successfully processed emails as read and processed
                    if all_successfully_processed:
                        email_fetcher.mark_emails_as_processed(all_successfully_processed)
                        logger.info(f"Marked {len(all_successfully_processed)} emails as processed")
                else:
                    # Save the summary for later sending but don't mark emails as read
                    logger.info("Not sending summary yet - waiting for scheduled delivery time")
                    try:
                        # Save summary to database
                        summary = Summary(
                            summary_type=config['summary']['frequency'],
                            summary_text=combined_summary,
                            creation_date=datetime.now(),
                            sent=False
                        )
                        session.add(summary)
                        session.commit()
                        summary_id = summary.id
                        
                        logger.info(f"Summary saved to database with ID: {summary_id} for later sending")
                        logger.info("Emails will remain unread until the summary is sent")
                    except Exception as e:
                        logger.error(f"Error saving summary to database: {e}", exc_info=True)
            else:
                logger.warning("No summaries were generated from any batch")
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error processing newsletters in traditional mode: {e}", exc_info=True)

def should_send_summary():
    """Determine if it's time to send a summary based on configuration."""
    current_time = datetime.now()
    frequency = config['summary']['frequency']
    delivery_time_str = config['summary']['delivery_time']
    
    # Parse delivery time
    delivery_hour, delivery_minute = map(int, delivery_time_str.split(':'))
    
    # Create today's delivery time for comparison
    todays_delivery_time = datetime(
        current_time.year, 
        current_time.month, 
        current_time.day, 
        delivery_hour, 
        delivery_minute
    )
    
    # Check if we're at or past today's delivery time but before tomorrow's delivery time
    tomorrows_delivery_time = todays_delivery_time + timedelta(days=1)
    time_window = current_time >= todays_delivery_time and current_time < tomorrows_delivery_time
    time_match = abs((current_time - todays_delivery_time).total_seconds() / 60) <= 15  # Within 15 minutes of delivery time
    
    logger.info(f"Time window check: {time_window} (comparing {current_time} with window {todays_delivery_time} to {tomorrows_delivery_time})")
    logger.info(f"Exact time match (±15 min): {time_match}")
    
    # Check if it's the right day based on frequency
    day_check = False
    if frequency == 'daily':
        day_check = True
    elif frequency == 'weekly':
        delivery_day = config['summary']['weekly_day']
        day_check = current_time.weekday() == delivery_day
    elif frequency == 'monthly':
        delivery_day = config['summary']['monthly_day']
        day_check = current_time.day == delivery_day
    
    logger.info(f"Day check result for {frequency} frequency: {day_check}")
    
    # Check if there's unsummarized content
    db_path = os.path.join('data', 'lettermonstr.db')
    session = get_session(db_path)
    has_content = False
    
    try:
        # Check if there are any unsummarized content items
        unsummarized_count = session.query(ProcessedContent).filter_by(is_summarized=False).count()
        logger.info(f"Found {unsummarized_count} unsummarized content items")
        has_content = unsummarized_count > 0
        
        # If no unsummarized content and we're at the delivery time, check for any content from the last 24 hours
        if not has_content and time_match and day_check:
            yesterday = current_time - timedelta(days=1)
            recent_content_count = session.query(ProcessedContent).filter(
                ProcessedContent.date_processed >= yesterday
            ).count()
            
            logger.info(f"Found {recent_content_count} content items from the last 24 hours")
            has_content = recent_content_count > 0
    finally:
        session.close()
    
    # If we're at the exact delivery time window (±15 min) on the right day and there is content, always send
    if time_match and day_check and has_content:
        logger.info("At delivery time window on the correct day with content available - will send summary")
        return True
        
    # If we have unsummarized content and we're in the broader time window on the right day, send it
    if time_window and day_check and has_content:
        logger.info("In delivery time window on the correct day with unsummarized content - will send summary")
        return True
        
    logger.info(f"Not sending summary. time_window: {time_window}, time_match: {time_match}, day_check: {day_check}, has_content: {has_content}")
    return False

def schedule_jobs():
    """Schedule jobs based on configuration."""
    delivery_time = config['summary']['delivery_time']
    
    # If periodic fetching is enabled, use the new approach
    if config['email'].get('periodic_fetch', False):
        logger.info("Periodic fetching is enabled - using periodic_runner.py instead")
        logger.info("Please run periodic_runner.py to start the periodic fetcher")
        sys.exit(0)
    
    # Schedule the daily job at the delivery time
    frequency = config['summary']['frequency']
    
    if frequency == 'daily':
        logger.info(f"Scheduling daily run at {delivery_time}")
        schedule.every().day.at(delivery_time).do(process_newsletters)
    elif frequency == 'weekly':
        day = config['summary']['weekly_day']
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_name = days[day]
        logger.info(f"Scheduling weekly run on {day_name} at {delivery_time}")
        getattr(schedule.every(), day_name).at(delivery_time).do(process_newsletters)
    elif frequency == 'monthly':
        day = config['summary']['monthly_day']
        logger.info(f"Scheduling monthly run on day {day} at {delivery_time}")
        schedule.every().month.at(f"{day:02d} {delivery_time}").do(process_newsletters)
    else:
        logger.error(f"Unknown frequency: {frequency}")
        sys.exit(1)
    
    # Run once immediately
    logger.info("Running once immediately")
    process_newsletters()
    
    # Run the scheduler
    logger.info("Starting scheduler")
    while True:
        schedule.run_pending()
        time.sleep(60)

def main():
    """Main entry point."""
    # Initialize database
    init_db()
    
    # Load configuration
    load_config()
    
    # Log startup
    logger.info("LetterMonstr starting up")
    
    # Check for unsent summaries or content that should be summarized
    logger.info("Checking for unsent content at startup...")
    
    try:
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Check for unsent summaries first
            unsent_summaries = session.query(Summary).filter_by(sent=False).all()
            if unsent_summaries:
                logger.info(f"Found {len(unsent_summaries)} unsent summaries, sending them...")
                
                # Initialize email sender
                email_sender = EmailSender(config['summary'])
                
                # Send each unsent summary
                for summary in unsent_summaries:
                    try:
                        logger.info(f"Sending summary {summary.id} created on {summary.creation_date}...")
                        email_sender.send_summary(summary.summary_text)
                        
                        # Update summary status
                        summary.sent = True
                        summary.sent_date = datetime.now()
                        
                        session.commit()
                        logger.info(f"Summary {summary.id} sent successfully")
                    except Exception as e:
                        logger.error(f"Error sending summary {summary.id}: {e}", exc_info=True)
            else:
                logger.info("No unsent summaries found")
                
                # Check for unsummarized content
                unsummarized_content = session.query(ProcessedContent).filter_by(is_summarized=False).all()
                if unsummarized_content:
                    logger.info(f"Found {len(unsummarized_content)} unsummarized content items")
                    process_newsletters()
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error checking for unsent summaries: {e}", exc_info=True)
    
    # Run the scheduler
    schedule_jobs()

if __name__ == "__main__":
    main() 