"""Constants for NAS Hub."""
from __future__ import annotations

DOMAIN = "nas_hub"

# One config entry per service; the type decides client, sensors and form
CONF_SERVICE = "service"
CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_PUBLIC_URL = "public_url"
CONF_WEBHOOK_ID = "webhook_id"

SERVICE_JELLYFIN = "jellyfin"
SERVICE_AUDIOBOOKSHELF = "audiobookshelf"
SERVICE_SONARR = "sonarr"
SERVICE_RADARR = "radarr"
SERVICE_EBOOKS = "ebooks"

SERVICE_NAMES = {
    SERVICE_JELLYFIN: "Jellyfin",
    SERVICE_AUDIOBOOKSHELF: "Audiobookshelf",
    SERVICE_SONARR: "Sonarr",
    SERVICE_RADARR: "Radarr",
    SERVICE_EBOOKS: "E-Book-Versand",
}

DEFAULT_URLS = {
    SERVICE_JELLYFIN: "http://nas.local:8096",
    SERVICE_AUDIOBOOKSHELF: "http://nas.local:13378",
    SERVICE_SONARR: "http://nas.local:8989",
    SERVICE_RADARR: "http://nas.local:7878",
}

# Options
OPT_LIST_MINUTES = "list_minutes"
OPT_LIVE_SECONDS = "live_seconds"
OPT_ITEM_COUNT = "item_count"
OPT_DAYS_AHEAD = "days_ahead"
OPT_AVAILABILITY_ENTITY = "availability_entity"
OPT_SHOW_CINEMA = "show_cinema"

DEFAULT_LIST_MINUTES = 60
DEFAULT_LIVE_SECONDS = 60
DEFAULT_ITEM_COUNT = 10
DEFAULT_DAYS_AHEAD = {SERVICE_SONARR: 14, SERVICE_RADARR: 90}

# A service that wakes up gets a moment before it is asked
WAKE_REFRESH_DELAY = 90

# States of the availability entity that mean "the NAS is asleep"
ASLEEP_STATES = {"off", "unavailable", "unknown", "false", "0", "not_home", "none", ""}

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.{{entry_id}}"

# Cached artwork lives outside www/ and is served under this URL; file names
# are hashes of their source, so they can be cached hard
IMAGE_DIR_NAME = "nas_hub_images"
IMAGE_URL_BASE = "/nas_hub_images"
MAX_IMAGE_BYTES = 3 * 1024 * 1024

FRONTEND_URL_BASE = f"/{DOMAIN}_frontend"

EBOOK_HISTORY = 30
EVENT_EBOOK_SENT = f"{DOMAIN}_ebook_sent"

REQUEST_TIMEOUT = 15
