# CLAUDE.md — APRS-IS Home Assistant Integration

Context for AI-assisted development on this project.

## What this project is

A HACS custom integration (`custom_components/aprs_is`) that connects Home Assistant to the APRS-IS network. It maintains a persistent TCP connection, parses incoming APRS packets via `aprslib`, and exposes HA entities for positions, weather, and messages.

## Repository layout

```
custom_components/aprs_is/
  __init__.py          # Entry setup/teardown, service registration
  coordinator.py       # TCP connection, packet parsing, callbacks, outbound sending
  config_flow.py       # Initial setup + multi-step options flow
  sensor.py            # All sensor entities
  device_tracker.py    # Position tracker entities
  geo_location.py      # Geo location (map pin) entities
  weather.py           # WeatherEntity entities
  symbols.py           # APRS symbol table lookup (aprs_symbol_name helper)
  const.py             # All constants (no logic)
  manifest.json        # HACS/HA manifest (aprslib==0.7.2)
  services.yaml        # Action UI descriptors
  strings.json         # UI strings (source of truth)
  translations/en.json # English translation (mirrors strings.json exactly)
.github/workflows/
  validate.yml         # Runs on push/PR: HACS validation, hassfest, ruff
  release.yml          # workflow_dispatch: bumps manifest version, tags, creates GH release
```

## Key architectural decisions

### Terminology
A full APRS identifier like `KE5YIM-9` is called a **callsign**; the `-9` suffix is the **SSID**. The integration uses "callsign" throughout (the full identifier including any SSID suffix). "SSID" alone only appears in descriptions where it refers specifically to the numeric suffix.

### Login callsign is connection-only
The callsign used to log in to APRS-IS (e.g. `KE5YIM` or `KE5YIM-1`). SSID is optional. It is used purely as a credential and to receive inbound messages. It gets no device tracker. Everything else is a sub-device under the connection device. Can be changed via the **Reconfigure** option in the integration's `⋮` menu.

### Stations (`CONF_STATIONS`)
A single unified list replaces the old monitored/tracked split. Each entry has `callsign` and `position_type` (`none` / `device_tracker` / `geo_location`). Any callsign can be added — there is no base-callsign restriction.

**My stations** are determined at runtime via `coordinator.is_my_callsign()`: if the station's base callsign matches the login's base callsign, it is one of your stations. This distinction currently affects only the device model label ("My Station" vs "Tracked Station"). The notify platform has been removed — use `aprs_is.send_message` instead.

Each station gets three sensors: `CallsignRxPacketsSensor`, `LastSeenSensor`, and `SymbolSensor`. Weather stations get the same three plus the full set of `WeatherSensor` entities. `SymbolSensor` reads `symbol_table` and `symbol` from the parsed aprslib packet and looks them up in `symbols.APRS_SYMBOL_NAMES` to produce a human-readable state (e.g. "Car", "Weather Station"). It falls back to the raw two-character string for unknown codes. Overlay symbols (digit or letter as the table char) are looked up in the alternate table with the overlay appended.

### Message ACK and retry
Outbound messages sent as the login callsign include a `{NNNNN` message number (no closing brace — APRS spec) and are retried up to 6 times (`_MSG_RETRY_DELAYS`) until an ACK is received. When `from_call` differs from the login callsign, no message number is added and no retry occurs, since ACKs would be addressed to a callsign we don't receive messages for.

