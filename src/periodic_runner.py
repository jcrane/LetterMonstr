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
from datetime import datetime, timedelta
from sqlalchemy import text
import random

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

def should_send_summary(config, force=False):
    """Determine if it's time to send a summary based on configuration."""
    # If force is True, bypass all time checks
    if force:
        logger.info("Force flag is set, bypassing time checks")
        return True
        
    current_time = datetime.now()
    frequency = config['summary']['frequency']
    delivery_time_str = config['summary']['delivery_time']
    
    # Parse delivery time
    delivery_hour, delivery_minute = map(int, delivery_time_str.split(':'))
    
    # Get system time from multiple sources for debugging
    system_time = time.localtime()
    # Format delivery time with leading zero for minutes
    formatted_delivery_time = f"{delivery_hour:02d}:{delivery_minute:02d}"
    logger.info(f"Current time: {current_time}, System time: {time.strftime('%Y-%m-%d %H:%M:%S', system_time)}, Delivery time: {formatted_delivery_time}")
    
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
    time_check = current_time >= todays_delivery_time and current_time < tomorrows_delivery_time
    
    logger.info(f"Time check result: {time_check} (comparing {current_time} with delivery window {todays_delivery_time} to {tomorrows_delivery_time})")
    
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
    
    # If it's not the right time or day, don't send a summary
    if not (time_check and day_check):
        logger.info(f"Not sending summary. time_check: {time_check}, day_check: {day_check}")
        return False
    
    # Check if there's unsummarized content to send
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    try:
        # Check if there are any unsummarized content items
        unsummarized_count = session.query(ProcessedContent).filter_by(is_summarized=False).count()
        logger.info(f"Found {unsummarized_count} unsummarized content items")
        
        if unsummarized_count > 0:
            # There's unsummarized content, so we should send a summary
            logger.info("Found unsummarized content, will send summary")
            return True
            
        # If no unsummarized content, check if more than 24 hours have passed since last summary
        latest_summary = session.query(Summary).filter(
            Summary.sent == True
        ).order_by(Summary.sent_date.desc()).first()
        
        if latest_summary and latest_summary.sent_date:
            hours_since_last_summary = (datetime.now() - latest_summary.sent_date).total_seconds() / 3600
            logger.info(f"Hours since last summary: {hours_since_last_summary:.1f}")
            
            # Send a summary if it's been more than 24 hours since the last one
            if hours_since_last_summary >= 24:
                logger.info("More than 24 hours since last summary, will send a summary")
                return True
        else:
            # No summaries sent yet, so we should send one
            logger.info("No summaries have been sent yet, will send a summary")
            return True
            
        logger.info("No unsummarized content and recent summary exists, won't send summary")
        return False
    except Exception as e:
        logger.error(f"Error checking for content to summarize: {e}", exc_info=True)
        return False  # If there's an error, be cautious and don't send
    finally:
        session.close()

def has_content_to_summarize():
    """Check if there is content to summarize, either unsummarized or total content."""
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    try:
        # Get unsummarized content
        unsummarized_count = session.query(ProcessedContent).filter_by(is_summarized=False).count()
        
        # Get total content count right away
        total_content = session.query(ProcessedContent).count()
        
        # If we have unsummarized content, we can generate a summary
        if unsummarized_count > 0:
            return True, unsummarized_count, total_content
        
        # If no unsummarized content, check if we have any content at all
        processed_emails = session.query(ProcessedEmail).count()
        
        # If we have processed emails and content, we should still generate a summary
        # This handles the case where all content is marked as summarized but we still want to send a summary
        if processed_emails > 0 and total_content > 0:
            # In this case, we'll need to temporarily mark all content as unsummarized
            # to ensure it gets included in the summary
            logger.info(f"No unsummarized content found but {total_content} total content items exist")
            logger.info("Temporarily marking all content as unsummarized to ensure complete summary")
            
            # Update all content to be unsummarized
            session.query(ProcessedContent).update({ProcessedContent.is_summarized: False})
            session.commit()
            
            return True, total_content, total_content
            
        # No content to summarize
        return False
    except Exception as e:
        logger.error(f"Error checking for content to summarize: {e}", exc_info=True)
        return False
    finally:
        session.close()

