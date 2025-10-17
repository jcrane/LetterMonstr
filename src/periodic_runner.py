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
import functools
from datetime import datetime, timedelta
from sqlalchemy import text
import random
from sqlalchemy.exc import OperationalError


# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Import required modules
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import components
from src.fetch_process import run_periodic_fetch, PeriodicFetcher
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

# Define a retry decorator for database operations
def db_retry(max_retries=5, retry_delay=0.5):
    """Decorator that retries database operations on lock errors."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            last_exception = None
            current_delay = retry_delay

            while attempt <= max_retries:
                try:
                    # Clear any previous session if it exists in kwargs
                    if 'session' in kwargs and kwargs['session'] is not None:
                        try:
                            kwargs['session'].close()
                        except:
                            pass
                        kwargs['session'] = None

                    # Try the function
                    return func(*args, **kwargs)
                    
                except OperationalError as e:
                    # Check if it's a database lock error
                    if "database is locked" in str(e).lower() and attempt < max_retries:
                        attempt += 1
                        
                        # Log the retry attempt
                        logger.warning(f"Database locked in {func.__name__}, retrying in {current_delay:.2f}s (attempt {attempt}/{max_retries})")
                        
                        # Wait with exponential backoff plus small random jitter to prevent thundering herd
                        jitter = random.uniform(0, 0.5)
                        time.sleep(current_delay + jitter)
                        
                        # Increase delay for next attempt with exponential backoff
                        current_delay *= 2
                        last_exception = e
                        
                    else:
                        # Not a lock error or max retries reached
                        if attempt > 0:
                            logger.error(f"Database operation in {func.__name__} failed after {attempt} retries: {e}")
                        else:
                            logger.error(f"Database error in {func.__name__}: {e}")
                        raise e
                        
                except Exception as e:
                    # For non-database errors, log and re-raise immediately
                    logger.error(f"Error in {func.__name__}: {e}")
                    raise e
            
            # If we exhausted all retries
            if last_exception:
                logger.error(f"Database remained locked after {max_retries} retries in {func.__name__}")
                raise last_exception
            else:
                raise RuntimeError(f"Failed to execute {func.__name__} after {max_retries} attempts for unknown reasons")
                
        return wrapper
    return decorator

# Define a transaction wrapper to ensure proper session handling
def with_db_transaction(func):
    """Decorator that handles database sessions and transactions properly."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Create a new session for each call
        session = None
        max_retries = 5
        retry_count = 0
        retry_delay = 1  # Start with 1 second delay
        
        while retry_count <= max_retries:
            try:
                # Create a fresh session for this attempt
                if session is not None:
                    try:
                        session.close()
                    except:
                        pass
                
                session = get_session()
                
                # Add the session to the kwargs
                kwargs['session'] = session
                
                # Call the function with the session
                result = func(*args, **kwargs)
                
                # Commit the transaction if everything went well
                session.commit()
                return result
                
            except OperationalError as e:
                # Handle database lock errors with retries
                if "database is locked" in str(e).lower() and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"Database locked in {func.__name__}, retrying in {retry_delay}s (attempt {retry_count}/{max_retries})")
                    
                    # Roll back any pending transaction
                    if session and hasattr(session, 'rollback'):
                        try:
                            session.rollback()
                        except:
                            pass
                    
                    # Wait before retrying with exponential backoff
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    # Re-raise if it's not a lock error or we've exhausted retries
                    logger.error(f"Database error in {func.__name__} after {retry_count} retries: {e}")
                    if session and hasattr(session, 'rollback'):
                        session.rollback()
                    raise
                    
            except Exception as e:
                # Rollback the transaction on any other error
                logger.error(f"Error in {func.__name__}: {e}")
                if session and hasattr(session, 'rollback'):
                    session.rollback()
                # Re-raise the exception
                raise e
                
            finally:
                # Always close the session to prevent connection leaks
                if session:
                    try:
                        session.close()
                    except:
                        pass
    
    return wrapper

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
    time_window = current_time >= todays_delivery_time and current_time < tomorrows_delivery_time
    time_match = abs((current_time - todays_delivery_time).total_seconds() / 60) <= 15  # Within 15 minutes of delivery time
    
    logger.info(f"Time window check: {time_window} (within {todays_delivery_time} to {tomorrows_delivery_time})")
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
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    session = get_session(db_path)
    has_content = False
    
    try:
        # Check if there are any unsummarized content items
        unsummarized_count = session.query(ProcessedContent).filter_by(is_summarized=False).count()
        logger.info(f"Found {unsummarized_count} unsummarized content items")
        has_content = unsummarized_count > 0
        
        # If no unsummarized content, check for any content from the last 24 hours
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

