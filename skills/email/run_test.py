#!/usr/bin/env python3
import subprocess
import sys
import os

print("Running email connection test...")
print("="*60)

script_dir = os.path.dirname(os.path.abspath(__file__))
test_script = os.path.join(script_dir, "test_connection.py")

# Default email for testing or pass as argument
# Ideally this script should also accept args to pass down
email_arg = None
if len(sys.argv) > 1:
    email_arg = sys.argv[1]

if not email_arg:
    print("Usage: python3 run_test.py <email_address>")
    sys.exit(1)

try:
    result = subprocess.run(
        [sys.executable, test_script, "--email", email_arg],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
        
except Exception as e:
    print(f"Error running test: {e}")