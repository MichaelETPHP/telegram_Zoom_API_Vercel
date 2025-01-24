import json
import requests
import os
import base64
from flask import Flask, request, redirect
from datetime import datetime, timedelta
import pytz
import asyncio

# Flask App for local callback
app = Flask(__name__)
application = app
app.url_map.strict_slashes = False

# Telegram Bot API token
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7859561595:AAEoCY3Dt5_eaqseHCwEWr54XEK5nwjJTfg')
TELEGRAM_GROUP_CHAT_ID = os.getenv('TELEGRAM_GROUP_CHAT_ID', '-1002339790106')

# Zoom API credentials
ZOOM_CLIENT_ID = os.getenv('ZOOM_CLIENT_ID', '9TQL8mraR4OaDttE0fPcdA')
ZOOM_CLIENT_SECRET = os.getenv('ZOOM_CLIENT_SECRET', 'nCWsA6YtWhRl5E0GjF5dwy9hiyD2AV77')
ZOOM_REDIRECT_URI = os.getenv('ZOOM_REDIRECT_URI', 'https://telegram-zoom-api.onrender.com/callback')

# Global variable to store access token
ZOOM_ACCESS_TOKEN = None

@app.route('/')
def home():
    """Redirect to Zoom authorization URL."""
    authorization_url = (
        f"https://zoom.us/oauth/authorize?response_type=code&client_id={ZOOM_CLIENT_ID}&redirect_uri={ZOOM_REDIRECT_URI}"
    )
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    """Handle Zoom OAuth callback."""
    global ZOOM_ACCESS_TOKEN

    authorization_code = request.args.get('code')
    if not authorization_code:
        return "Error: Authorization code not found.", 400

    token_url = 'https://zoom.us/oauth/token'
    auth_header = base64.b64encode(f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}".encode()).decode()
    payload = {
        'grant_type': 'authorization_code',
        'code': authorization_code,
        'redirect_uri': ZOOM_REDIRECT_URI
    }
    headers = {
        'Authorization': f'Basic {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    response = requests.post(token_url, data=payload, headers=headers)
    if response.status_code == 200:
        ZOOM_ACCESS_TOKEN = response.json().get('access_token')
        meeting_details = create_zoom_meeting()
        if meeting_details:
            send_meeting_details_to_telegram(meeting_details)
        return "Access token successfully obtained, and meeting details sent to Telegram.", 200
    else:
        return f"Failed to obtain access token. Status code: {response.status_code}. Response: {response.json()}", 400

def create_zoom_meeting():
    global ZOOM_ACCESS_TOKEN

    if not ZOOM_ACCESS_TOKEN:
        print("Access token not available. Please complete the OAuth flow first.")
        return None

    tz = pytz.timezone('UTC')
    current_time = datetime.now(tz)
    start_time = current_time + timedelta(minutes=1)
    start_time_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')

    meeting_url = 'https://api.zoom.us/v2/users/me/meetings'
    payload = {
        "topic": "Scheduled Meeting",
        "type": 2,
        "start_time": start_time_str,
        "duration": 30,
        "timezone": "UTC",
    }
    headers = {
        'Authorization': f'Bearer {ZOOM_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    response = requests.post(meeting_url, json=payload, headers=headers)
    if response.status_code == 201:
        meeting_details = response.json()
        print(f"Meeting created successfully. Meeting ID: {meeting_details.get('id')}")
        return meeting_details
    else:
        print(f"Failed to create meeting. Status code: {response.status_code}")
        print(f"Response: {response.json()}")
        return None

def send_meeting_details_to_telegram(meeting_details):
    meeting_link = meeting_details.get('join_url')
    meeting_topic = meeting_details.get('topic')
    meeting_id = meeting_details.get('id')
    countdown_seconds = 60  # Time until meeting starts

    # Prepare the message
    message = (
        f"**📢 New Zoom Meeting Created!**\n\n"
        f"**🔐 Meeting ID:** {meeting_id}\n"
        f"**🗋 Topic:** {meeting_topic}\n"
        f"**🔗 Join Link:** [Click here to join the meeting]({meeting_link})\n"
        f"**⏳ Starting in:** {countdown_seconds} seconds"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_GROUP_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        telegram_message_id = response.json().get('result', {}).get('message_id')
        # Start the countdown and deletion tasks
        asyncio.run(update_and_delete_tasks(telegram_message_id, countdown_seconds, meeting_link, meeting_topic, meeting_id))
    else:
        print(f"Failed to send message to Telegram. Status code: {response.status_code}")
        print(f"Response: {response.json()}")

async def update_and_delete_tasks(message_id, countdown_seconds, meeting_link, meeting_topic, meeting_id):
    await asyncio.gather(
        update_countdown_in_telegram(message_id, countdown_seconds, meeting_link, meeting_topic, meeting_id),
        delete_telegram_message(message_id, 60)
    )

async def update_countdown_in_telegram(message_id, countdown_seconds, meeting_link, meeting_topic, meeting_id):
    """Update the countdown timer in the Telegram message."""
    while countdown_seconds > 0:
        message = (
            f"**📢 New Zoom Meeting Created!**\n\n"
            f"**🔐 Meeting ID:** {meeting_id}\n"
            f"**📝 Topic:** {meeting_topic}\n"
            f"**🔗 Join Link:** [Click here to join the meeting]({meeting_link})\n"
            f"**⏳ Starting in:** {countdown_seconds} seconds"
        )
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
        data = {
            'chat_id': TELEGRAM_GROUP_CHAT_ID,
            'message_id': message_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        requests.post(url, data=data)
        await asyncio.sleep(1)
        countdown_seconds -= 1

async def delete_telegram_message(message_id, delay):
    """Delete a Telegram message after a specified delay."""
    await asyncio.sleep(delay)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    data = {'chat_id': TELEGRAM_GROUP_CHAT_ID, 'message_id': message_id}
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print(f"Message ID {message_id} deleted successfully.")
        await notify_telegram_admin()
    else:
        print(f"Failed to delete message ID {message_id}. Status code: {response.status_code}")

async def notify_telegram_admin():
    """Notify users to contact admin after the message is deleted."""
    message = (
        f"🚨 **Missed the Zoom meeting details?**\n\n"
        f"📩 Please contact the admin for assistance: @MikaET\n"
        f"🔒 Stay connected and never miss important updates!"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': TELEGRAM_GROUP_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("Admin notification sent successfully.")
    else:
        print(f"Failed to send admin notification. Status code: {response.status_code}")
    
    requests.post(url, data=data)

# Ensure the Flask app runs with a proper event loop
if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run(port=5000)
