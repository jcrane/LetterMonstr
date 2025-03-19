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
from sqlalchemy import text

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
    day_check = False
    if frequency == 'daily':
        day_check = True
    elif frequency == 'weekly':
        delivery_day = config['summary']['weekly_day']
        day_check = current_time.weekday() == delivery_day
    elif frequency == 'monthly':
        delivery_day = config['summary']['monthly_day']
        day_check = current_time.day == delivery_day
    
    # If it's not the right time or day, don't send a summary
    if not (time_check and day_check):
        return False
    
    # Check if we've already sent a summary today (regardless of whether it was forced or not)
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    try:
        # Look for ANY summaries created today that were sent
        today_date = current_time.strftime('%Y-%m-%d')
        today_start = datetime.strptime(f"{today_date} 00:00:00", "%Y-%m-%d %H:%M:%S")
        today_end = datetime.strptime(f"{today_date} 23:59:59", "%Y-%m-%d %H:%M:%S")
        
        already_sent_today = session.query(Summary).filter(
            Summary.sent == True,
            Summary.sent_date.between(today_start, today_end)
        ).count() > 0
        
        logger.info(f"Already sent summary today: {already_sent_today}")
        return not already_sent_today  # Send if we haven't already sent a summary today
    except Exception as e:
        logger.error(f"Error checking for existing summaries: {e}", exc_info=True)
        return False  # If there's an error, be cautious and don't send
    finally:
        session.close()

