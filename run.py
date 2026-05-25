"""
StayVista Slack Issue Bot - Launcher

Usage:
    python run.py
"""

import os
import json
import urllib.request as urllib_req
from dotenv import load_dotenv

load_dotenv()

PORT = int(os.environ.get("PORT", 5000))


def _get_ngrok_url():
    """Return existing ngrok tunnel URL if one is already running."""
    try:
        with urllib_req.urlopen("http://localhost:4040/api/tunnels", timeout=2) as r:
            data = json.loads(r.read())
            tunnels = data.get("tunnels", [])
            if tunnels:
                url = tunnels[0]["public_url"]
                return url if url.startswith("https://") else "https://" + url[7:]
    except Exception:
        pass
    return None


def _start_ngrok():
    """Start a new ngrok tunnel and return the public URL."""
    try:
        from pyngrok import ngrok, conf
        ngrok_token = os.environ.get("NGROK_AUTH_TOKEN", "")
        if ngrok_token:
            conf.get_default().auth_token = ngrok_token
        tunnel = ngrok.connect(PORT, "http")
        url = tunnel.public_url
        return url if url.startswith("https://") else "https://" + url[7:]
    except Exception as e:
        print(f"      [WARN] Could not start ngrok: {e}")
        return None


def main():
    print("=" * 60)
    print("  StayVista Slack Issue Bot")
    print("=" * 60)

    # Step 1: Get or start ngrok tunnel
    print("\n[1/2] Setting up ngrok tunnel...")
    public_url = _get_ngrok_url()

    if public_url:
        print(f"      [OK] Using existing tunnel: {public_url}")
    else:
        public_url = _start_ngrok()
        if public_url:
            print(f"      [OK] ngrok tunnel active: {public_url}")
        else:
            print(f"      Run ngrok manually: ngrok http {PORT}")

    # Step 2: Print Slack config URLs
    print("\n[2/2] Slack configuration:")
    print("-" * 60)
    if public_url:
        print(f"  Event Subscriptions URL:  {public_url}/slack/events")
        print(f"  Interactivity URL:        {public_url}/slack/actions")
    else:
        print("  Set ngrok URL in Slack app settings once tunnel is running.")
    print("-" * 60)
    print("\nBot is live. Press Ctrl+C to stop.\n")

    # Run Flask in main thread (keeps process alive)
    from app import app
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