@db_retry(max_retries=5)
@with_db_transaction
def has_content_to_summarize(session=None):
    """Check if there's unsummarized content in the database."""
    try:
        # Check if there are any unsummarized content items
        unsummarized_count = session.query(ProcessedContent).filter_by(is_summarized=False).count()
        
        if unsummarized_count > 0:
            logger.info(f"Found {unsummarized_count} unsummarized content items")
            return True
        else:
            logger.info("No unsummarized content found")
            return False
    except Exception as e:
        logger.error(f"Error checking for unsummarized content: {e}", exc_info=True)
        return False

@db_retry(max_retries=5)
@with_db_transaction
def generate_and_send_summary(force=False, session=None):
    """Generate and send a summary if there's content to summarize."""
    # Load configuration
    config = load_config()
    
    # Check if we should send a summary
    send_now = should_send_summary(config, force)
    
    try:
        # Check if there are any unsent summaries to retry
        retry_summaries = session.query(Summary).filter(
            Summary.sent == False,
            Summary.retry_count < 3  # Limit retries
        ).order_by(Summary.creation_date.desc()).all()
        
        if retry_summaries:
            logger.info(f"Found {len(retry_summaries)} unsent summaries to retry")
            
            # Initialize components for retry
            email_sender = EmailSender(config['summary'])
            email_fetcher = EmailFetcher(config['email'])
            
            # Try to resend each summary
            for summary in retry_summaries:
                logger.info(f"Retrying summary ID: {summary.id}, attempt {summary.retry_count + 1}")
                
                try:
                    # Check if it's time to deliver based on scheduled time or force flag
                    if not send_now and not force:
                        logger.info(f"Not scheduled delivery time yet, will retry summary ID: {summary.id} later")
                        continue
                    
                    # Increment retry count
                    summary.retry_count += 1
                    session.flush()  # Flush changes but don't commit yet
                    
                    # Send the email
                    status = email_sender.send_summary(
                        summary.summary_text,
                        summary.id
                    )
                    
                    if status:
                        # Mark as sent if successful
                        summary.sent = True
                        summary.sent_date = datetime.now()
                        
                        # Mark associated content as summarized
                        content_ids = []
                        for content in summary.content_items:
                            content.is_summarized = True
                            content_ids.append(content.id)
                        
                        # Get associated emails to mark as read in Gmail
                        emails_to_mark = []
                        content_items = session.query(ProcessedContent).filter(
                            ProcessedContent.id.in_(content_ids),
                            ProcessedContent.email_id.isnot(None)
                        ).all()
                        
                        for item in content_items:
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
                        
                        logger.info("All database records updated after successful retry")
                        
                        # Return so we don't generate a new summary
                        return
                except Exception as e:
                    logger.error(f"Error sending summary: {e}", exc_info=True)
        
        # If we get here, all retries have failed or there were no retries
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
        
        # Check if we're at or near the scheduled delivery time
        current_time = datetime.now()
        delivery_time_str = config['summary']['delivery_time']
        delivery_hour, delivery_minute = map(int, delivery_time_str.split(':'))
        
        # Create today's delivery time for comparison
        todays_delivery_time = datetime(
            current_time.year, 
            current_time.month, 
            current_time.day, 
            delivery_hour, 
            delivery_minute
        )
        
        # Check if we're within 15 minutes of the configured delivery time
        time_diff = abs((current_time - todays_delivery_time).total_seconds() / 60)
        is_delivery_window = time_diff <= 15
        
        # Only check for recent summaries if we're not in the delivery window
        if not is_delivery_window and not force:
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
        elif is_delivery_window:
            logger.info(f"In delivery window (±15 minutes of {delivery_hour:02d}:{delivery_minute:02d}), will generate and send summary")
        elif force:
            logger.info("Force flag is set, will generate and send summary regardless of previous summaries")
        
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
                
                # If summary_text is a dictionary (from Claude API response), extract the actual text
                if isinstance(summary_text, dict):
                    logger.info("Summary returned as dictionary, extracting text content")
                    if 'summary' in summary_text:
                        summary_text = summary_text['summary']
                    elif 'content' in summary_text:
                        summary_text = summary_text['content']
                    else:
                        # Convert the entire dict to a string as fallback
                        summary_text = str(summary_text)
                
                # Ensure summary_text is a string
                if not isinstance(summary_text, str):
                    summary_text = str(summary_text)
                    logger.info(f"Converted non-string summary to string: {type(summary_text)}")

                # Check if the summary just indicates there's no content
                try:
                    is_empty_summary = any(indicator in summary_text.lower() for indicator in no_content_indicators)
                except Exception as e:
                    logger.error(f"Error checking if summary is empty: {e}, summary_text type: {type(summary_text)}")
                    # If we can't check, assume it's not empty
                    is_empty_summary = False
                
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
    except Exception as e:
        logger.error(f"Error generating and sending summary: {e}", exc_info=True)

