#!/usr/bin/env python3
import sys
import os

print("=== Python Environment Diagnostic ===")
print(f"Python version: {sys.version}")
print(f"Python executable: {sys.executable}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")

# Check if we can import email.header
try:
    import email.header
    print("✓ Successfully imported email.header")
except ImportError as e:
    print(f"✗ FAILED to import email.header: {e}")
    
    # Try to find the email module location
    import importlib.util
    spec = importlib.util.find_spec("email")
    if spec:
        print(f"email module location: {spec.origin}")
    else:
        print("email module not found!")
    
    # Try to find pythons standard library location
    import sysconfig
    stdlib_path = sysconfig.get_path('stdlib')
    print(f"Standard library path: {stdlib_path}")
    
    email_dir = os.path.join(stdlib_path, "email")
    if os.path.exists(email_dir):
        print(f"email directory exists at: {email_dir}")
        header_file = os.path.join(email_dir, "header.py")
        if os.path.exists(header_file):
            print(f"header.py exists at: {header_file}")
        else:
            print(f"header.py DOES NOT exist at: {header_file}")
    else:
        print(f"email directory DOES NOT exist at: {email_dir}")

print("=== End Diagnostic ===\n")
