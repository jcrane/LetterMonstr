#!/usr/bin/env python3
"""
Migration script to add retry-related fields to the Summary table.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join('data', 'db_migration.log'), mode='a')
    ]
)
logger = logging.getLogger(__name__)

def migrate_db():
    """Add retry fields to the Summary table."""
    print("\nLetterMonstr - Adding Retry Fields Migration")
    print("===========================================")
    
    # Database path
    db_path = os.path.join('data', 'lettermonstr.db')
    
    # Create backup before migration
    backup_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_path = f"{db_path}.backup_{backup_timestamp}"
    
    try:
        # Create backup
        print(f"Creating database backup at {backup_path}...")
        with open(db_path, 'rb') as src, open(backup_path, 'wb') as dst:
            dst.write(src.read())
        print("Backup created successfully.")
        
        # Connect to database
        print("Connecting to database...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(summaries)")
        columns = [column[1] for column in cursor.fetchall()]
        
        new_columns = []
        if 'retry_count' not in columns:
            new_columns.append(('retry_count', 'INTEGER DEFAULT 0'))
        if 'last_retry_time' not in columns:
            new_columns.append(('last_retry_time', 'DATETIME'))
        if 'max_retries' not in columns:
            new_columns.append(('max_retries', 'INTEGER DEFAULT 5'))
        if 'error_message' not in columns:
            new_columns.append(('error_message', 'TEXT'))
        
        if not new_columns:
            print("All retry fields already exist. No migration needed.")
            return
        
        # Add the new columns
        print("Adding new columns to summaries table...")
        for column_name, column_type in new_columns:
            cursor.execute(f"ALTER TABLE summaries ADD COLUMN {column_name} {column_type}")
            print(f"Added column: {column_name} ({column_type})")
        
        # Commit changes
        conn.commit()
        print("Database migration completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during migration: {e}", exc_info=True)
        print(f"Error: {str(e)}")
        print("Migration failed. Check data/db_migration.log for details.")
        
        # Try to restore from backup if it was created
        if os.path.exists(backup_path):
            restore = input("\nWould you like to restore from backup? (y/n): ")
            if restore.lower() == 'y':
                try:
                    print(f"Restoring from backup {backup_path}...")
                    with open(backup_path, 'rb') as src, open(db_path, 'wb') as dst:
                        dst.write(src.read())
                    print("Restoration completed.")
                except Exception as restore_error:
                    logger.error(f"Error during restoration: {restore_error}", exc_info=True)
                    print(f"Restoration failed: {str(restore_error)}")
    
    finally:
        # Close connection
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate_db() 