@db_retry(max_retries=5)
@with_db_transaction
def reset_incorrectly_summarized_content(session=None):
    """Find and reset content that was incorrectly marked as summarized but not included in any summary."""
    try:
        # Find the latest summary
        latest_summary = session.query(Summary).filter(
            Summary.sent == True
        ).order_by(Summary.sent_date.desc()).first()
        
        if not latest_summary:
            logger.info("No summaries found, nothing to reset")
            return 0
            
        # Get the creation date of the latest summary
        latest_summary_date = latest_summary.creation_date
        
        # Find all content that was processed after the last summary
        # but is marked as summarized
        incorrectly_summarized = session.query(ProcessedContent).filter(
            ProcessedContent.date_processed > latest_summary_date,
            ProcessedContent.is_summarized == True
        ).all()
        
        if not incorrectly_summarized:
            logger.info("No incorrectly summarized content found")
            return 0
            
        # Reset the summarized flag
        for item in incorrectly_summarized:
            item.is_summarized = False
            
        # Commit the changes
        session.commit()
        
        logger.info(f"Reset summarized flag for {len(incorrectly_summarized)} content items processed after {latest_summary_date}")
        return len(incorrectly_summarized)
        
    except Exception as e:
        logger.error(f"Error resetting summarized content: {e}", exc_info=True)
        return 0

def validate_connections_ready():
    """Validate that all required connections are ready before running tasks.
    
    Returns:
        bool: True if connections are ready, False otherwise
    """
    try:
        # Check network connectivity
        import socket
        try:
            socket.gethostbyname('gmail.com')
        except socket.gaierror:
            logger.warning("Network not ready - DNS resolution failed")
            return False
        
        # Test IMAP connection
        config = load_config()
        try:
            from src.mail_handling.fetcher import EmailFetcher
            fetcher = EmailFetcher(config['email'])
            # Try to connect
            mail = fetcher.connect()
            if mail:
                # Close it immediately, we just wanted to test
                try:
                    mail.logout()
                except:
                    pass
                logger.info("✓ IMAP connection validated")
                return True
            else:
                logger.warning("IMAP connection failed")
                return False
        except Exception as e:
            logger.warning(f"IMAP connection validation failed: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error validating connections: {e}", exc_info=True)
        return False

@db_retry(max_retries=5)
def run_periodic_tasks():
    """Run periodic tasks for fetching emails and generating summaries."""
    logger.info("Running periodic tasks...")
    
    # Validate connections are ready before proceeding
    if not validate_connections_ready():
        logger.warning("⚠️  Connections not ready, skipping this run")
        return
    
    # Load configuration
    config = load_config()
    
    try:
        # Run fetch and process
        logger.info("Running periodic fetch and process...")
        fetcher = PeriodicFetcher(config)
        fetcher.fetch_and_process()
        
        # Reset any content that was incorrectly marked as summarized
        reset_incorrectly_summarized_content()
        
        # Check if it's time to generate and send a summary
        logger.info("Checking if it's time to generate and send a summary...")
        generate_and_send_summary(force=False)
        
        logger.info("✓ Periodic tasks completed successfully")
    except Exception as e:
        logger.error(f"❌ Error running periodic tasks: {e}", exc_info=True)

