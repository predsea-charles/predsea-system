#!/usr/bin/env python3
"""
PredSea Status Notifier.
Sends messages to configured webhooks (Slack, Discord, Teams).
"""
import argparse
import json
import os
import sys
import requests

def send_notification(message: str, webhook_url: str):
    """Send a plain text or JSON payload to a webhook."""
    if not webhook_url:
        print("⚠️ No webhook URL provided. Skipping notification.")
        return

    payload = {}

    # Simple heuristic to detect Slack/Discord/Teams and format appropriately
    if "hooks.slack.com" in webhook_url:
        payload = {"text": message}
    elif "discord.com/api/webhooks" in webhook_url:
        payload = {"content": message}
    else:
        # Default to generic JSON text field
        payload = {"text": message}

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        print(f"✅ Notification sent to {webhook_url.split('/')[2]}")
    except Exception as e:
        print(f"❌ Failed to send notification: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Send status notifications to webhooks.")
    parser.add_argument("message", help="The message to send")
    parser.add_argument("--webhook-url", default=os.getenv("PREDSEA_NOTIFICATION_WEBHOOK"), help="Webhook URL")

    args = parser.parse_args()

    if not args.webhook_url:
        # Check if we are in a GCP environment and might have a secret or env var
        pass

    send_notification(args.message, args.webhook_url)

if __name__ == "__main__":
    main()