def has_content_to_summarize():
    """Check if there is content to summarize, either unsummarized or total content."""
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    try:
        # Get unsummarized content
        unsummarized_count = session.query(ProcessedContent).filter_by(summarized=False).count()
        
        # If we have unsummarized content, we can generate a summary
        if unsummarized_count > 0:
            return True
        
        # If no unsummarized content, check if we have any content at all
        total_content = session.query(ProcessedContent).count()
        processed_emails = session.query(ProcessedEmail).count()
        
        # If we have processed emails and content, we should still generate a summary
        # This handles the case where all content is marked as summarized but we still want to send a summary
        if processed_emails > 0 and total_content > 0:
            # In this case, we'll need to temporarily mark all content as unsummarized
            # to ensure it gets included in the summary
            logger.info(f"No unsummarized content found but {total_content} total content items exist")
            logger.info("Temporarily marking all content as unsummarized to ensure complete summary")
            
            # Update all content to be unsummarized
            session.query(ProcessedContent).update({ProcessedContent.summarized: False})
            session.commit()
            
            return True
            
        # No content to summarize
        return False
    except Exception as e:
        logger.error(f"Error checking for content to summarize: {e}", exc_info=True)
        return False
    finally:
        session.close()

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
    
    # Check if there's content to summarize
    if not has_content_to_summarize():
        logger.info("No content to summarize, skipping summary generation")
        return
    
    try:
        # Get database session
        db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # First check if we have any unsent summaries
            unsent_summaries = session.query(Summary).filter_by(sent=False).order_by(Summary.id.desc()).all()
            if unsent_summaries:
                logger.info(f"Found {len(unsent_summaries)} existing unsent summaries")
            
            # Get all unsummarized content
            unsummarized = session.query(ProcessedContent).filter_by(summarized=False).all()
            
            # Get total count for debugging
            total_content = session.query(ProcessedContent).count()
            processed_emails_count = session.query(ProcessedEmail).count()
            
            logger.info(f"Database status: {processed_emails_count} processed emails, {total_content} total content items, {len(unsummarized)} unsummarized")
            
            # Initialize components
            content_processor = ContentProcessor(config['content'])
            summary_generator = SummaryGenerator(config['llm'])
            email_sender = EmailSender(config['summary'])
            email_fetcher = EmailFetcher(config['email'])
            
            # Flag to determine if we need to generate a new summary
            generate_new_summary = True
            
            # If we have no new content to summarize
            if not unsummarized:
                logger.info("No unsummarized content found")
                
                # If we have processed emails but no content, that could indicate a processing issue
                if processed_emails_count > 0 and total_content == 0:
                    logger.warning("There are processed emails but no content items - this may indicate an issue with email processing")
                
                # If we have existing unsent summaries, send those
                if unsent_summaries:
                    logger.info("Sending existing unsent summaries even though there's no new content")
                    generate_new_summary = False
                else:
                    # No unsummarized content and no unsent summaries - nothing to do
                    return
            
            if generate_new_summary:
                logger.info(f"Processing {len(unsummarized)} unsummarized content items")
                
                # Prepare content for summarization
                all_content = []
                emails_to_mark = []
                
                for item in unsummarized:
                    try:
                        # Parse the JSON content - it's stored as a string in the database
                        processed_content = item.processed_content
                        
                        # Parse the JSON string back into a dictionary
                        try:
                            import json
                            # If the processed_content is a string, try to parse it as JSON
                            if isinstance(processed_content, str):
                                processed_content = json.loads(processed_content)
                                logger.debug(f"Successfully parsed JSON from item {item.id}")
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing JSON for item {item.id}: {e}")
                            # Skip this item if we can't parse it
                            continue
                        
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
                
                # Check if summary actually contains meaningful content
                # Look for indication phrases that Claude uses when no content is found
                no_content_indicators = [
                    "I don't see any actual newsletter content",
                    "no actual text",
                    "appears to be empty",
                    "content to summarize"
                ]
                
                # Check if the summary just indicates there's no content
                is_empty_summary = any(indicator in summary_text for indicator in no_content_indicators)
                
                # Also check if final content items have meaningful content
                has_meaningful_content = False
                min_content_length = 100  # Minimum characters for meaningful content
                
                for item in final_content:
                    content = item.get('content', '')
                    if isinstance(content, str) and len(content) > min_content_length:
                        has_meaningful_content = True
                        break
                
                if is_empty_summary or not has_meaningful_content:
                    logger.warning("Not sending summary email as there is no meaningful content to summarize")
                    # Update status but don't send email
                    for item in unsummarized:
                        item.summarized = True
                    session.commit()
                    logger.info(f"Marked {len(unsummarized)} empty content items as summarized without sending email")
                    return
                
                # Create summary record
                new_summary = Summary(
                    period_start=min(item.date_processed for item in unsummarized),
                    period_end=max(item.date_processed for item in unsummarized),
                    summary_type=config['summary']['frequency'],
                    summary_text=summary_text,
                    creation_date=datetime.now(),
                    sent=False,
                    is_forced=False  # This is a scheduled summary, not forced
                )
                session.add(new_summary)
                session.flush()  # To get the ID
                
                # Now add to our list of unsent summaries
                unsent_summaries.append(new_summary)
            
            # At this point, we have at least one summary to send
            # If we have multiple summaries, merge them
            if len(unsent_summaries) > 1:
                logger.info(f"Merging {len(unsent_summaries)} summaries into a single email")
                
                # Collect all summary texts, filtering out problematic ones
                all_summary_texts = []
                summary_ids = []
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
                        logger.info(f"Skipping problematic summary ID {summary.id} - contains error messages")
                        # Mark as sent so it doesn't get included again
                        summary.sent = True
                        summary.sent_date = datetime.now()
                        continue
                    
                    # Skip empty summaries
                    if not summary.summary_text or len(summary.summary_text.strip()) < 100:
                        logger.info(f"Skipping empty or very short summary ID {summary.id}")
                        # Mark as sent so it doesn't get included again
                        summary.sent = True
                        summary.sent_date = datetime.now()
                        continue
                    
                    all_summary_texts.append(summary.summary_text)
                    summary_ids.append(summary.id)
                
                # If we've filtered out all summaries, bail out
                if not all_summary_texts:
                    logger.warning("After filtering, no valid summaries remain to send")
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
                
                # Send the merged summary
                logger.info("Sending merged summary email...")
                result = email_sender.send_summary(merged_summary)
                
                if result:
                    logger.info("Merged summary email sent successfully")
                    
                    # Mark all summaries as sent
                    for summary in unsent_summaries:
                        summary.sent = True
                        summary.sent_date = datetime.now()
                    
                    # Mark all content as summarized
                    for item in unsummarized:
                        item.summarized = True
                    
                    # Mark emails as read in Gmail
                    if emails_to_mark and config['email'].get('mark_read_after_summarization', True):
                        email_fetcher.mark_emails_as_processed(emails_to_mark)
                        logger.info(f"Marked {len(emails_to_mark)} emails as read in Gmail")
                    
                    # Commit all changes
                    session.commit()
                    logger.info("All database records updated")
                else:
                    logger.error("Failed to send merged summary email")
            else:
                # Only one summary to send
                summary = unsent_summaries[0]
                
                # Send the summary
                logger.info(f"Sending summary email (ID: {summary.id})...")
                result = email_sender.send_summary(summary.summary_text, summary.id)
                
                if result:
                    logger.info("Summary email sent successfully")
                    
                    # Mark the summary as sent
                    summary.sent = True
                    summary.sent_date = datetime.now()
                    
                    # Mark all content as summarized
                    for item in unsummarized:
                        item.summarized = True
                    
                    # Mark emails as read in Gmail
                    if emails_to_mark and config['email'].get('mark_read_after_summarization', True):
                        email_fetcher.mark_emails_as_processed(emails_to_mark)
                        logger.info(f"Marked {len(emails_to_mark)} emails as read in Gmail")
                    
                    # Commit all changes
                    session.commit()
                    logger.info("All database records updated")
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