"""Constants for NAS Hub."""
from __future__ import annotations

DOMAIN = "nas_hub"

# One config entry per service; the type decides client, sensors and form
CONF_SERVICE = "service"
CONF_URL = "url"
CONF_API_KEY = "api_key"
CONF_PUBLIC_URL = "public_url"

SERVICE_JELLYFIN = "jellyfin"
SERVICE_AUDIOBOOKSHELF = "audiobookshelf"
SERVICE_SONARR = "sonarr"
SERVICE_RADARR = "radarr"
SERVICE_EBOOKS = "ebooks"
SERVICE_SEERR = "seerr"

SERVICE_NAMES = {
    SERVICE_JELLYFIN: "Jellyfin",
    SERVICE_AUDIOBOOKSHELF: "Audiobookshelf",
    SERVICE_SONARR: "Sonarr",
    SERVICE_RADARR: "Radarr",
    SERVICE_SEERR: "Seerr",
    SERVICE_EBOOKS: "E-Book-Versand",
}

DEFAULT_URLS = {
    SERVICE_JELLYFIN: "http://nas.local:8096",
    SERVICE_AUDIOBOOKSHELF: "http://nas.local:13378",
    SERVICE_SONARR: "http://nas.local:8989",
    SERVICE_RADARR: "http://nas.local:7878",
    SERVICE_SEERR: "http://nas.local:5055",
    SERVICE_EBOOKS: "http://nas.local:8095",
}

# Options
OPT_LIST_MINUTES = "list_minutes"
OPT_LIVE_SECONDS = "live_seconds"
OPT_ITEM_COUNT = "item_count"
OPT_DAYS_AHEAD = "days_ahead"
OPT_AVAILABILITY_ENTITY = "availability_entity"
OPT_SHOW_CINEMA = "show_cinema"
# Seerr: who gets told when a wish is fulfilled
OPT_NOTIFY_MAP = "notify_map"  # {seerr user id (str): notify service name}
OPT_MIN_REQUEST_DAYS = "min_request_days"
DEFAULT_MIN_REQUEST_DAYS = 7

DEFAULT_LIST_MINUTES = 60
# The e-book list is small and changes when someone drops a book: ask more often
DEFAULT_LIST_MINUTES_BY_SERVICE = {SERVICE_EBOOKS: 10}
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

EVENT_EBOOK_SENT = f"{DOMAIN}_ebook_sent"
EVENT_REQUEST_AVAILABLE = f"{DOMAIN}_request_available"

REQUEST_TIMEOUT = 15
