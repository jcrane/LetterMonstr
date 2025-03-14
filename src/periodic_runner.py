#!/usr/bin/env python3
"""
Periodic Runner for LetterMonstr.

This script runs the periodic fetcher at configurable intervals
and handles the final summary generation and sending at the scheduled time.
"""

import os
import sys
import time
import yaml
import logging
import schedule
from datetime import datetime

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Import required modules
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import components
from src.fetch_process import run_periodic_fetch
from src.database.models import get_session, ProcessedContent, Summary, ProcessedEmail
from src.summarize.processor import ContentProcessor
from src.summarize.generator import SummaryGenerator
from src.mail_handling.sender import EmailSender
from src.mail_handling.fetcher import EmailFetcher

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(project_root, 'data', 'lettermonstr_periodic.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """Load configuration from YAML file."""
    config_path = os.path.join(project_root, 'config', 'config.yaml')
    
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def should_send_summary(config):
    """Determine if it's time to send a summary based on configuration."""
    current_time = datetime.now()
    frequency = config['summary']['frequency']
    delivery_time_str = config['summary']['delivery_time']
    
    # Parse delivery time
    delivery_hour, delivery_minute = map(int, delivery_time_str.split(':'))
    
    # Check if we're at or past the delivery time
    time_check = (current_time.hour > delivery_hour) or \
                 (current_time.hour == delivery_hour and current_time.minute >= delivery_minute)
    
    # Check if it's the right day based on frequency
    if frequency == 'daily':
        return time_check
    elif frequency == 'weekly':
        delivery_day = config['summary']['weekly_day']
        return current_time.weekday() == delivery_day and time_check
    elif frequency == 'monthly':
        delivery_day = config['summary']['monthly_day']
        return current_time.day == delivery_day and time_check
    
    return False

def generate_and_send_summary():
    """Generate and send summary at scheduled time."""
    logger.info("Checking if it's time to generate and send summary...")
    
    # Load configuration
    config = load_config()
    
    # Check if it's time to send a summary
    if not should_send_summary(config):
        logger.info("Not time to send summary yet")
        return
    
    logger.info("It's time to generate and send summary")
    
    try:
        # Get database session
        db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Get all unsummarized content
            unsummarized = session.query(ProcessedContent).filter_by(summarized=False).all()
            
            # Get total count for debugging
            total_content = session.query(ProcessedContent).count()
            processed_emails_count = session.query(ProcessedEmail).count()
            
            logger.info(f"Database status: {processed_emails_count} processed emails, {total_content} total content items, {len(unsummarized)} unsummarized")
            
            if not unsummarized:
                logger.info("No unsummarized content found")
                
                # If we have processed emails but no content, that could indicate a processing issue
                if processed_emails_count > 0 and total_content == 0:
                    logger.warning("There are processed emails but no content items - this may indicate an issue with email processing")
                    
                return
            
            logger.info(f"Found {len(unsummarized)} unsummarized content items")
            
            # Initialize components
            content_processor = ContentProcessor(config['content'])
            summary_generator = SummaryGenerator(config['llm'])
            email_sender = EmailSender(config['summary'])
            email_fetcher = EmailFetcher(config['email'])
            
            # Prepare content for summarization
            all_content = []
            emails_to_mark = []
            
            for item in unsummarized:
                try:
                    # Parse the JSON content
                    processed_content = item.processed_content
                    
                    # Add to the list for summarization
                    all_content.append(processed_content)
                    
                    # Get associated email if any
                    if item.email and item.email.message_id:
                        emails_to_mark.append({
                            'message_id': item.email.message_id,
                            'subject': item.email.subject,
                            'sender': item.email.sender,
                            'date': item.email.date_received
                        })
                except Exception as e:
                    logger.error(f"Error processing content item {item.id}: {e}", exc_info=True)
            
            # Deduplicate and process content
            final_content = content_processor.process_and_deduplicate(all_content)
            
            # Generate summary
            logger.info("Generating summary...")
            summary_text = summary_generator.generate_summary(final_content)
            
            if not summary_text:
                logger.error("Failed to generate summary")
                return
            
            # Create summary record
            summary = Summary(
                period_start=min(item.date_processed for item in unsummarized),
                period_end=max(item.date_processed for item in unsummarized),
                summary_type=config['summary']['frequency'],
                summary_text=summary_text,
                creation_date=datetime.now(),
                sent=False
            )
            session.add(summary)
            session.flush()  # To get the ID
            
            # Send the summary
            logger.info("Sending summary email...")
            result = email_sender.send_summary(summary_text, summary.id)
            
            if result:
                logger.info("Summary email sent successfully")
                
                # Mark emails as read in Gmail
                if emails_to_mark:
                    logger.info(f"Marking {len(emails_to_mark)} emails as read in Gmail")
                    email_fetcher.mark_emails_as_processed(emails_to_mark)
                
                # Mark all content as summarized
                for item in unsummarized:
                    item.summarized = True
                    item.summary_id = summary.id
                
                session.commit()
                logger.info(f"Marked {len(unsummarized)} content items as summarized")
            else:
                logger.error("Failed to send summary email")
                
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error generating and sending summary: {e}", exc_info=True)

def run_periodic_tasks():
    """Run both periodic fetcher and check if it's time to send summary."""
    # Run fetch and process first
    run_periodic_fetch()
    
    # Then check if it's time for summary
    generate_and_send_summary()

def setup_scheduler():
    """Set up the scheduler based on configuration."""
    # Load configuration
    config = load_config()
    
    # Check if periodic fetching is enabled
    if not config['email'].get('periodic_fetch', False):
        logger.info("Periodic fetching is disabled in config")
        return
    
    # Get the fetch interval
    fetch_interval = config['email'].get('fetch_interval_hours', 1)
    
    # Schedule periodic fetching
    if fetch_interval == 1:
        schedule.every().hour.do(run_periodic_fetch)
        logger.info("Scheduled fetch and process to run every hour")
    else:
        schedule.every(fetch_interval).hours.do(run_periodic_fetch)
        logger.info(f"Scheduled fetch and process to run every {fetch_interval} hours")
    
    # Schedule summary check to run every 15 minutes
    schedule.every(15).minutes.do(generate_and_send_summary)
    logger.info("Scheduled summary check to run every 15 minutes")
    
    # Run immediately once
    run_periodic_tasks()
    
    # Keep the scheduler running
    logger.info("Starting scheduler")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    setup_scheduler() 