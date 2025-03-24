#!/usr/bin/env python3
"""
Database Initialization Script for LetterMonstr

This script creates and initializes the SQLite database with proper settings
to avoid database locking issues.
"""

import os
import sys
import time
import sqlite3
import logging
from sqlalchemy import create_engine, text

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import database models
from src.database.models import Base, init_db, get_session

def initialize_database():
    """Create and initialize the database with proper settings."""
    db_path = os.path.join('data', 'lettermonstr.db')
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Remove existing database if it exists
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            logger.info(f"Removed existing database file: {db_path}")
        except Exception as e:
            logger.error(f"Error removing existing database: {e}")
            if os.path.exists(db_path):
                logger.error("Database file still exists, may be locked by another process")
                return False
    
    # Create empty database file
    try:
        # Use sqlite3 to create and initialize the database with proper pragmas
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Set journal mode to WAL for better concurrency
        cursor.execute("PRAGMA journal_mode=WAL;")
        
        # Use a proper synchronous setting
        cursor.execute("PRAGMA synchronous=NORMAL;")
        
        # Set busy timeout to prevent lock errors
        cursor.execute("PRAGMA busy_timeout=120000;")  # 120 seconds
        
        # Use memory for temp store
        cursor.execute("PRAGMA temp_store=MEMORY;")
        
        # Increase cache size
        cursor.execute("PRAGMA cache_size=-40000;")  # About 40MB
        
        # Enable foreign keys
        cursor.execute("PRAGMA foreign_keys=ON;")
        
        conn.commit()
        conn.close()
        
        logger.info(f"Created and initialized database file: {db_path}")
    except Exception as e:
        logger.error(f"Error creating database file: {e}")
        return False
    
    try:
        # Now create all tables using SQLAlchemy
        logger.info("Creating database tables...")
        Session = init_db(db_path)
        session = Session()
        
        # Verify pragma settings using SQLAlchemy
        pragmas_to_check = [
            "journal_mode", "synchronous", "busy_timeout", 
            "temp_store", "cache_size", "foreign_keys"
        ]
        
        for pragma in pragmas_to_check:
            result = session.execute(text(f"PRAGMA {pragma};")).scalar()
            logger.info(f"PRAGMA {pragma} = {result}")
        
        # Close session
        session.close()
        
        logger.info("Database initialization completed successfully")
        return True
    except Exception as e:
        logger.error(f"Error initializing database tables: {e}")
        return False

if __name__ == "__main__":
    print("LetterMonstr Database Initialization")
    print("===================================")
    
    if initialize_database():
        print("\nDatabase initialized successfully!")
        print("You can now run LetterMonstr with './run_lettermonstr.sh'")
    else:
        print("\nFailed to initialize database.")
        print("Please check the logs for details.")
        sys.exit(1) 