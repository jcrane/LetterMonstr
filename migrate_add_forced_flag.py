#!/usr/bin/env python3
"""
Migration script to add is_forced column to summaries table.

This adds the ability to distinguish between scheduled and forced summaries.
"""

import os
import sys
import logging
import sqlite3

# Set up the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_migration():
    """Run the migration to add is_forced column to summaries table."""
    db_path = os.path.join('data', 'lettermonstr.db')
    
    if not os.path.exists(db_path):
        logger.error(f"Database file not found at {db_path}")
        return False
    
    conn = None
    try:
        logger.info(f"Opening database at {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(summaries)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'is_forced' in columns:
            logger.info("Column 'is_forced' already exists in the summaries table")
            return True
        
        # Add the is_forced column with default value of True for existing summaries
        logger.info("Adding 'is_forced' column to summaries table")
        cursor.execute("ALTER TABLE summaries ADD COLUMN is_forced BOOLEAN DEFAULT 1")
        
        # Commit the changes
        conn.commit()
        logger.info("Migration completed successfully")
        
        # Display the count of updated summaries
        cursor.execute("SELECT COUNT(*) FROM summaries")
        count = cursor.fetchone()[0]
        logger.info(f"Updated {count} existing summaries to is_forced=True")
        
        return True
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("Running migration to add is_forced column to summaries table...")
    if run_migration():
        print("Migration completed successfully.")
    else:
        print("Migration failed. Check the logs for details.") 