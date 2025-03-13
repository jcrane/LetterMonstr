#!/usr/bin/env python3
"""
Database migration script for LetterMonstr.

This script adds the ProcessedContent table to existing database installations
and any other required database schema changes for the periodic fetching feature.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime

# Add the project root to the Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(project_root, 'data', 'db_migration.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_db_path():
    """Get the path to the SQLite database file."""
    return os.path.join(project_root, 'data', 'lettermonstr.db')

def check_table_exists(conn, table_name):
    """Check if a table exists in the database."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    result = cursor.fetchone()
    return result is not None

def create_processed_content_table(conn):
    """Create the ProcessedContent table if it doesn't exist."""
    cursor = conn.cursor()
    
    # Create the table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS processed_content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content_hash TEXT NOT NULL UNIQUE,
        email_id INTEGER,
        source TEXT,
        content_type TEXT,
        raw_content TEXT,
        processed_content TEXT NOT NULL,
        content_metadata TEXT,
        date_processed TIMESTAMP NOT NULL,
        summarized BOOLEAN NOT NULL DEFAULT 0,
        summary_id INTEGER,
        FOREIGN KEY (email_id) REFERENCES processed_email (id),
        FOREIGN KEY (summary_id) REFERENCES summary (id)
    )
    ''')
    
    # Create indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_content_hash ON processed_content (content_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_summarized ON processed_content (summarized)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_email_id ON processed_content (email_id)')
    
    conn.commit()
    logger.info("ProcessedContent table created successfully")

def add_new_columns_to_existing_tables(conn):
    """Add any new columns to existing tables."""
    cursor = conn.cursor()
    
    # Check if we need to add the mark_read_after_summarization column to config table
    try:
        # First check if the config table exists
        if check_table_exists(conn, 'config'):
            # Check if column exists
            cursor.execute("PRAGMA table_info(config)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'mark_read_after_summarization' not in columns:
                cursor.execute('''
                ALTER TABLE config 
                ADD COLUMN mark_read_after_summarization BOOLEAN DEFAULT 1
                ''')
                logger.info("Added mark_read_after_summarization column to config table")
        
        conn.commit()
    except Exception as e:
        logger.error(f"Error adding columns to existing tables: {e}")
        conn.rollback()

def migrate_database():
    """Run database migrations."""
    logger.info("Starting database migration")
    
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        logger.error(f"Database file not found at {db_path}")
        print(f"Error: Database file not found at {db_path}")
        print("Please run the main application first to initialize the database")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        
        # Check if ProcessedContent table already exists
        if check_table_exists(conn, 'processed_content'):
            logger.info("ProcessedContent table already exists")
        else:
            create_processed_content_table(conn)
        
        # Add any new columns to existing tables
        add_new_columns_to_existing_tables(conn)
        
        # Close connection
        conn.close()
        
        logger.info("Database migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error during database migration: {e}")
        print(f"Error: Database migration failed: {e}")
        return False

if __name__ == "__main__":
    print("LetterMonstr - Database Migration Tool")
    print("-------------------------------------")
    
    success = migrate_database()
    
    if success:
        print("\nDatabase migration completed successfully!")
        print("You can now use the periodic fetching feature.")
    else:
        print("\nDatabase migration failed. Please check the logs for details.")
        sys.exit(1)