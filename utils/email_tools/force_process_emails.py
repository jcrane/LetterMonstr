#!/usr/bin/env python3
"""
Script to force process all unread emails regardless of their previous processed status.

This is useful for troubleshooting or reprocessing emails that were previously skipped.
"""

from src.fetch_process import force_process_all_emails

if __name__ == "__main__":
    print("Starting force processing of all unread emails...")
    print("NOTE: This will only process UNREAD emails in your inbox.")
    print("To test this workflow, you can:")
    print("1. Mark one test email as unread in Gmail")
    print("2. Run this script to process just that email")
    print("3. Check the result with ./status_lettermonstr.sh to see if ProcessedContent entries were created")
    print()
    
    force_process_all_emails()
    print("Force processing completed.") 