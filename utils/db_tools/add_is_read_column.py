#!/usr/bin/env python3
"""
Add is_read column to processed_emails table.

This is a one-time migration script to add the is_read column to the processed_emails table.
"""

import os
import sys
import logging
import sqlite3

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_migration():
    """Run database migration to add is_read column."""
    # Database path
    db_path = os.path.join(project_root, 'data', 'lettermonstr.db')
    
    print("\nLetterMonstr - Add is_read Column Migration Tool")
    print("-------------------------------------")
    
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the column already exists
        cursor.execute("PRAGMA table_info(processed_emails)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'is_read' in column_names:
            logger.info("is_read column already exists in processed_emails table")
            return True
        
        # Add the column with default value of false (0)
        logger.info("Adding is_read column to processed_emails table")
        cursor.execute("ALTER TABLE processed_emails ADD COLUMN is_read BOOLEAN DEFAULT 0")
        
        # Commit the changes
        conn.commit()
        
        logger.info("Successfully added is_read column")
        return True
    
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False
    
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    success = run_migration()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed! See log for details.")
        sys.exit(1) 