def generate_and_send_summary(force=False):
    """Generate and send summary at scheduled time."""
    logger.info("Checking if it's time to generate and send summary...")
    
    # Load configuration
    config = load_config()
    
    # Check if it's time to send a summary
    if not should_send_summary(config, force):
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
            # First check if we have any unsent summaries that should be retried
            current_time = datetime.now()
            unsent_summaries = session.query(Summary).filter_by(sent=False).order_by(Summary.id.desc()).all()
            
            # Check if any of these summaries are ready for retry
            retry_candidates = []
            for summary in unsent_summaries:
                # Skip if we've reached max retries
                if summary.retry_count >= summary.max_retries:
                    logger.warning(f"Summary {summary.id} has reached max retries ({summary.max_retries}). Last error: {summary.error_message}")
                    continue
                
                # Calculate backoff time (exponential with jitter)
                if summary.last_retry_time:
                    # Exponential backoff: 5min, 10min, 20min, 40min, 80min
                    backoff_minutes = 5 * (2 ** summary.retry_count)
                    # Add some randomness (jitter) to prevent all retries happening at once
                    jitter = random.randint(0, 60)  # 0-60 seconds of jitter
                    backoff_seconds = backoff_minutes * 60 + jitter
                    
                    # Check if enough time has passed since the last retry
                    time_since_last_retry = (current_time - summary.last_retry_time).total_seconds()
                    if time_since_last_retry < backoff_seconds:
                        logger.info(f"Summary {summary.id} will be retried after backoff period (retry {summary.retry_count+1}/{summary.max_retries}, waiting {backoff_seconds}s, elapsed {time_since_last_retry}s)")
                        continue
                
                # This summary is ready for retry
                retry_candidates.append(summary)
            
            if retry_candidates:
                logger.info(f"Found {len(retry_candidates)} unsent summaries ready for retry")
                
                # Initialize components for sending
                email_sender = EmailSender(config['summary'])
                email_fetcher = EmailFetcher(config['email'])
                
                # Attempt to send each retry candidate
                for summary in retry_candidates:
                    logger.info(f"Retrying summary {summary.id} (attempt {summary.retry_count+1}/{summary.max_retries})")
                    
                    # Increment retry count and update last retry time
                    summary.retry_count += 1
                    summary.last_retry_time = current_time
                    
                    # Try to send the summary
                    try:
                        # Send the summary
                        logger.info(f"Sending summary email (ID: {summary.id})...")
                        result = email_sender.send_summary(summary.summary_text, summary.id)
                        
                        if result:
                            logger.info(f"Summary email {summary.id} sent successfully on retry {summary.retry_count}")
                            
                            # Mark the summary as sent
                            summary.sent = True
                            summary.sent_date = current_time
                            summary.error_message = None
                            
                            # Find unsummarized content associated with this time period
                            if summary.period_start and summary.period_end:
                                unsummarized = session.query(ProcessedContent).filter(
                                    ProcessedContent.is_summarized == False,
                                    ProcessedContent.date_processed >= summary.period_start,
                                    ProcessedContent.date_processed <= summary.period_end
                                ).all()
                            else:
                                # Fall back to all unsummarized content
                                unsummarized = session.query(ProcessedContent).filter_by(is_summarized=False).all()
                            
                            # Mark all content as summarized
                            for item in unsummarized:
                                item.is_summarized = True
                                item.summary_id = summary.id
                            
                            # Get message IDs for any emails associated with this content
                            emails_to_mark = []
                            for item in unsummarized:
                                if item.email and item.email.message_id:
                                    emails_to_mark.append({
                                        'message_id': item.email.message_id,
                                        'subject': item.email.subject,
                                        'sender': item.email.sender,
                                        'date': item.email.date_received
                                    })
                            
                            # Mark emails as read in Gmail
                            if emails_to_mark and config['email'].get('mark_read_after_summarization', True):
                                email_fetcher.mark_emails_as_processed(emails_to_mark)
                                logger.info(f"Marked {len(emails_to_mark)} emails as read in Gmail")
                            
                            # Commit all changes
                            session.commit()
                            logger.info("All database records updated after successful retry")
                            
                            # Return since we've successfully sent a summary
                            return
                        else:
                            # Record the failure
                            summary.error_message = "Failed to send email"
                            session.commit()
                            logger.error(f"Failed to send summary email {summary.id} on retry {summary.retry_count}")
                    except Exception as e:
                        # Record the error
                        summary.error_message = str(e)[:500]  # Truncate long error messages
                        session.commit()
                        logger.error(f"Error sending summary {summary.id} on retry {summary.retry_count}: {e}", exc_info=True)
            
            # If we get here, either there were no retries or all retries failed
            # Continue with creating a new summary if needed
            
            # Get fresh unsummarized content
            unsummarized = session.query(ProcessedContent).filter_by(is_summarized=False).all()
            
            # Get total count for debugging
            total_content = session.query(ProcessedContent).count()
            processed_emails_count = session.query(ProcessedEmail).count()
            
            logger.info(f"Database status: {processed_emails_count} processed emails, {total_content} total content items, {len(unsummarized)} unsummarized")
            
            # If there's no unsummarized content, no need to continue
            if not unsummarized:
                logger.info("No unsummarized content to process")
                return
                
            # Initialize components
            content_processor = ContentProcessor(config['content'])
            summary_generator = SummaryGenerator(config['llm'])
            email_sender = EmailSender(config['summary'])
            email_fetcher = EmailFetcher(config['email'])
            
            # Check if we've already sent a summary for recent content
            today = datetime.now().date()
            recent_summaries = session.query(Summary).filter(
                Summary.sent == True,
                Summary.creation_date >= today
            ).order_by(Summary.creation_date.desc()).first()
            
            # If we found a recent summary, just mark the content as summarized and exit
            if recent_summaries is not None:
                logger.info(f"Recent summary (ID: {recent_summaries.id}) already covers current content. Marking content as summarized.")
                for item in unsummarized:
                    item.is_summarized = True
                session.commit()
                logger.info(f"Marked {len(unsummarized)} content items as summarized without sending new summary")
                return
            
            # Flag to determine if we need to generate a new summary
            generate_new_summary = True
            
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
                
                # Estimate token count (roughly 4 chars per token)
                total_chars = sum(len(item.get('content', '')) for item in final_content)
                estimated_tokens = total_chars // 4
                logger.info(f"Estimated total tokens: {estimated_tokens}")
                
                # Set a safe batch limit (less than Claude's 200k limit)
                TOKEN_BATCH_LIMIT = 25000
                
                # Generate summary
                logger.info("Generating summary...")
                
                try:
                    # Check if we need to batch the content
                    if estimated_tokens > TOKEN_BATCH_LIMIT:
                        logger.info(f"Content too large ({estimated_tokens} tokens), splitting into batches...")
                        
                        # Sort content by date (newest first) to process most recent first
                        sorted_content = sorted(final_content, key=lambda x: x.get('date', datetime.now()), reverse=True)
                        
                        batches = []
                        current_batch = []
                        current_batch_chars = 0
                        
                        # Create batches based on token estimates
                        for item in sorted_content:
                            item_chars = len(item.get('content', ''))
                            item_tokens = item_chars // 4
                            
                            # If adding this item would exceed our limit, start a new batch
                            if current_batch_chars // 4 + item_tokens > TOKEN_BATCH_LIMIT and current_batch:
                                batches.append(current_batch)
                                current_batch = [item]
                                current_batch_chars = item_chars
                            else:
                                current_batch.append(item)
                                current_batch_chars += item_chars
                        
                        # Add the last batch if it has items
                        if current_batch:
                            batches.append(current_batch)
                        
                        logger.info(f"Split content into {len(batches)} batches")
                        
                        # Generate summaries for each batch
                        batch_summaries = []
                        for i, batch in enumerate(batches):
                            batch_tokens = sum(len(item.get('content', '')) for item in batch) // 4
                            logger.info(f"Generating summary for batch {i+1}/{len(batches)} ({batch_tokens} tokens)...")
                            try:
                                batch_summary = summary_generator.generate_summary(batch)
                                if batch_summary:
                                    batch_summaries.append(batch_summary)
                                    logger.info(f"Batch {i+1} summary generated successfully")
                                else:
                                    logger.warning(f"Failed to generate summary for batch {i+1}")
                            except Exception as e:
                                logger.error(f"Error generating summary for batch {i+1}: {e}", exc_info=True)
                                # Try with a smaller portion of the batch if possible
                                if len(batch) > 1:
                                    logger.info(f"Attempting to generate summary with half of batch {i+1}...")
                                    half_size = len(batch) // 2
                                    try:
                                        half_batch_summary = summary_generator.generate_summary(batch[:half_size])
                                        if half_batch_summary:
                                            batch_summaries.append(half_batch_summary)
                                            logger.info(f"Generated summary for first half of batch {i+1}")
                                        
                                        # Try the second half too
                                        second_half_summary = summary_generator.generate_summary(batch[half_size:])
                                        if second_half_summary:
                                            batch_summaries.append(second_half_summary)
                                            logger.info(f"Generated summary for second half of batch {i+1}")
                                    except Exception as e2:
                                        logger.error(f"Error generating summary for half of batch {i+1}: {e2}", exc_info=True)
                        
                        # Combine all batch summaries
                        if batch_summaries:
                            logger.info(f"Combining {len(batch_summaries)} batch summaries...")
                            if len(batch_summaries) == 1:
                                summary_text = batch_summaries[0]
                            else:
                                # Use the dedicated method to combine summaries
                                summary_text = summary_generator.combine_summaries(batch_summaries)
                            logger.info("Combined summary created successfully")
                        else:
                            raise Exception("No batch summaries were generated")
                    else:
                        # Content is small enough to summarize in one call
                        logger.info("Content size is within limits, generating summary in one call...")
                        summary_text = summary_generator.generate_summary(final_content)
                    
                    if not summary_text:
                        raise Exception("Failed to generate summary - empty result returned")
                    
                except Exception as e:
                    # Create a new summary record with the error, but don't mark content as summarized
                    error_message = f"Error generating summary: {str(e)}"
                    logger.error(error_message)
                    
                    new_summary = Summary(
                        period_start=min(item.date_processed for item in unsummarized),
                        period_end=max(item.date_processed for item in unsummarized),
                        summary_type=config['summary']['frequency'],
                        summary_text=error_message,
                        creation_date=datetime.now(),
                        sent=False,
                        is_forced=False,
                        retry_count=0,
                        last_retry_time=datetime.now(),
                        error_message=str(e)[:500]  # Truncate long error messages
                    )
                    session.add(new_summary)
                    session.commit()
                    logger.info(f"Created failed summary {new_summary.id} for retry later")
                    return
                
                # We have a valid summary text, create a new summary record
                try:
                    # Check if the summary indicates no meaningful content
                    no_content_indicators = [
                        "no meaningful content",
                        "no newsletter content",
                        "no content to summarize",
                        "no emails contained",
                        "no extractable content"
                    ]
                    
                    # Check if the summary just indicates there's no content
                    is_empty_summary = any(indicator in summary_text.lower() for indicator in no_content_indicators)
                    
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
                            item.is_summarized = True
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
                        is_forced=False,  # This is a scheduled summary, not forced
                        retry_count=0,
                        last_retry_time=datetime.now()
                    )
                    session.add(new_summary)
                    session.flush()  # To get the ID
                    
                    # Store content signatures for deduplication in future summaries
                    content_processor.store_summarized_content(new_summary.id, final_content)
                    
                    # Now try to send the summary immediately
                    logger.info(f"Sending summary email (ID: {new_summary.id})...")
                    result = email_sender.send_summary(summary_text, new_summary.id)
                    
                    if result:
                        logger.info("Summary email sent successfully")
                        
                        # Mark the summary as sent
                        new_summary.sent = True
                        new_summary.sent_date = datetime.now()
                        
                        # Mark all content as summarized
                        for item in unsummarized:
                            item.is_summarized = True
                            item.summary_id = new_summary.id
                        
                        # Mark emails as read in Gmail
                        if emails_to_mark and config['email'].get('mark_read_after_summarization', True):
                            email_fetcher.mark_emails_as_processed(emails_to_mark)
                            logger.info(f"Marked {len(emails_to_mark)} emails as read in Gmail")
                        
                        # Commit all changes
                        session.commit()
                        logger.info("All database records updated")
                    else:
                        # The summary is created but sending failed - will be retried later
                        new_summary.error_message = "Failed to send email"
                        session.commit()
                        logger.error("Failed to send summary email - will retry later")
                except Exception as e:
                    logger.error(f"Error creating or sending summary: {e}", exc_info=True)
                    # Don't mark content as summarized so we can try again later
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
    last_check_time = time.time()
    
    while True:
        try:
            current_time = time.time()
            time_diff = current_time - last_check_time
            
            # If more than 5 minutes have passed since last check,
            # it's likely the system was sleeping
            if time_diff > 300:  # 5 minutes in seconds
                logger.info(f"Detected possible system sleep: {time_diff:.1f} seconds since last check")
                logger.info("Running periodic fetch immediately to catch up")
                
                # Run tasks immediately to catch up after sleep
                run_periodic_fetch()
                
                # Also check if we need to send a summary
                generate_and_send_summary()
                
                # Calculate and log how many scheduled runs were missed
                missed_fetch_runs = int(time_diff / (fetch_interval * 3600))
                missed_summary_checks = int(time_diff / (15 * 60))
                
                if missed_fetch_runs > 0 or missed_summary_checks > 0:
                    logger.info(f"Estimated missed runs during sleep: {missed_fetch_runs} fetch runs, {missed_summary_checks} summary checks")
            
            # Normal scheduler operation
            schedule.run_pending()
            last_check_time = time.time()
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}", exc_info=True)
            # Wait before trying again to avoid excessive error logging
            time.sleep(300)  # Wait 5 minutes before retrying
            # Update last_check_time even after an error
            last_check_time = time.time()

def main():
    """Main entry point for the periodic runner."""
    # Load configuration
    config = load_config()
    
    # Check if force flag is passed
    force = len(sys.argv) > 1 and sys.argv[1] == '--force'
    
    if force:
        logger.info("Force flag detected, generating summary immediately")
        generate_and_send_summary(force=True)
        
    # Use the setup_scheduler function to handle all scheduling
    setup_scheduler()

if __name__ == "__main__":
    main() 