#!/usr/bin/env python3
"""
Reset summarized status for content items in the LetterMonstr database.

This script finds content items that are marked as summarized but associated with
failed summaries, and resets their status so they can be summarized again.
"""

import os
import sys
import logging
from datetime import datetime

# Set up the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# Import necessary components
try:
    from src.database.models import get_session, Summary, ProcessedContent
except ImportError as e:
    print(f"\nError importing required modules: {e}")
    sys.exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'reset_summarized_status.log'))
    ]
)
logger = logging.getLogger(__name__)

def reset_summarized_status():
    """Reset summarized status for content items associated with failed summaries."""
    print("\nLetterMonstr - Reset Summarized Status")
    print("==================================")
    
    # Get database session
    db_path = os.path.join('data', 'lettermonstr.db')
    session = get_session(db_path)
    
    try:
        # Find all ProcessedContent items marked as summarized
        summarized_content = session.query(ProcessedContent).filter_by(summarized=True).all()
        print(f"Found {len(summarized_content)} content items marked as summarized.")
        
        # Find the most recent summary that appears to contain an error
        error_summaries = session.query(Summary).filter(
            Summary.summary_text.like("%Error generating summary%") | 
            Summary.summary_text.like("%prompt is too long%") |
            Summary.summary_text.like("%error%")
        ).all()
        
        if error_summaries:
            print(f"Found {len(error_summaries)} summaries with errors.")
            
            # Ask for confirmation to reset
            print("\nThe following summaries appear to contain errors:")
            for i, summary in enumerate(error_summaries):
                creation_date = summary.creation_date.strftime('%Y-%m-%d %H:%M') if summary.creation_date else "Unknown"
                sent_status = "Sent" if summary.sent else "Not sent"
                print(f"{i+1}. ID: {summary.id}, Created: {creation_date}, Status: {sent_status}")
                print(f"   Content: {summary.summary_text[:100]}...")
            
            reset_choice = input("\nEnter the number of the summary to reset content for, 'a' for all, or 'q' to quit: ")
            
            if reset_choice.lower() == 'q':
                print("Operation cancelled.")
                return
            
            summaries_to_reset = []
            if reset_choice.lower() == 'a':
                summaries_to_reset = error_summaries
            elif reset_choice.isdigit() and 1 <= int(reset_choice) <= len(error_summaries):
                summaries_to_reset = [error_summaries[int(reset_choice)-1]]
            else:
                print("Invalid choice. Operation cancelled.")
                return
            
            # Reset summarized status for content associated with these summaries
            for summary in summaries_to_reset:
                # Get the date range of this summary
                if summary.period_start and summary.period_end:
                    # Find content within this period
                    content_to_reset = session.query(ProcessedContent).filter(
                        ProcessedContent.summarized == True,
                        ProcessedContent.date_processed.between(summary.period_start, summary.period_end)
                    ).all()
                    
                    # Reset their status
                    for item in content_to_reset:
                        item.summarized = False
                        item.summary_id = None
                    
                    print(f"Reset {len(content_to_reset)} content items associated with summary ID {summary.id}.")
                else:
                    print(f"Summary ID {summary.id} has no period information, cannot reset associated content.")
            
            # Commit the changes
            session.commit()
            print("\nSummarized status reset successfully.")
            print("You can now run force_new_for_unsummarized.py to generate a new summary.")
        else:
            # Reset all summarized content
            print("No error summaries found. Do you want to reset all summarized content items?")
            reset_all = input("Reset all summarized content? (y/n): ")
            
            if reset_all.lower() == 'y':
                for item in summarized_content:
                    item.summarized = False
                    item.summary_id = None
                
                session.commit()
                print(f"Reset {len(summarized_content)} content items to unsummarized.")
                print("You can now run force_new_for_unsummarized.py to generate a new summary.")
            else:
                print("Operation cancelled.")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        print(f"Error: {str(e)}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    reset_summarized_status() 