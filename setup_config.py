#!/usr/bin/env python3
"""
Configuration setup script for LetterMonstr.

This script helps users configure LetterMonstr by creating a config.yaml file
with their personal settings.
"""

import os
import yaml
import sys

def create_config():
    """Create a configuration file based on user input."""
    print("LetterMonstr Configuration Setup")
    print("===============================")
    print("This script will help you set up your LetterMonstr configuration.")
    print("You'll need your Gmail credentials and Anthropic API key.")
    print("\n")
    
    # Check if config file already exists
    config_path = os.path.join("config", "config.yaml")
    
    if os.path.exists(config_path):
        print("A configuration file already exists.")
        try:
            with open(config_path, 'r') as f:
                existing_config = yaml.safe_load(f)
            
            # Show current configuration summary
            print("\nCurrent Configuration Summary:")
            print(f"- Gmail: {existing_config['email']['fetch_email']}")
            print(f"- Recipient: {existing_config['summary']['recipient_email']}")
            print(f"- Summary Frequency: {existing_config['summary']['frequency']}")
            print(f"- Delivery Time: {existing_config['summary']['delivery_time']}")
            print(f"- API Key Set: {'Yes' if existing_config['llm']['anthropic_api_key'] else 'No'}")
            
            # Ask if user wants to use existing or create new
            action = input("\nOptions:\n[u] Use existing configuration\n[e] Edit existing configuration\n[n] Create new configuration\nChoice [u/e/n]: ").strip().lower()
            
            if action == 'u':
                print("\nUsing existing configuration.")
                return True
            elif action == 'e':
                print("\nEditing existing configuration...")
                config = existing_config
            else:
                print("\nCreating new configuration...")
                config = get_default_config()
        except Exception as e:
            print(f"Error reading existing configuration: {e}")
            print("Creating new configuration...")
            config = get_default_config()
    else:
        config = get_default_config()
    
    # Create config directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    # Get user input for email configuration
    print("\nEmail Configuration")
    print("-----------------")
    print("You'll need to use an App Password for Gmail.")
    print("To create one, visit: https://myaccount.google.com/apppasswords")
    config["email"]["fetch_email"] = input(f"Gmail address to fetch newsletters from [{config['email']['fetch_email']}]: ").strip() or config["email"]["fetch_email"]
    
    # Only prompt for password if it's not already set or user is creating new config
    if not config["email"]["password"] or action == 'n':
        config["email"]["password"] = input("Gmail App Password (visible): ").strip()
    else:
        update_password = input("Update Gmail password? (y/n): ").strip().lower()
        if update_password == 'y':
            config["email"]["password"] = input("Gmail App Password (visible): ").strip()
    
    # Summary delivery configuration
    print("\nSummary Delivery Configuration")
    print("----------------------------")
    config["summary"]["recipient_email"] = input(f"Email address to receive summaries [{config['summary']['recipient_email']}]: ").strip() or config["summary"]["recipient_email"]
    config["summary"]["sender_email"] = config["email"]["fetch_email"]  # Use same email for sending
    
    frequency_options = {'d': 'daily', 'w': 'weekly', 'm': 'monthly'}
    current_freq = 'd' if config["summary"]["frequency"] == 'daily' else 'w' if config["summary"]["frequency"] == 'weekly' else 'm'
    frequency_choice = input(f"Delivery frequency (d)aily, (w)eekly, or (m)onthly [{current_freq}]: ").strip().lower() or current_freq
    config["summary"]["frequency"] = frequency_options.get(frequency_choice, config["summary"]["frequency"])
    
    if config["summary"]["frequency"] == 'weekly':
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        print("Day of week for weekly summaries:")
        for i, day in enumerate(day_names):
            print(f"{i} - {day}")
        day_choice = input(f"Choose a day [0-6, default={config['summary']['weekly_day']}]: ").strip()
        config["summary"]["weekly_day"] = int(day_choice) if day_choice.isdigit() and 0 <= int(day_choice) <= 6 else config["summary"]["weekly_day"]
    
    if config["summary"]["frequency"] == 'monthly':
        day_choice = input(f"Day of month for monthly summaries [1-28, default={config['summary']['monthly_day']}]: ").strip()
        config["summary"]["monthly_day"] = int(day_choice) if day_choice.isdigit() and 1 <= int(day_choice) <= 28 else config["summary"]["monthly_day"]
    
    delivery_time = input(f"Delivery time (24-hour format, e.g. 08:00) [{config['summary']['delivery_time']}]: ").strip() or config["summary"]["delivery_time"]
    config["summary"]["delivery_time"] = delivery_time
    
    # LLM configuration
    print("\nClaude API Configuration")
    print("----------------------")
    print("You'll need an Anthropic API key for Claude.")
    print("To get one, visit: https://console.anthropic.com/")
    
    # Only prompt for API key if it's not already set or user is creating new config
    if not config["llm"]["anthropic_api_key"] or action == 'n':
        config["llm"]["anthropic_api_key"] = input("Anthropic API Key (visible): ").strip()
    else:
        update_api_key = input("Update Anthropic API key? (y/n): ").strip().lower()
        if update_api_key == 'y':
            config["llm"]["anthropic_api_key"] = input("Anthropic API Key (visible): ").strip()
    
    # Write configuration to file
    try:
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        print("\nConfiguration saved successfully!")
        print(f"You can edit your configuration anytime by modifying: {config_path}")
        return True
    except Exception as e:
        print(f"Error saving configuration: {e}")
        return False

def get_default_config():
    """Return default configuration settings."""
    return {
        "email": {
            "fetch_email": "lettermonstr@gmail.com",
            "password": "",
            "imap_server": "imap.gmail.com",
            "imap_port": 993,
            "initial_lookback_days": 7,
            "folders": ["INBOX"]
        },
        "content": {
            "max_links_per_email": 5,
            "max_link_depth": 1,
            "user_agent": "LetterMonstr/1.0",
            "request_timeout": 10,
            "ad_keywords": ["sponsored", "advertisement", "promoted", "partner", "paid"]
        },
        "database": {
            "path": "data/lettermonstr.db"
        },
        "summary": {
            "recipient_email": "",
            "frequency": "weekly",
            "delivery_time": "08:00",
            "weekly_day": 0,
            "monthly_day": 1,
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "sender_email": "lettermonstr@gmail.com",
            "subject_prefix": "[LetterMonstr] "
        },
        "llm": {
            "anthropic_api_key": "",
            "model": "claude-3-7-sonnet-20250219",
            "max_tokens": 4000,
            "temperature": 0.3
        }
    }

if __name__ == "__main__":
    success = create_config()
    if success:
        print("\nLetterMonstr is now configured and ready to use!")
        print("Run the application with: python src/main.py")
    else:
        print("\nConfiguration failed. Please try again.")
        sys.exit(1) 