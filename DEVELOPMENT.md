# TobiGT

MIDI ↔ UDP bridge for controlling **PiPedal** (guitar amp sim on Raspberry Pi) from an ESP pedalboard over WiFi hotspot.

## Two codebases in one repo

| Where | What | MIDI backend | Target |
|-------|------|--------------|--------|
| Root `/` | Legacy Guitarix/JACK scripts (Guitarix headless) | `mido.backends.rtmidi/UNIX_JACK` | `gx_head_amp:midi_in_1` |
| `tobigt-puente-pipedal/` | Current PiPedal bridge + ESP firmware | `mido.backends.rtmidi/ALSA` (no JACK) | `PiPedal:in` (ALSA seq) |

## New bridge + ESP: `tobigt-puente-pipedal/`

Three async layers in `animalMidi.py`:

1. **UDP ← ESP** (`0.0.0.0:20001`) — commands: `boost` (toggle), `kl` (keepalive), `note_on channel=0 note=N`
2. **MIDI → PiPedal** — forwards parsed commands as MIDI via ALSA sequencer
3. **WebSocket ← PiPedal** (`ws://127.0.0.1:80/pipedal`) — events forwarded to ESP:
   - `onBanksChanged` / `getBankIndex` reply → `k:<bank_name>` → **tmA** (con scroll)
   - `onPresetsChanged` → `b:<preset_name>` → **tmA** (directo)
   - `onPedalboardChanged` / `currentPedalboard` reply → `p:<pedalboard.name>` → **tmA** (directo)
   - `onSelectedSnapshotChanged` → `s:<snapshot_name>` → **tmB** (directo)
   - Wire format: `[{"message": "<event>"}, <body>]`

UDP replies: `boost+`, `boost-`, `klok`, `ok`, `-1`, `k:<name>`, `b:<name>`, `p:<name>`, `s:<name>`.

**ESP stateless** — todo el estado vive en PiPedal. La ESP solo manda notas fijas:
- `note=70` → Next Preset (BANCO short, FD/FI in preset mode)
- `note=71` → Previous Preset (FI in preset mode)
- `note=72` → Next Bank (PROG short press)
- `note=76` → Next Snapshot (FD button)
- `note=77` → Previous Snapshot (FI button)
- `boost` → toggle MIDI note 60

**Preset selection mode** (BANCO long press): FD/FI remapped to preset navigation (notes 70/71). BANCO or BOOST exits back to normal mode.

**Display mapping:**
- **tmA** = preset (`b:`/`p:`)
- **tmB** = snapshot (`s:`)
- `k:` (bank) no se muestra en pantalla

**Firmware ESP:** `esp-firmware/main.py` incluido en este repo.

### PROG menu (long-press PROG button)

Menú navegable con FD/FI, confirmar con BANCO, cancelar con BOOST o cualquier botón.

| Opción | tmA | Acción |
|--------|-----|--------|
| Shutdown | `ShUt` | Envía `note=73` → PiPedal: System Shutdown |
| Reboot | `rEbt` | Envía `note=74` → PiPedal: System Reboot |
| Hotspot | `Hot` | Envía `note=75` → PiPedal: Toggle Hotspot |
| Deep sleep | `SLP` | `machine.deepsleep()` (local) |
| Salir | `ESC` | Sale sin acción |

Al confirmar (excepto ESC): countdown 5→0 en tmB. Cualquier botón cancela.

### PiPedal WebSocket protocol

All messages are JSON arrays: `[{"message": "<name>"[, "replyTo"/"reply": <int>]}[, <body>]]`.

**Handshake (required!):**
1. Connect → send `[{"message": "hello"}]`
2. PiPedal replies `[{"message": "ehlo", "reply": <id>}, <clientId>]`
3. PiPedal then pushes all async notification events with current state

Without the "hello" handshake, PiPedal **does not push any events** and most query messages are rejected.

