#!/usr/bin/env python3
"""
Fix Database Locks - LetterMonstr.

This script checks for and resolves database locking issues that may 
prevent summaries from being sent properly.
"""

import os
import sys
import time
import sqlite3
import subprocess
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join('data', 'db_fix.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def get_database_path():
    """Get the path to the SQLite database."""
    return os.path.join('data', 'lettermonstr.db')

def check_database_lock():
    """Check if the database is locked."""
    db_path = get_database_path()
    
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        return False
    
    try:
        # Try to open the database for writing
        conn = sqlite3.connect(db_path, timeout=1)
        cursor = conn.cursor()
        
        # Try a simple write operation
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("COMMIT")
        
        conn.close()
        print("Database is not locked. Connections are working properly.")
        return False
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e):
            print("Database is locked!")
            return True
        else:
            print(f"Database error: {e}")
            return False

def identify_locking_processes():
    """Identify processes that might be locking the database."""
    db_path = get_database_path()
    processes = []
    
    try:
        if sys.platform == 'darwin':  # macOS
            # Get processes that have the database file open
            result = subprocess.run(['lsof', db_path], 
                                   capture_output=True, text=True)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:  # Skip header line
                    for line in lines[1:]:
                        parts = line.split()
                        if len(parts) >= 2:
                            processes.append({
                                'pid': parts[1],
                                'process': parts[0]
                            })
            
            if processes:
                print(f"Found {len(processes)} processes accessing the database:")
                for p in processes:
                    print(f"  PID {p['pid']}: {p['process']}")
            else:
                print("No processes found that are currently accessing the database.")
                print("The lock might be from a process that died unexpectedly.")
    except Exception as e:
        print(f"Error identifying locking processes: {e}")
    
    return processes

def fix_database_lock():
    """Attempt to fix database locking issues."""
    db_path = get_database_path()
    
    if not check_database_lock():
        return True
    
    print("\nAttempting to fix database lock...")
    
    # 1. Identify locking processes
    processes = identify_locking_processes()
    
    if not processes:
        # 2. If no processes found, try making a new connection with a longer timeout
        print("Attempting to connect with longer timeout...")
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            cursor = conn.cursor()
            cursor.execute("PRAGMA busy_timeout = 60000")  # 60 second timeout
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("COMMIT")
            conn.close()
            print("Successfully connected with longer timeout.")
            return True
        except sqlite3.OperationalError as e:
            print(f"Failed to connect with longer timeout: {e}")
    
    # 3. Create a backup of the database
    backup_path = f"{db_path}.backup-{int(time.time())}"
    print(f"Creating database backup at {backup_path}...")
    try:
        with open(db_path, 'rb') as src, open(backup_path, 'wb') as dst:
            dst.write(src.read())
        print("Backup created successfully.")
    except Exception as e:
        print(f"Failed to create backup: {e}")
        return False
    
    # 4. Attempt to recover the database
    print("Attempting database recovery...")
    try:
        # Connect to the database
        conn = sqlite3.connect(db_path, timeout=60)
        
        # Enable multi-threading mode and set a busy timeout
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=60000")
        
        # Run VACUUM to rebuild the database file
        print("Running VACUUM to rebuild the database...")
        conn.execute("VACUUM")
        
        # Check the integrity of the database
        print("Checking database integrity...")
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        
        if result and result[0] == 'ok':
            print("Database integrity is OK.")
        else:
            print(f"Database integrity check failed: {result}")
            
        conn.close()
        
        # Verify the fix worked
        if not check_database_lock():
            print("\nDatabase lock has been fixed!")
            return True
        else:
            print("\nDatabase is still locked after recovery attempts.")
            return False
            
    except Exception as e:
        print(f"Error during recovery: {e}")
        return False

def main():
    """Main function."""
    print("\nLetterMonstr - Fix Database Locks")
    print("================================\n")
    
    if check_database_lock():
        if fix_database_lock():
            print("\nSuccess! The database should now be accessible.")
            print("You can now run the debug_summaries.py script to send pending summaries.")
        else:
            print("\nFailed to fix database lock. Try:")
            print("1. Restart your computer")
            print("2. Check for zombie processes")
            print("3. Use the backup file if needed")
    else:
        print("\nNo issues found with the database. If you're still having problems:")
        print("1. Check your email configuration")
        print("2. Run debug_summaries.py to check for unsent summaries")
        print("3. Check the log files for other errors")

if __name__ == "__main__":
    main() 