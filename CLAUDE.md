# CLAUDE.md — APRS-IS Home Assistant Integration

Context for AI-assisted development on this project.

## What this project is

A HACS custom integration (`custom_components/aprs_is`) that connects Home Assistant to the APRS-IS network. It maintains a persistent TCP connection to APRS-IS and an optional concurrent TCP KISS TNC connection (e.g. Direwolf), parses incoming APRS packets via `aprslib`, and exposes HA entities for positions, weather, and messages.

## Repository layout

```
custom_components/aprs_is/
  __init__.py          # Entry setup/teardown, service registration
  coordinator.py       # APRS-IS + KISS TNC connections, packet parsing, callbacks, outbound routing
  config_flow.py       # Initial setup + multi-step options flow
  kiss.py              # KISS framing + AX.25 UI encode/decode (no third-party deps)
  sensor.py            # All sensor entities (including KISS TNC stats sensors)
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

### entry.data vs entry.options
`entry.data` holds only the two true credentials: `callsign` and `passcode`. Everything else — including `host` and `port` — lives in `entry.options` and is changed via the options flow. This is intentional: host/port are connection behaviour, not identity. The coordinator reads host/port from `entry.options` with defaults (`rotate.aprs.net:14580`). `aprs_is_configured` checks `entry.options.get(CONF_HOST)`.

### Options flow menu order
`aprs_is` → `kiss_tnc` → `station_beacon` → `wx_beacon` → `stations` → `weather_stations`. This groups by function: connections first, then outbound beacons, then inbound station tracking.

### Stations (`CONF_STATIONS`)
A single unified list replaces the old monitored/tracked split. Each entry has `callsign` and `position_type` (`none` / `device_tracker` / `geo_location`). Any callsign can be added — there is no base-callsign restriction.

**My stations** are determined at runtime via `coordinator.is_my_callsign()`: if the station's base callsign matches the login's base callsign, it is one of your stations. This distinction currently affects only the device model label ("My Station" vs "Tracked Station"). The notify platform has been removed — use `aprs_is.send_message` instead.

Each station gets three sensors: `CallsignRxPacketsSensor`, `LastSeenSensor`, and `SymbolSensor`. Weather stations get the same three plus the full set of `WeatherSensor` entities. `SymbolSensor` reads `symbol_table` and `symbol` from the parsed aprslib packet and looks them up in `symbols.APRS_SYMBOL_NAMES` to produce a human-readable state (e.g. "Car", "Weather Station"). It falls back to the raw two-character string for unknown codes. Overlay symbols (digit or letter as the table char) are looked up in the alternate table with the overlay appended.

### Message ACK and retry
Outbound messages sent as the login callsign include a `{NNNNN` message number (no closing brace — APRS spec) and are retried up to 6 times (`_MSG_RETRY_DELAYS`) until an ACK is received. When `from_call` differs from the login callsign, no message number is added and no retry occurs, since ACKs would be addressed to a callsign we don't receive messages for.

Incoming ACKs are detected via `packet.get("response") == "ack"` (aprslib's parsed field) with a fallback to `message_text.startswith("ack")`. REJ packets are silently discarded.

ACK receipt and retry are **transport-agnostic**: an ACK arriving via either APRS-IS or KISS TNC cancels the retry task (keyed on `(sender, msgid)`). Retry attempts use the `transport` value captured at send time — `auto` uses `_tx_order()` on each attempt (enabling failover without resetting the retry count); explicit `aprs_is` or `kiss_tnc` sticks to that transport across all retries.

### Push-based coordinator (not DataUpdateCoordinator)
`AprsIsCoordinator` runs two independent persistent TCP listener loops — one for APRS-IS and one for the optional KISS TNC — each with exponential backoff reconnect (5s → 300s). Both loops run concurrently and feed the same entity callback pipeline via `_process_packet()`. Entities register callbacks and are notified on each packet. There is no polling.

### KISS TNC transport (`kiss.py`)
Pure-Python KISS framing and AX.25 UI encode/decode with no third-party dependencies. Used by the coordinator for both inbound frame parsing and outbound packet encoding.

Inbound: raw TCP bytes → KISS frame assembly (FEND delimiters) → unescape → `parse_ax25_frame()` → reconstruct APRS-IS format string → `_handle_kiss_line()` → local filter (FROM configured stations OR messages TO login callsign) → `_process_packet()`.

Outbound: APRS-IS format string → extract source + info → `encode_ax25_ui(source, "APRS", rf_path_digipeaters, info)` → `encode_kiss_frame()` → write to TCP socket.

### TOCALL
All outbound packets use `APRS_TOCALL = "APZHA"` as the AX.25 destination field (the TOCALL). `APZ` is the experimental/unregistered prefix per the APRS spec; `HA` identifies Home Assistant. The intent is to register a permanent TOCALL via aprs.org/aprs11/tocalls.txt before a stable release. To change it later, update only `APRS_TOCALL` in `const.py` — all packet formatters and the KISS TNC encoder reference it.

### Outbound transmit routing
`_tx_order()` returns transports in preferred order based on `CONF_TX_PRIMARY` (`aprs_is` or `kiss_tnc`). `_send()`, `_send_ack()`, and `_message_retry_loop()` all use `_tx_order()` for consistent routing. The passcode `-1` receive-only guard is scoped to the APRS-IS branch only — KISS TNC transmit is independent of the APRS-IS passcode.

Per-transport stats are tracked separately: `rx_packets`/`tx_packets`/`tx_messages` for APRS-IS; `kiss_rx_packets`/`kiss_tx_packets`/`kiss_tx_messages` for KISS TNC. Four KISS TNC sensors are registered under a dedicated device when `kiss_configured` is True.

### Per-service-call transport and NOGATE

Every outbound action accepts `transport` and `nogate` keyword arguments (and corresponding service call fields).

`transport` values: `auto` (use `_tx_order()` with fallback), `aprs_is` (APRS-IS only), `kiss_tnc` (KISS TNC only), `both` (send on both simultaneously). `both` is excluded from `send_message` — APRS radios deduplicate messages by `(from_call, msgid)` but behavior varies enough that duplicate delivery is unacceptable.

When `transport == TRANSPORT_BOTH`, `_send()` sends on APRS-IS first, then KISS TNC. NOGATE is forced on the KISS copy only when APRS-IS is connected and has a valid passcode — this prevents nearby IGates from re-injecting the RF copy back onto APRS-IS. If APRS-IS is disconnected or receive-only, NOGATE is not forced so IGates can pick up the RF copy and inject it onto APRS-IS. Both transport counters are incremented. If only one transport is available, that one is used with no error.

`nogate=True` appends `,NOGATE` to the AX.25 digipeater path in `_kiss_write_packet()`. It is silently ignored for APRS-IS transmissions.

For `send_message`, the chosen `transport` and `nogate` values are captured at call time and passed through to `_message_retry_loop()`, which uses them consistently across all retry attempts.

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

## Python / tooling

- **Python 3.12+** required (HA 2026.1+). Install via pyenv if needed.
- **Virtual env**: `.venv/` at repo root — `source .venv/bin/activate`
- **Linter**: ruff. Install if needed: `pip install ruff`. Run: `ruff check --fix custom_components/aprs_is/`
- **Syntax check**: `python -c "import ast, pathlib; [ast.parse(f.read_text()) for f in pathlib.Path('custom_components/aprs_is').glob('*.py')]"` (use venv Python — system Python 3.10 chokes on 3.12 syntax)
- **aprslib version**: 0.7.2 (0.7.3 does not exist — do not bump without checking PyPI)

## Tests

Unit tests live in `tests/`. Run with:

```
source .venv/bin/activate
python -m pytest tests/ -v
```

Install test deps if needed:
```
pip install pytest==9.0.3 pytest-asyncio==1.3.0 pytest-homeassistant-custom-component==0.13.331 aprslib==0.7.2
```

**How the test environment works**: `pytest-homeassistant-custom-component` installs a real `homeassistant` package (currently 2026.5.2) and provides a `hass` fixture that runs a full in-memory HA instance per test. Use `MockConfigEntry` from `pytest_homeassistant_custom_component.common` to create config entries. All imports work against the real packages — no stubs needed.

**What is covered**:
- `kiss.py` — full encode/decode + roundtrip coverage (`tests/test_kiss.py`)
- `symbols.py` — all table lookups and overlay branches (`tests/test_symbols.py`)
- `coordinator.py` pure functions — `_lat_to_aprs`, `_lon_to_aprs`, `_classify_packet` (`tests/test_coordinator_utils.py`)
- `coordinator.py` packet formatters — `_build_wx_packet`, `_build_object_packet` (`tests/test_packet_formatters.py`)
- `coordinator.py` HA-coupled logic — `_build_filter`, `_tx_order`, `_send`, `_handle_kiss_line`, `is_my_callsign`, `_is_duplicate_message`, `_check_rate_limit`, `_next_msg_id` (`tests/test_coordinator.py`)

**What is NOT covered**:
- Message retry loop (`_message_retry_loop`)
- Config flow steps, entity callbacks, service handlers

CI runs the full test suite on every push and PR (`.github/workflows/validate.yml`, `test` job).

## Strings / translations

`strings.json` is the source of truth. `translations/en.json` must mirror it exactly. Both files must be updated together whenever the config flow gains new steps or fields. The options flow uses `async_show_menu` for navigation — menu step strings go under `menu_options`, not `data`.

## What is NOT implemented (deferred)

- **APRS telemetry** (Tier 1 raw channels) — out of scope for now
- **Bulletin reception** — decided against; would need range filter + dedup and adds complexity

## Testing in HA

Copy `custom_components/aprs_is/` to `<ha-config>/custom_components/aprs_is/` and restart. No GitHub release required for local testing. Check **Settings → System → Logs** for import errors.

## Releasing

Use the `release` workflow (`workflow_dispatch`) in GitHub Actions. It takes a semver version input, validates it, updates `manifest.json`, commits, tags, and creates a GitHub Release. HACS picks up new versions from GitHub Releases.