**Key request messages (body omitted):**
| Send | Reply | Purpose |
|------|-------|---------|
| `hello` | `ehlo` + clientId | Handshake |
| `getBankIndex` | `getBankIndex` + BankIndex | Current bank/setlist |
| `currentPedalboard` | `currentPedalboard` + Pedalboard | Current pedalboard name + snapshots |

**Key async push events:**
| Event | Body | Purpose |
|-------|------|---------|
| `onBanksChanged` | BankIndex | Bank list/index changed |
| `onPresetsChanged` | `{clientId, presets: {selectedInstanceId, presets}}` | Preset list changed |
| `onPedalboardChanged` | `{clientId, pedalboard}` | Pedalboard name + snapshots |
| `onSelectedSnapshotChanged` | int (index) | Snapshot selection changed |

**`currentPedalboard`** not `getPedalboard` — the latter is **unknown** to PiPedal.

### Critical: ESP must listen persistently for async UDP

The bridge sends `k:`/`b:`/`p:`/`s:` asynchronously from WebSocket events. The ESP **cannot** use ephemeral sockets (`sendto` + single `recvfrom` + close) — the async packets arrive after the socket is closed or on a different port.

**ESP firmware fix:**
- Single **persistent** global UDP socket created at startup, `setblocking(False)`
- `enviarudp()` reuses this socket: `sendto()` then non-blocking `recvfrom` loop for ~2s collecting ALL responses into a list
- `control_UDP()` iterates the list: `k:`/`b:`/`p:`/`s:` update display; `ok`/`boost` returned as command result
- Main loop calls `poll_async_udp()` between iterations to catch messages that arrive outside the command window

### PiPedal hierarchy

- **Banco** = setlist/repertoire — **Preset** = song/pedalboard — **Snapshot** = song section

### Setup

```sh
cd tobigt-puente-pipedal && ./setup.sh
```

**IMPORTANT:** Run as your normal user, NOT with `sudo`. The script uses `sudo` internally where needed (apt, systemd). Running the whole script with `sudo` changes `$HOME` to `/root`, creating the venv at `/root/.animalmidi-pipedal/` and making the systemd service run as root — which **breaks the ALSA sequencer connection** to PiPedal.

- Creates venv `~/.animalmidi-pipedal/` with `--system-site-packages` (apt packages: `python3-rtmidi`, `python3-websockets`; pip: `mido`)
- Installs systemd service `animalmidi.service` (`After=pipedald.service`)
- Writes env file `/etc/animalmidi/env` (all `TOBIGT_*` vars optional, documented in file)
- Service management: `systemctl [start|stop|status|restart] animalmidi`

### Runtime config

All config via environment (defaults in `animalMidi.py:43-54`). Override in `/etc/animalmidi/env`:

| Var | Default |
|-----|---------|
| `TOBIGT_UDP_HOST` | `0.0.0.0` |
| `TOBIGT_UDP_PORT` | `20001` |
| `TOBIGT_ESP_HOST` | `192.168.60.195` |
| `TOBIGT_ESP_PORT` | `4097` |
| `TOBIGT_PIPEDAL_WS` | `ws://127.0.0.1:80/pipedal` |
| `TOBIGT_PIPEDAL_MIDI` | `PiPedal:in` |
| `TOBIGT_MIDI_BACKEND` | `mido.backends.rtmidi/LINUX_ALSA` |

MIDI port opens with `client_name="TobiGT"` (visible via `aconnect -i` / `aseqdump -l`).

WiFi hotspot: SSID `tobiGT`, PSK `animalito`, created via `nmcli` (`hotspotUp.sh`).

## Legacy (root)

- `animalMidi.py:65` has a **known bug**: uses undefined variable `text` instead of `message` → crashes on MIDI input
- Old entrypoint: `/home/tobi/.animalmidi/bin/python3 /home/tobi/animalMidi.py`
- `udp_asyncServer.py` — standalone echo server for testing (`127.0.0.1:9999`)

## No toolchain

No package manager, tests, linter, formatter, type checker, or CI. Hotspot uses `nmcli`.
