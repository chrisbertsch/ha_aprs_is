"""Constants for the APRS-IS integration."""

DOMAIN = "aprs_is"

# APRS-IS connection defaults
DEFAULT_HOST = "rotate.aprs.net"
DEFAULT_PORT = 14580
RECEIVE_ONLY_PASSCODE = -1

# Config entry keys
CONF_CALLSIGN = "callsign"
CONF_PASSCODE = "passcode"
CONF_HOST = "host"
CONF_PORT = "port"

# Options keys
CONF_STATIONS = "stations"
CONF_WEATHER_STATIONS = "weather_stations"
CONF_EVENT_RATE_LIMIT = "event_rate_limit"
# Range filter uses HA's configured home lat/lon automatically
CONF_RANGE_FILTER_RADIUS = "range_filter_radius"
# Appended verbatim after the auto-generated filter string
CONF_FILTER_EXTRA = "filter_extra"
CONF_BEACON_INTERVAL = "beacon_interval"

# WX beacon options
CONF_WX_BEACON_INTERVAL = "wx_beacon_interval"
CONF_WX_BEACON_FROM_CALL = "wx_beacon_from_call"
CONF_WX_BEACON_COMMENT = "wx_beacon_comment"
CONF_WX_BEACON_LATITUDE = "wx_beacon_latitude"
CONF_WX_BEACON_LONGITUDE = "wx_beacon_longitude"
CONF_WX_STALENESS_ENTITY = "wx_staleness_entity"
CONF_WX_STALENESS_MAX_AGE = "wx_staleness_max_age"
CONF_WX_ENT_TEMP = "wx_ent_temp"
CONF_WX_ENT_HUMIDITY = "wx_ent_humidity"
CONF_WX_ENT_PRESSURE = "wx_ent_pressure"
CONF_WX_ENT_WIND_SPEED = "wx_ent_wind_speed"
CONF_WX_ENT_WIND_DIR = "wx_ent_wind_dir"
CONF_WX_ENT_WIND_GUST = "wx_ent_wind_gust"
CONF_WX_ENT_RAIN_1H = "wx_ent_rain_1h"
CONF_WX_ENT_RAIN_24H = "wx_ent_rain_24h"
CONF_WX_ENT_RAIN_MIDNIGHT = "wx_ent_rain_midnight"
CONF_WX_ENT_LUMINOSITY = "wx_ent_luminosity"

# Per-station option keys
CONF_POSITION_TYPE = "position_type"

# Position type values
POSITION_TYPE_NONE = "none"
POSITION_TYPE_DEVICE_TRACKER = "device_tracker"
POSITION_TYPE_GEO_LOCATION = "geo_location"

# Defaults
DEFAULT_EVENT_RATE_LIMIT = 0  # 0 = unlimited
DEFAULT_RANGE_FILTER_RADIUS = 0  # 0 = disabled
DEFAULT_BEACON_INTERVAL = 0  # 0 = disabled
DEFAULT_WX_BEACON_INTERVAL = 0  # 0 = disabled
DEFAULT_WX_STALENESS_MAX_AGE = 10  # minutes

# APRS-IS login banner
APRS_SOFTWARE_NAME = "homeassistant-aprs-is"
APRS_SOFTWARE_VERSION = "0.1.0"

# HA event names
EVENT_PACKET_RECEIVED = f"{DOMAIN}_packet_received"
EVENT_POSITION_RECEIVED = f"{DOMAIN}_position_received"
EVENT_WEATHER_RECEIVED = f"{DOMAIN}_weather_received"
EVENT_MESSAGE_RECEIVED = f"{DOMAIN}_message_received"
EVENT_BULLETIN_RECEIVED = f"{DOMAIN}_bulletin_received"
EVENT_PACKET_SENT = f"{DOMAIN}_packet_sent"

# aprslib packet format values
PACKET_TYPE_POSITION = "position"
PACKET_TYPE_WEATHER = "wx"
PACKET_TYPE_MESSAGE = "message"
PACKET_TYPE_OBJECT = "object"
PACKET_TYPE_STATUS = "status"
PACKET_TYPE_BULLETIN = "bulletin"

# HA service/action names
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_SEND_BULLETIN = "send_bulletin"
SERVICE_SEND_ANNOUNCEMENT = "send_announcement"
SERVICE_SEND_WX_REPORT = "send_wx_report"
SERVICE_SEND_OBJECT = "send_object"
SERVICE_DELETE_OBJECT = "delete_object"
SERVICE_SEND_POSITION = "send_position"
SERVICE_SEND_WX_FROM_ENTITIES = "send_wx_report_from_entities"
