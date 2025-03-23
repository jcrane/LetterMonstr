#!/usr/bin/env python3
"""
Script to fix Python path issues.

This script will:
1. Add the correct directories to the Python path
2. Test if the email.header module can be imported
3. Try to locate where email.header should be
"""

import os
import sys
import importlib.util
import site

# Print current Python information
print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"Python path: {sys.path}")

# Try to import email.header
try:
    from email.header import decode_header
    print("\n✓ Successfully imported email.header!")
except ImportError as e:
    print(f"\n✗ Failed to import email.header: {e}")
    
    # Find the email module
    email_spec = importlib.util.find_spec("email")
    if email_spec:
        print(f"The email module is located at: {email_spec.origin}")
        
        # Check if header.py exists in that directory
        email_dir = os.path.dirname(email_spec.origin)
        header_path = os.path.join(email_dir, "header.py")
        if os.path.exists(header_path):
            print(f"Found header.py at: {header_path}")
        else:
            print(f"header.py does not exist at: {header_path}")
            
            # List files in the email directory
            print("\nFiles in the email module directory:")
            for f in os.listdir(email_dir):
                print(f"  - {f}")
    else:
        print("Could not locate the email module at all!")

# Add site-packages directories to path
print("\nAdding site-packages directories to Python path...")
for site_dir in site.getsitepackages():
    if site_dir not in sys.path:
        sys.path.append(site_dir)
        print(f"Added: {site_dir}")

# Try to import again after fixing path
try:
    from email.header import decode_header
    print("\n✓ Successfully imported email.header after fixing path!")
except ImportError as e:
    print(f"\n✗ Still failed to import email.header: {e}")

# Save the fixed path to a file
with open("fixed_pythonpath.txt", "w") as f:
    f.write("\n".join(sys.path))
print("\nSaved fixed Python path to fixed_pythonpath.txt")

print("\nDone!") 