def check_network_ready(max_wait_seconds=30):
    """Check if network is ready after wake, with timeout.
    
    Args:
        max_wait_seconds: Maximum time to wait for network
        
    Returns:
        bool: True if network is ready, False if timeout
    """
    import socket
    
    start_time = time.time()
    logger.info("Checking network readiness...")
    
    while (time.time() - start_time) < max_wait_seconds:
        try:
            # Try to resolve a common DNS name
            socket.gethostbyname('gmail.com')
            logger.info("Network is ready")
            return True
        except socket.gaierror:
            # Network not ready yet, wait a bit
            time.sleep(2)
    
    logger.warning(f"Network not ready after {max_wait_seconds} seconds")
    return False

def setup_scheduler():
    """Set up the scheduler based on configuration with robust sleep recovery."""
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
    
    # Keep the scheduler running with enhanced sleep detection
    logger.info("Starting scheduler with sleep/wake detection")
    last_check_time = time.time()
    consecutive_errors = 0
    max_consecutive_errors = 3
    
    while True:
        try:
            current_time = time.time()
            time_diff = current_time - last_check_time
            
            # If more than 3 minutes have passed since last check,
            # it's likely the system was sleeping (reduced from 5 for faster detection)
            if time_diff > 180:  # 3 minutes in seconds
                logger.warning(f"⚠️  SLEEP DETECTED: {time_diff:.1f} seconds ({time_diff/60:.1f} minutes) since last check")
                
                # Wait for network to be ready before attempting recovery
                logger.info("Waiting for network to be ready after wake...")
                network_ready = check_network_ready(max_wait_seconds=30)
                
                if not network_ready:
                    logger.error("Network not ready after wake, will retry on next cycle")
                    last_check_time = time.time()
                    time.sleep(60)
                    continue
                
                # Give the system a moment to fully stabilize
                logger.info("Network ready, waiting 5 seconds for system to stabilize...")
                time.sleep(5)
                
                logger.info("🔄 Running recovery tasks after wake...")
                
                # Clear and reset the scheduler
                schedule.clear()
                logger.info("Cleared old scheduler jobs")
                
                # Re-setup the scheduler with fresh jobs
                if fetch_interval == 1:
                    schedule.every().hour.do(run_periodic_fetch)
                    logger.info("✓ Re-scheduled fetch and process to run every hour")
                else:
                    schedule.every(fetch_interval).hours.do(run_periodic_fetch)
                    logger.info(f"✓ Re-scheduled fetch and process to run every {fetch_interval} hours")
                
                # Re-schedule summary check
                schedule.every(15).minutes.do(generate_and_send_summary)
                logger.info("✓ Re-scheduled summary check to run every 15 minutes")
                
                # Calculate and log how many scheduled runs were missed
                missed_fetch_runs = int(time_diff / (fetch_interval * 3600))
                missed_summary_checks = int(time_diff / (15 * 60))
                
                if missed_fetch_runs > 0 or missed_summary_checks > 0:
                    logger.info(f"📊 Estimated missed runs during sleep: {missed_fetch_runs} fetch runs, {missed_summary_checks} summary checks")
                
                # Run tasks immediately to catch up after sleep
                logger.info("🚀 Running catch-up tasks after sleep...")
                try:
                    run_periodic_tasks()
                    logger.info("✓ Catch-up tasks completed successfully")
                    consecutive_errors = 0  # Reset error counter on success
                except Exception as e:
                    logger.error(f"❌ Error running catch-up tasks: {e}", exc_info=True)
                    # Don't fail completely, just log and continue
                
                logger.info("✓ Sleep recovery completed")
            
            # Normal scheduler operation
            schedule.run_pending()
            last_check_time = time.time()
            consecutive_errors = 0  # Reset error counter on successful cycle
            time.sleep(60)
            
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"❌ Error in scheduler loop (attempt {consecutive_errors}/{max_consecutive_errors}): {e}", exc_info=True)
            
            # If we've had too many consecutive errors, something is seriously wrong
            if consecutive_errors >= max_consecutive_errors:
                logger.critical(f"💥 Too many consecutive errors ({consecutive_errors}), system may need restart")
                # Wait longer before retrying
                time.sleep(600)  # Wait 10 minutes before retrying
                consecutive_errors = 0  # Reset to give it another chance
            else:
                # Wait before trying again to avoid excessive error logging
                time.sleep(120)  # Wait 2 minutes before retrying
            
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
    else:
        # Check for unsent content at startup
        logger.info("Checking for unsent content at startup...")
        generate_and_send_summary(force=False)
        
    # Use the setup_scheduler function to handle all scheduling
    setup_scheduler()

if __name__ == "__main__":
    main() 