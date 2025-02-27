#!/usr/bin/env python3
"""
LetterMonstr - Newsletter aggregator and summarizer

This is the main entry point for the LetterMonstr application.
"""

import os
import sys
import logging
import time
from datetime import datetime
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
    from src.database.models import init_db, get_session, ProcessedEmail
except ImportError as e:
    print(f"Error: Database module is missing: {e}")
    print("  pip install sqlalchemy")
    sys.exit(1)

# Import application components with proper error handling
_has_components = True
try:
    from src.mail_handling.fetcher import EmailFetcher
    from src.mail_handling.parser import EmailParser
    from src.crawl.crawler import WebCrawler
    from src.summarize.processor import ContentProcessor
    from src.summarize.generator import SummaryGenerator
    from src.mail_handling.sender import EmailSender
except ImportError as e:
    _has_components = False
    print(f"Warning: Could not import a required component: {e}")
    print("Some functionality may be limited. Try reinstalling requirements:")
    print("  pip install -r requirements.txt")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data/lettermonstr.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config():
    """Load configuration from YAML file."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                             'config', 'config.yaml')
    
    # Check if config file exists
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found at {config_path}")
        print(f"\nError: Configuration file not found at {config_path}")
        print("\nPlease run the setup script first:")
        print("  python3 setup_config.py")
        sys.exit(1)
        
    try:
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def process_newsletters():
    """Process newsletters and generate summaries."""
    logger.info("Starting newsletter processing")
    
    try:
        # Initialize components
        email_fetcher = EmailFetcher(config['email'])
        
        # Test if other components are available
        if _has_components:
            email_parser = EmailParser()
            web_crawler = WebCrawler(config['content'])
            content_processor = ContentProcessor(config['content'])
            summary_generator = SummaryGenerator(config['llm'])
            email_sender = EmailSender(config['summary'])
            
            # Fetch emails
            emails = email_fetcher.fetch_new_emails()
            logger.info(f"Fetched {len(emails)} new emails")
            
            if not emails:
                logger.info("No new emails to process")
                return
            
            # Track successfully processed emails
            successfully_processed = []
            
            # FIRST: Save emails to database before processing
            session = get_session(os.path.join('data', 'lettermonstr.db'))
            try:
                saved_emails = []
                for email in emails:
                    try:
                        # Create a ProcessedEmail record but don't mark as processed yet
                        processed_email = ProcessedEmail(
                            message_id=email['message_id'],
                            subject=email['subject'],
                            sender=email['sender'],
                            date_received=email['date']
                            # Omit date_processed to indicate it's not fully processed
                        )
                        session.add(processed_email)
                        session.flush()  # Flush to get the ID without committing
                        
                        # Add the database ID to the email object
                        email['db_id'] = processed_email.id
                        saved_emails.append(email)
                        
                        logger.debug(f"Added email to database: {email['subject']} with ID {processed_email.id}")
                    except Exception as e:
                        logger.error(f"Error saving email {email['subject']} to database: {e}", exc_info=True)
                
                # Only commit if we successfully added all emails
                session.commit()
                logger.debug(f"Committed {len(saved_emails)} emails to database")
                
                # Now emails have IDs, process them
                emails = saved_emails
            except Exception as e:
                session.rollback()
                logger.error(f"Error in database transaction: {e}", exc_info=True)
            finally:
                session.close()
            
            # Process each email
            all_content = []
            for email in emails:
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
            
            # Process and deduplicate content
            processed_content = content_processor.process_and_deduplicate(all_content)
            
            # Generate summary
            summary = summary_generator.generate_summary(processed_content)
            
            # Send summary email if it's time
            if should_send_summary():
                email_sender.send_summary(summary)
                logger.info("Summary email sent successfully")
                
                # Mark all successfully processed emails as read and processed
                if successfully_processed:
                    email_fetcher.mark_emails_as_processed(successfully_processed)
                    logger.info(f"Marked {len(successfully_processed)} emails as processed")
        else:
            # Just test email fetching
            emails = email_fetcher.fetch_new_emails()
            logger.info(f"Fetched {len(emails)} new emails (limited functionality mode)")
            
            if not emails:
                logger.info("No new emails to process")
                return
            
            # Print summary of fetched emails
            for email in emails:
                logger.info(f"Email: {email['subject']} from {email['sender']}")
            
    except Exception as e:
        logger.error(f"Error processing newsletters: {e}", exc_info=True)

def should_send_summary():
    """Determine if it's time to send a summary based on configuration."""
    current_time = datetime.now()
    frequency = config['summary']['frequency']
    
    if frequency == 'daily':
        return True
    elif frequency == 'weekly':
        delivery_day = config['summary']['weekly_day']
        return current_time.weekday() == delivery_day
    elif frequency == 'monthly':
        delivery_day = config['summary']['monthly_day']
        return current_time.day == delivery_day
    return False

def schedule_jobs():
    """Schedule jobs based on configuration."""
    delivery_time = config['summary']['delivery_time']
    
    # Schedule newsletter processing
    schedule.every().day.at(delivery_time).do(process_newsletters)
    
    logger.info(f"Scheduled processing for every day at {delivery_time}")
    logger.info(f"Summary delivery frequency: {config['summary']['frequency']}")

def main():
    """Main entry point for the application."""
    global config
    
    print("\nLetterMonstr - Newsletter aggregator and summarizer")
    print("---------------------------------------------------")
    
    # Load environment variables
    load_dotenv()
    
    # Load configuration
    config = load_config()
    
    # Create data directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    
    # Initialize database
    if 'database' in config:
        init_db(config['database']['path'])
    else:
        init_db('data/lettermonstr.db')
    
    # Check if we're in limited functionality mode
    if not _has_components:
        print("\nRunning in limited functionality mode (some components are not available)")
        print("Only email fetching will be tested")
    
    # Schedule jobs
    schedule_jobs()
    
    # Do an initial processing
    logger.info("Performing initial processing")
    process_newsletters()
    
    # Keep the scheduler running
    logger.info("Starting scheduler")
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nExiting LetterMonstr...")
        sys.exit(0)

if __name__ == "__main__":
    main() 