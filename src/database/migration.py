"""
Database migration script for LetterMonstr.

This script adds new tables and columns to the database as needed.
"""

import os
import logging
import sys
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from src.database.models import get_session, Base, Summary, SummarizedContent

logger = logging.getLogger(__name__)

def migrate_database(db_path):
    """Perform database migrations."""
    logger.info("Starting database migration")
    
    # Get database session
    session = get_session(db_path)
    
    try:
        # Check if ProcessedContent table exists
        try:
            session.execute(text("SELECT 1 FROM processed_content LIMIT 1"))
            logger.info("ProcessedContent table already exists")
        except OperationalError:
            logger.info("Creating ProcessedContent table")
            # Import ProcessedContent class only after checking to avoid circular imports
            from src.database.models import ProcessedContent
            
            # Create table
            Base.metadata.create_all(session.get_bind(), tables=[ProcessedContent.__table__])
            logger.info("ProcessedContent table created successfully")
        
        # Check if summarized_content_history table exists
        try:
            session.execute(text("SELECT 1 FROM summarized_content_history LIMIT 1"))
            logger.info("SummarizedContent table already exists")
        except OperationalError:
            logger.info("Creating SummarizedContent table")
            
            # Create table
            Base.metadata.create_all(session.get_bind(), tables=[SummarizedContent.__table__])
            logger.info("SummarizedContent table created successfully")
        
        logger.info("Database migration completed successfully")
    except Exception as e:
        logger.error(f"Error during database migration: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Get database path
    db_path = os.path.join(os.path.dirname(project_root), 'data', 'lettermonstr.db')
    
    # Run migration
    migrate_database(db_path) 