Incoming ACKs are detected via `packet.get("response") == "ack"` (aprslib's parsed field) with a fallback to `message_text.startswith("ack")`. REJ packets are silently discarded.

### Push-based coordinator (not DataUpdateCoordinator)
`AprsIsCoordinator` runs a persistent TCP listener loop with exponential backoff reconnect (5s → 300s). Entities register callbacks and are notified on each packet. There is no polling.

### Outbound actions

Eight actions are registered under the `aprs_is` domain: `send_message`, `send_bulletin`, `send_announcement`, `send_wx_report`, `send_wx_report_from_entities`, `send_object`, `delete_object`, and `send_position`.

`send_wx_report` takes raw values in specific units (°F, mph, hundredths-of-inch, etc.) — useful with templates.

`send_wx_report_from_entities` takes HA entity IDs; the handler in `__init__.py` reads each entity's state and `unit_of_measurement` and converts using `homeassistant.util.unit_conversion` (`TemperatureConverter`, `PressureConverter`, `SpeedConverter`). Rain is converted with simple math (mm → hundredths of an inch). Unavailable or non-numeric entities are silently skipped.

`send_position` sends a standard APRS position report (`!` packet). Speed is taken in mph and converted to knots for the course/speed data extension. Altitude goes in the comment as `/A=XXXXXX` (feet). Symbol defaults to `/>` (car).

### aprslib unit conversions — important gotcha
aprslib converts raw APRS values to metric/SI in its parsed output. Do NOT assume raw APRS units:

| Field | aprslib output | Notes |
|---|---|---|
| `weather.temperature` | Celsius | APRS packet stores °F |
| `weather.wind_gust` | m/s | Correctly converted from mph |
| `weather.rain_*` | mm | Converted from hundredths-of-inch |
| `weather.pressure` | hPa | Correct, no conversion needed |
| `speed` (top-level) | km/h | **Bug**: aprslib treats mph wind speed as knots — we correct with `/ 1.852 * 0.44704` to get m/s |
| `course` (top-level) | degrees | Correct |

Wind speed and direction for WX packets are **not** in the `weather` sub-dict. aprslib puts them at the top level as `speed` and `course`. Both `WeatherSensor._handle_callback` and `AprsWeatherEntity._handle_callback` merge these into the wx dict with the knots-correction applied.

### Device hierarchy
All tracked callsigns and weather stations are sub-devices under the connection device using `DeviceInfo(via_device=(DOMAIN, coordinator.callsign))`. HA renders this as a device hierarchy in the UI.

### Message deduplication
APRS-IS can deliver the same message multiple times. The coordinator keeps a rolling 2-hour dedup window by `(from_call, msgid)` to suppress duplicate persistent notifications.

### Server-side filter
`coordinator._build_filter()` builds the APRS-IS filter string from options. All callsign lists within each filter term are sorted alphabetically for consistency:
- `b/` — FROM all configured stations + weather stations
- `g/` — messages TO the login callsign only
- `r/` — range filter centred on HA's lat/lon (if radius > 0)
- Extra terms appended verbatim from options

## Python / tooling

- **Python 3.12+** required (HA 2026.1+). Install via pyenv if needed.
- **Virtual env**: `.venv/` at repo root — `source .venv/bin/activate`
- **Linter**: ruff. Run: `ruff check --fix custom_components/aprs_is/`
- **Syntax check**: `python -c "import ast, pathlib; [ast.parse(f.read_text()) for f in pathlib.Path('custom_components/aprs_is').glob('*.py')]"`
- **aprslib version**: 0.7.2 (0.7.3 does not exist — do not bump without checking PyPI)

## Strings / translations

`strings.json` is the source of truth. `translations/en.json` must mirror it exactly. Both files must be updated together whenever the config flow gains new steps or fields. The options flow uses `async_show_menu` for navigation — menu step strings go under `menu_options`, not `data`.

## What is NOT implemented (deferred)

- **APRS telemetry** (Tier 1 raw channels) — out of scope for now
- **Bulletin reception** — decided against; would need range filter + dedup and adds complexity

## Testing in HA

Copy `custom_components/aprs_is/` to `<ha-config>/custom_components/aprs_is/` and restart. No GitHub release required for local testing. Check **Settings → System → Logs** for import errors.

## Releasing

Use the `release` workflow (`workflow_dispatch`) in GitHub Actions. It takes a semver version input, validates it, updates `manifest.json`, commits, tags, and creates a GitHub Release. HACS picks up new versions from GitHub Releases.
