#!/usr/bin/env python3
"""
Force Generate Summary for All Content - LetterMonstr.

This script forces generation of a summary for ALL content items
in the database, bypassing deduplication checks.
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
    from src.summarize.processor import ContentProcessor
    from src.summarize.generator import SummaryGenerator
    from src.mail_handling.sender import EmailSender
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'force_complete_summary.log'))
    ]
)
logger = logging.getLogger(__name__)

# Create a modified ContentProcessor class that skips cross-summary deduplication
class NoDedupeContentProcessor(ContentProcessor):
    """Content processor that skips cross-summary deduplication."""
    
    def _filter_previously_summarized(self, items):
        """Override to bypass cross-summary deduplication."""
        logger.info(f"BYPASSING cross-summary deduplication for {len(items)} items - including ALL content")
        return items

def force_generate_complete_summary():
    """Generate a new summary for ALL content items."""
    print("\nLetterMonstr - Force Generate Complete Summary (No Deduplication)")
    print("===============================================================")
    
    try:
        # Initialize components with no deduplication processor
        content_processor = NoDedupeContentProcessor(config['content'])
        summary_generator = SummaryGenerator(config['llm'])
        email_sender = EmailSender(config['summary'])
        
        # Get database session
        db_path = os.path.join('data', 'lettermonstr.db')
        session = get_session(db_path)
        
        try:
            # Get ALL processed content items
            all_content = session.query(ProcessedContent).all()
            
            if not all_content:
                print("\nNo content found in the database.")
                return
            
            print(f"Found {len(all_content)} content items.")
            
            # Prepare content in the format expected by the summary generator
            processed_content = []
            for item in all_content:
                # Extract the processed content from JSON
                try:
                    # Try to parse the processed_content JSON
                    item_content = json.loads(item.processed_content)
                except (json.JSONDecodeError, TypeError):
                    # If it's not valid JSON, use it as raw text
                    item_content = {
                        'source': item.source or "Untitled",
                        'content': item.processed_content,
                        'date': item.date_processed
                    }
                
                # Make sure it has the expected format
                if not isinstance(item_content, dict):
                    item_content = {
                        'source': item.source or "Untitled",
                        'content': str(item_content),
                        'date': item.date_processed
                    }
                
                # Ensure it has required fields
                if 'source' not in item_content:
                    item_content['source'] = item.source or "Untitled"
                if 'date' not in item_content:
                    item_content['date'] = item.date_processed
                
                processed_content.append(item_content)
            
            # Process content through our no-dedupe processor
            print("Processing content for summarization (with deduplication DISABLED)...")
            processed_content = content_processor.process_and_deduplicate(processed_content)
            
            # Estimate token count (roughly 4 chars per token)
            total_chars = sum(len(item.get('content', '')) for item in processed_content)
            estimated_tokens = total_chars // 4
            print(f"Estimated total tokens: {estimated_tokens}")
            
            # Set a safe batch limit (less than Claude's 200k limit)
            TOKEN_BATCH_LIMIT = 100000
            
            # Generate summary
            print("Generating summary...")
            try:
                # Check if we need to batch
                if estimated_tokens > TOKEN_BATCH_LIMIT:
                    print(f"Content too large ({estimated_tokens} tokens), splitting into batches...")
                    
                    # Sort content by date (newest first) to process most recent first
                    sorted_content = sorted(processed_content, key=lambda x: x.get('date', datetime.now()), reverse=True)
                    
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
                    
                    print(f"Split content into {len(batches)} batches")
                    
                    # Generate summaries for each batch
                    batch_summaries = []
                    for i, batch in enumerate(batches):
                        print(f"Generating summary for batch {i+1}/{len(batches)} ({sum(len(item.get('content', '')) for item in batch) // 4} tokens)...")
                        try:
                            batch_summary = summary_generator.generate_summary(batch)
                            if batch_summary:
                                batch_summaries.append(batch_summary)
                                print(f"Batch {i+1} summary generated successfully!")
                            else:
                                print(f"Failed to generate summary for batch {i+1}")
                        except Exception as e:
                            logger.error(f"Error generating summary for batch {i+1}: {e}")
                            print(f"Error generating summary for batch {i+1}: {str(e)}")
                            # Try with a smaller portion of the batch
                            if len(batch) > 1:
                                print(f"Attempting to generate summary with half of batch {i+1}...")
                                half_size = len(batch) // 2
                                try:
                                    half_batch_summary = summary_generator.generate_summary(batch[:half_size])
                                    if half_batch_summary:
                                        batch_summaries.append(half_batch_summary)
                                        print(f"Generated summary for first half of batch {i+1}")
                                    
                                    # Try the second half too
                                    second_half_summary = summary_generator.generate_summary(batch[half_size:])
                                    if second_half_summary:
                                        batch_summaries.append(second_half_summary)
                                        print(f"Generated summary for second half of batch {i+1}")
                                except Exception as e2:
                                    logger.error(f"Error generating summary for half of batch {i+1}: {e2}")
                                    print(f"Error generating summary for half of batch {i+1}: {str(e2)}")
                    
                    # Combine all batch summaries
                    if batch_summaries:
                        print("Combining batch summaries...")
                        if len(batch_summaries) == 1:
                            summary_text = batch_summaries[0]
                        else:
                            summary_text = summary_generator.combine_summaries(batch_summaries)
                        print("Combined summary created successfully!")
                    else:
                        print("No batch summaries were generated")
                        return
                else:
                    # Content is small enough to summarize in one go
                    print("Content size is within limits, generating summary in one call...")
                    summary_text = summary_generator.generate_summary(processed_content)
                    
                if not summary_text:
                    print("Failed to generate summary - empty result returned.")
                    return
                    
                print("Summary generated successfully!")
                
                # Create summary record
                new_summary = Summary(
                    period_start=min(item.date_processed for item in all_content),
                    period_end=max(item.date_processed for item in all_content),
                    summary_type="daily",
                    summary_text=summary_text,
                    creation_date=datetime.now(),
                    sent=False,
                    is_forced=True  # This is a forced summary
                )
                session.add(new_summary)
                session.flush()  # To get the ID
                
                print(f"Summary saved to database with ID: {new_summary.id}")
                
                # Ask if user wants to send summary
                send_now = input("\nSend summary email now? (y/n): ")
                
                if send_now.lower() == 'y':
                    print("Sending summary email...")
                    result = email_sender.send_summary(summary_text, new_summary.id)
                    
                    if result:
                        print("Summary email sent successfully!")
                        
                        # Mark the summary as sent
                        new_summary.sent = True
                        new_summary.sent_date = datetime.now()
                        
                        # Mark all content as summarized
                        for item in all_content:
                            item.is_summarized = True
                        
                        # Commit all changes
                        session.commit()
                        print("All database records updated.")
                    else:
                        print("Failed to send summary email.")
                        session.commit()  # Still save the summary to database
                else:
                    print("Summary not sent. You can send it later with send_pending_summaries.py.")
                    session.commit()
                    
            except Exception as e:
                logger.error(f"Error generating or sending summary: {e}", exc_info=True)
                print(f"Error: {str(e)}")
        except Exception as e:
            logger.error(f"Database error: {e}", exc_info=True)
            print(f"Database error: {str(e)}")
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error initializing components: {e}", exc_info=True)
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    force_generate_complete_summary() 