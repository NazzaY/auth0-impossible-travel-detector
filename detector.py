import os
import math
import requests
from datetime import datetime

CLIENT_ID = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET = os.getenv("AUTH0_CLIENT_SECRET")
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUDIENCE = f"https://{AUTH0_DOMAIN}/api/v2/"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SPEED_THRESHOLD_KMH = int(os.getenv("SPEED_THRESHOLD_KMH", "800"))
MIN_DISTANCE_KM = int(os.getenv("MIN_DISTANCE_KM", "50"))

user_states = {}
seen_log_ids = set()


def get_auth0_token():
    url = f"https://{AUTH0_DOMAIN}/oauth/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "audience": AUDIENCE
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json().get("access_token")


def fetch_auth0_logs(access_token):
    url = f"https://{AUTH0_DOMAIN}/api/v2/logs"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"per_page": 50, "sort": "date:-1"}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def get_geolocation(ip_address):
    if not ip_address or ip_address in ["127.0.0.1", "::1", "localhost"]:
        return None
    try:
        res = requests.get(f"http://ip-api.com/json/{ip_address}", timeout=5)
        data = res.json()
        if data.get("status") == "success":
            return {
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "city": data.get("city", "Unknown"),
                "country": data.get("country", "Unknown")
            }
    except Exception as e:
        print(f"GeoIP error for IP {ip_address}: {e}")
    return None


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing. Alert output:\n", message)
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")


def check_impossible_travel():
    print("[*] Authenticating with Auth0...")
    token = get_auth0_token()
    
    print("[*] Fetching recent Auth0 logs...")
    logs = fetch_auth0_logs(token)

    for log in reversed(logs):
        log_id = log.get("log_id") or log.get("_id")
        if log_id in seen_log_ids:
            continue
        seen_log_ids.add(log_id)

        if log.get("type") != "s":
            continue

        user_id = log.get("user_id")
        user_name = log.get("user_name", "N/A")
        ip = log.get("ip")
        date_str = log.get("date")
        
        if not user_id or not ip or not date_str:
            continue

        current_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        geo = get_geolocation(ip)
        if not geo:
            continue

        current_lat = geo["lat"]
        current_lon = geo["lon"]

        if user_id in user_states:
            prev = user_states[user_id]
            prev_time = prev["timestamp"]
            
            time_diff_hours = (current_time - prev_time).total_seconds() / 3600.0
            
            if time_diff_hours > 0:
                distance_km = haversine(prev["lat"], prev["lon"], current_lat, current_lon)
                speed_kmh = distance_km / time_diff_hours

                if distance_km > MIN_DISTANCE_KM and speed_kmh > SPEED_THRESHOLD_KMH:
                    alert_msg = (
                        f"🚨 *IMPOSSIBLE TRAVEL DETECTED!*\n\n"
                        f"👤 *User:* {user_name} (`{user_id}`)\n"
                        f"📍 *Previous:* {prev['city']}, {prev['country']} at {prev_time.strftime('%H:%M:%S UTC')}\n"
                        f"📍 *Current:* {geo['city']}, {geo['country']} at {current_time.strftime('%H:%M:%S UTC')}\n"
                        f"📏 *Distance:* {int(distance_km)} km\n"
                        f"⏱ *Time elapsed:* {round(time_diff_hours * 60, 1)} minutes\n"
                        f"⚡ *Calculated speed:* *{int(speed_kmh)} km/h*\n\n"
                        f"🛠 *Recommended actions:*\n"
                        f"1. Contact the user to verify the login\n"
                        f"2. Revoke active sessions in Auth0\n"
                        f"3. If not confirmed: reset password and require MFA re-verification"
                    )
                    print(alert_msg)
                    send_telegram_alert(alert_msg)

        user_states[user_id] = {
            "lat": current_lat,
            "lon": current_lon,
            "timestamp": current_time,
            "city": geo["city"],
            "country": geo["country"]
        }

    print("[*] Scan completed successfully.")


if __name__ == "__main__":
    import time
    while True:
        try:
            check_impossible_travel()
        except Exception as e:
            print(f"Scan failed: {e}")
        time.sleep(60)
