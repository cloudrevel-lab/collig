#!/usr/bin/env python3
"""
Email Connection Test Script
Tests IMAP, POP3, and SMTP connections for given email config
"""

import imaplib
import poplib
import smtplib
import ssl
import socket
import time
import argparse
import json
import os
import sys
from datetime import datetime

# Global config placeholder
CONFIG = {
    "EMAIL_ADDRESS": "",
    "EMAIL_PASSWORD": "",
    "IMAP_SERVER": "",
    "SMTP_SERVER": ""
}

def load_config_for_email(email_address):
    """
    Finds and loads the configuration file for the given email address.
    Searches in ~/.collig/configs/email/
    """
    config_dir = os.path.expanduser("~/.collig/configs/email")
    if not os.path.exists(config_dir):
        print(f"Error: Config directory {config_dir} does not exist.")
        sys.exit(1)

    # Search for a file containing the email address
    files = [f for f in os.listdir(config_dir) if f.endswith(".json")]
    found_file = None

    for fname in files:
        path = os.path.join(config_dir, fname)
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if data.get("EMAIL_ADDRESS") == email_address:
                    found_file = path
                    # Update global config
                    CONFIG.update(data)
                    break
        except Exception as e:
            print(f"Warning: Failed to read {path}: {e}")

    if not found_file:
        print(f"Error: No configuration found for email: {email_address}")
        print(f"Checked in {config_dir}")
        sys.exit(1)

    print(f"Loaded configuration from: {found_file}")
    return True

def test_imap_connection():
    """Test IMAP connection on port 993"""
    print("\n" + "="*60)
    print("Testing IMAP Connection (port 993)")
    print("="*60)

    email_user = CONFIG["EMAIL_ADDRESS"]
    email_pass = CONFIG["EMAIL_PASSWORD"]
    imap_host = CONFIG["IMAP_SERVER"]

    try:
        # Create SSL context
        context = ssl.create_default_context()

        # Connect to IMAP server
        print(f"Connecting to {imap_host}:993...")
        start_time = time.time()
        imap_server = imaplib.IMAP4_SSL(
            host=imap_host,
            port=993,
            ssl_context=context
        )
        connection_time = time.time() - start_time
        print(f"✓ Connected successfully in {connection_time:.2f} seconds")

        # Try to login
        print(f"Attempting login for {email_user}...using {email_pass}")
        imap_server.login(email_user, email_pass)
        print("✓ Login successful")

        # List mailboxes
        print("Listing mailboxes...")
        status, mailboxes = imap_server.list()
        if status == 'OK':
            print(f"✓ Found {len(mailboxes)} mailboxes")
            for i, mailbox in enumerate(mailboxes[:5]):  # Show first 5
                print(f"  {i+1}. {mailbox.decode('utf-8', errors='ignore')}")
            if len(mailboxes) > 5:
                print(f"  ... and {len(mailboxes)-5} more")
        else:
            print("✗ Could not list mailboxes")

        # Get mailbox status
        print("Getting INBOX status...")
        imap_server.select('INBOX')
        status, messages = imap_server.status('INBOX', '(MESSAGES UNSEEN RECENT)')
        if status == 'OK':
            print(f"✓ INBOX status: {messages[0].decode('utf-8')}")

        # Logout
        imap_server.logout()
        print("✓ Logged out successfully")
        return True

    except Exception as e:
        print(f"✗ IMAP Connection failed: {e}")
        return False

def test_pop3_connection():
    """Test POP3 connection on port 995"""
    print("\n" + "="*60)
    print("Testing POP3 Connection (port 995)")
    print("="*60)

    # Assuming POP3 server is same as IMAP or SMTP if not specified?
    # Usually config only has IMAP and SMTP. Let's try IMAP host or SMTP host?
    # Or just skip if not explicitly configured?
    # The user asked to update IMAP and SMTP. POP3 might not be configured.
    # We'll use IMAP_SERVER host as a guess for POP3, or skip.

    host = CONFIG.get("IMAP_SERVER") # Often same hostname
    email_user = CONFIG["EMAIL_ADDRESS"]
    email_pass = CONFIG["EMAIL_PASSWORD"]

    try:
        # Create SSL context
        context = ssl.create_default_context()

        # Connect to POP3 server
        print(f"Connecting to {host}:995...")
        start_time = time.time()
        pop_server = poplib.POP3_SSL(
            host=host,
            port=995,
            context=context
        )
        connection_time = time.time() - start_time
        print(f"✓ Connected successfully in {connection_time:.2f} seconds")

        # Try to login
        print(f"Attempting login for {email_user}...")
        pop_server.user(email_user)
        pop_server.pass_(email_pass)
        print("✓ Login successful")

        # Quit
        pop_server.quit()
        print("✓ Connection closed successfully")
        return True

    except Exception as e:
        print(f"✗ POP3 Connection failed (Optional): {e}")
        return False # Mark as fail, but it might be optional

def test_smtp_connection():
    """Test SMTP connection on port 465"""
    print("\n" + "="*60)
    print("Testing SMTP Connection (port 465)")
    print("="*60)

    email_user = CONFIG["EMAIL_ADDRESS"]
    email_pass = CONFIG["EMAIL_PASSWORD"]
    smtp_host = CONFIG["SMTP_SERVER"]

    try:
        # Create SSL context
        context = ssl.create_default_context()

        # Connect to SMTP server
        print(f"Connecting to {smtp_host}:465...")
        start_time = time.time()
        smtp_server = smtplib.SMTP_SSL(
            host=smtp_host,
            port=465,
            context=context,
            timeout=30
        )
        connection_time = time.time() - start_time
        print(f"✓ Connected successfully in {connection_time:.2f} seconds")

        # Try to login
        print(f"Attempting login for {email_user}...")
        smtp_server.login(email_user, email_pass)
        print("✓ Login successful")

        # Quit
        smtp_server.quit()
        print("✓ Connection closed successfully")
        return True

    except Exception as e:
        print(f"✗ SMTP Connection failed: {e}")
        return False

def test_dns_resolution():
    """Test DNS resolution for the mail server"""
    print("\n" + "="*60)
    print("Testing DNS Resolution")
    print("="*60)

    host = CONFIG["IMAP_SERVER"]

    try:
        import socket

        print(f"Resolving {host}...")
        start_time = time.time()
        ip_addresses = socket.getaddrinfo(
            host,
            None,
            socket.AF_INET,
            socket.SOCK_STREAM
        )
        resolution_time = time.time() - start_time

        print(f"✓ DNS resolved in {resolution_time:.2f} seconds")
        for i, (family, socktype, proto, canonname, sockaddr) in enumerate(ip_addresses):
            print(f"  IP Address {i+1}: {sockaddr[0]}")

        return True

    except Exception as e:
        print(f"✗ DNS resolution failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test Email Connection")
    parser.add_argument("--email", required=True, help="Email address to test (loads config from ~/.collig/configs/email/)")
    args = parser.parse_args()

    # Load Config
    load_config_for_email(args.email)

    print("="*60)
    print("EMAIL CONNECTION TEST SCRIPT")
    print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print(f"Email: {CONFIG['EMAIL_ADDRESS']}")
    print(f"IMAP Server: {CONFIG['IMAP_SERVER']}")
    print(f"SMTP Server: {CONFIG['SMTP_SERVER']}")
    print("="*60)

    results = {
        'DNS': test_dns_resolution(),
        'IMAP': test_imap_connection(),
        # 'POP3': test_pop3_connection(), # POP3 is often disabled/optional, let's skip strict check or make optional
        'SMTP': test_smtp_connection()
    }

    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    for service, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{service:10} {status}")

    print("="*60)

    if all(results.values()):
        print("🎉 All tests passed! Email configuration is working correctly.")
        sys.exit(0)
    else:
        print("⚠️  Some tests failed. Check the error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main()