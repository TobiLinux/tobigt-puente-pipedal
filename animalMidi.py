#!/usr/bin/env python3
"""
TobiGT — Puente MIDI ↔ UDP para PiPedal.

Arquitectura:
  ESP pedalboard ──UDP──→ animalMidi.py ──ALSA MIDI──→ PiPedal:in
                 boost, kl, note_on         (sequencer)

  ESP ←──UDP── animalMidi.py ←─WebSocket── PiPedal :80/pipedal
              b:nombreBanco        onBanksChanged
              p:nombrePreset       onPedalboardChanged
              s:nombreSnapshot     onSelectedSnapshotChanged

Tres capas asíncronas conviven en un event loop:
  1. UDP server  ← recibe comandos de la pedalera ESP
  2. MIDI output → los reenvía como mensajes MIDI a PiPedal
  3. WebSocket   ← escucha cambios de estado en PiPedal y los
                   refleja de vuelta a la ESP por UDP

Requiere:
  - python3-rtmidi (desde apt, con soporte ALSA)
  - python3-websockets (desde apt)
  - mido (pip)

Configurar con:  ./setup.sh

"""


import asyncio
import json
import logging
import os
import signal
import subprocess
import mido
import websockets

# MIDI note → nombre de nota (siempre sostenido)
NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


# =============================================================================
# Configuración — por entorno (con defaults), sobreescribir según el setup
# =============================================================================

UDP_HOST = os.environ.get("TOBIGT_UDP_HOST", "0.0.0.0")
UDP_PORT = int(os.environ.get("TOBIGT_UDP_PORT", "20001"))

ESP_HOST = os.environ.get("TOBIGT_ESP_HOST", "192.168.60.195")
ESP_PORT = int(os.environ.get("TOBIGT_ESP_PORT", "4097"))
ESP_ADDR = (ESP_HOST, ESP_PORT)

PIPEDAL_WS = os.environ.get("TOBIGT_PIPEDAL_WS", "ws://127.0.0.1:80/pipedal")

PIPEDAL_MIDI = os.environ.get("TOBIGT_PIPEDAL_MIDI", "PiPedal:in")

MIDI_BACKEND = os.environ.get("TOBIGT_MIDI_BACKEND", "mido.backends.rtmidi/LINUX_ALSA")


# =============================================================================
# Estado — instancia compartida entre capas
# =============================================================================

class AppState:
    def __init__(self):
        self.boost = False
        self.last_pedalboard = {}
        self.next_reply_id = 1
        self.last_esp_addr = None
        self.ws_request_queue = None
        self.ws_client_id = None
        self.tuner_instance_id = None
        self.tuner_sub_handle = None
        self.tuner_subscribed = False
        self.tuner_sub_pending = False
        self.tuner_activated = False
        self.mute_state = 0
        self.mute_state_known = False


# =============================================================================
# Capa 1 — Servidor UDP (recibe comandos de la pedalera ESP)
# =============================================================================

class UDPProtocol(asyncio.DatagramProtocol):
    """
    Manejador de datagramas UDP. Encola cada mensaje recibido para que
    udp_controller() lo procese de forma asíncrona, sin bloquear aquí.
    """

    def __init__(self, queue, state):
        self.transport = None
        self.queue = queue
        self.state = state

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        msg = data.decode("utf-8")
        self.state.last_esp_addr = addr
        self.queue.put_nowait((msg, addr))

    def error_received(self, exc):
        logging.error(f"UDP error: {exc}")

    def connection_lost(self, exc):
        logging.warning("UDP connection lost")


# =============================================================================
# Capa 2 — Traducción UDP → MIDI (hacia PiPedal)
# =============================================================================

def udp_send(transport, msg, state):
    """
    Envía un mensaje de texto a la ESP por UDP.
    Usa la última dirección desde la que la ESP nos envió un mensaje,
    o el ESP_ADDR de configuración si aún no ha contactado.
    Lo usan los callbacks del WebSocket para reflejar el estado de PiPedal.
    """
    addr = state.last_esp_addr or ESP_ADDR
    logging.info("UDP >> %s -> %s:%s", msg, addr[0], addr[1])
    transport.sendto(msg.encode("utf-8"), addr)


def midi_to_GT(msg, port, state):
    """
    Traduce un comando UDP a un mensaje MIDI y lo envía a PiPedal.

    Comandos actuales:
      "boost"                     → toggle nota 60 (on/off)
      "kl"                        → solo responde "klok" (keepalive)
      "note_on channel=0 note=N"  → reenvía tal cual a PiPedal
      cualquier Message MIDI raw  → se parsea con mido y se envía

    Retorna la respuesta textual que se envía de vuelta a la ESP,
    o None si no hay respuesta.
    """
    if msg == "boost":
        if not state.boost:
            port.send(mido.Message.from_str("note_on channel=0 note=60 velocity=127"))
            state.boost = True
            return "boost+"
        port.send(mido.Message.from_str("note_on channel=0 note=60 velocity=0"))
        state.boost = False
        return "boost-"

    if msg == "kl":
        return "klok"

    try:
        m = mido.Message.from_str(msg)
        # note 78: MUTE toggle via WS setControl (MIDI binding buggy en PiPedal)
        if m.type == "note_on" and m.note == 78:
            return "__mute_toggle__"
        logging.info("MIDI >> %s", m)
        port.send(m)
        return "ok"
    except Exception as e:
        logging.warning("MIDI error: %s", e)
        return "-1"


# =============================================================================
# Capa 3 — WebSocket (recibe estado de PiPedal)
# =============================================================================

def handle_banks(body, transport, state):
    if not isinstance(body, dict) or "selectedBank" not in body:
        return
    selected = body["selectedBank"]
    for entry in body.get("entries", []):
        if entry.get("instanceId") == selected:
            name = entry.get("name", "")
            if name:
                logging.info("Bank: %s", name)
                udp_send(transport, f"k:{name}", state)
            return


def handle_presets(body, transport, state):
    """
    Procesa el evento onPresetsChanged (reemplazo de onBanksChanged
    en versiones recientes de PiPedal).

    El body trae:
      { "clientId": ..., "presets": {
          "selectedInstanceId": <id>,
          "presets": [{ "instanceId": ..., "name": "...", ... }, ...]
        }
      }
    """
    if not isinstance(body, dict) or "presets" not in body:
        return
    pd = body["presets"]
    sid = pd.get("selectedInstanceId")
    for entry in pd.get("presets", []):
        if entry.get("instanceId") == sid:
            name = entry.get("name", "")
            if name:
                logging.info("Preset (from presets list): %s", name)
                udp_send(transport, f"b:{name}", state)
            return


def handle_pedalboard(body, transport, state):
    if not isinstance(body, dict):
        return
    pb = body.get("pedalboard", body)
    name = pb.get("name", "")
    state.last_pedalboard["snapshots"] = pb.get("snapshots", [])

    # Detectar instancia del afinador TooB Tuner y suscribirse
    for key in ("pedalboardItems", "items", "serializedPedalboard"):
        items = pb.get(key)
        if isinstance(items, list):
            for item in items:
                uri = item.get("uri", "")
                if isinstance(uri, str) and "toob-tuner" in uri.lower():
                    state.tuner_instance_id = item.get("instanceId")
                    logging.info("Tuner instanceId=%s", state.tuner_instance_id)
                    q = state.ws_request_queue
                    if q is None:
                        logging.warning("Tuner: ws_request_queue is None, skipping")
                    else:
                        tuner_activated = item.get("isEnabled", False)
                        logging.info("Tuner: found instanceId=%s activated=%s client=%s",
                            state.tuner_instance_id, tuner_activated, state.ws_client_id)
                        # Extraer estado de controles
                        for cv in item.get("controlValues", []):
                            k = cv.get("key")
                            v = cv.get("value")
                            if k == "MUTE":
                                state.mute_state = v if v is not None else 0
                                state.mute_state_known = True
                        if not state.tuner_activated:
                            state.tuner_activated = True
                            logging.info("Tuner: first activation for instance %s",
                                state.tuner_instance_id)
                        # Suscribir monitorPort solo si no hay suscripción activa o pendiente
                        if not state.tuner_subscribed and not state.tuner_sub_pending:
                            state.tuner_sub_pending = True
                            q.put_nowait(({"message": "monitorPort"},
                                {"instanceId": state.tuner_instance_id, "key": "FREQ",
                                    "updateRate": 0.03333}))
                    break

    if name:
        logging.info("Pedalboard: %s", name)
        udp_send(transport, f"p:{name}", state)
    sel_idx = pb.get("selectedSnapshot")
    if isinstance(sel_idx, int):
        handle_snapshot(sel_idx, transport, state)


def handle_snapshot(index, transport, state):
    if not isinstance(index, int) or index < 0:
        return
    snapshots = state.last_pedalboard.get("snapshots", [])
    if 0 <= index < len(snapshots):
        snap = snapshots[index]
        if isinstance(snap, dict):
            name = snap.get("name", "")
            if name:
                logging.info("Snapshot: %s", name)
                udp_send(transport, f"s:{name}", state)


async def ws_loop(udp_transport, state, stop_event):
    """
    Bucle principal de WebSocket. Mantiene conexión con PiPedal,
    procesa eventos push y también drena peticiones de la cola
    (puestas por udp_controller tras cada comando MIDI exitoso).

    Reconexión automática con espera de 3 segundos si se cae.
    """
    while not stop_event.is_set():
        try:
            async with websockets.connect(PIPEDAL_WS, ping_interval=None) as ws:
                logging.info("WebSocket conectado a PiPedal")

                await ws.send(json.dumps([{"message": "hello"}]))
                logging.info("WS >> hello")
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(raw)
                    if isinstance(data, list) and len(data) > 0:
                        hdr = data[0]
                        if isinstance(hdr, dict) and hdr.get("message") == "ehlo":
                            state.ws_client_id = data[1] if len(data) > 1 else None
                            state.tuner_subscribed = False
                            state.tuner_sub_handle_notify = None
                            state.tuner_sub_handle_freq = None
                            state.tuner_sub_pending = False
                            state.tuner_activated = False
                            logging.info("WS << ehlo clientId=%s", state.ws_client_id)
                except (asyncio.TimeoutError, json.JSONDecodeError, IndexError):
                    logging.warning("WS no recibió ehlo (procediendo de todas formas)")

                req_id = state.next_reply_id
                state.next_reply_id += 1
                await ws.send(json.dumps([{"message": "getBankIndex", "replyTo": req_id}]))
                req_id = state.next_reply_id
                state.next_reply_id += 1
                await ws.send(json.dumps([{"message": "currentPedalboard", "replyTo": req_id}]))

                while not stop_event.is_set():
                    # Drenar peticiones encoladas por udp_controller
                    while state.ws_request_queue is not None and not state.ws_request_queue.empty():
                        req = state.ws_request_queue.get_nowait()
                        req_id = state.next_reply_id
                        state.next_reply_id += 1
                        if isinstance(req, tuple):
                            header, ws_body = req
                        else:
                            header, ws_body = req, None
                        header["replyTo"] = req_id
                        payload = [header, ws_body] if ws_body is not None else [header]
                        await ws.send(json.dumps(payload))
                        logging.info("WS >> %s", json.dumps(payload))

                    # Esperar mensaje con timeout para no bloquear la cola
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue

                    try:
                        data = json.loads(raw)
                        logging.info("WS << %s", raw)

                        if not isinstance(data, list) or not data:
                            continue

                        header = data[0]
                        if not isinstance(header, dict):
                            continue
                        body = data[1] if len(data) > 1 else None
                        msg = header.get("message", "")
                        is_reply = "reply" in header

                        # PiPedal espera confirmación para todo mensaje con replyTo
                        reply_to = header.get("replyTo")
                        if reply_to is not None:
                            ack = [{"reply": reply_to, "message": msg}, True]
                            await ws.send(json.dumps(ack))
                            logging.info("WS >> (ack) %s", json.dumps(ack))

                        if msg == "onBanksChanged" or (msg == "getBankIndex" and is_reply):
                            handle_banks(body, udp_transport, state)

                        elif msg == "onPresetsChanged":
                            handle_presets(body, udp_transport, state)

                        elif msg == "onPedalboardChanged" or (msg == "currentPedalboard" and is_reply):
                            handle_pedalboard(body, udp_transport, state)

                        elif msg == "monitorPort" and is_reply and isinstance(body, int):
                            state.tuner_sub_handle = body
                            if not state.tuner_subscribed:
                                state.tuner_subscribed = True
                                state.tuner_sub_pending = False
                            logging.info("Tuner: subscribed monitorPort handle=%s", body)

                        elif msg == "onSelectedSnapshotChanged":
                            handle_snapshot(body, udp_transport, state)

                        elif msg == "onMonitorPortOutput":
                            if not isinstance(body, dict):
                                continue
                            handle = body.get("subscriptionHandle")
                            value = body.get("value")
                            logging.info("MonitorPortOutput: handle=%s value=%s", handle, value)
                            # Guardar handle de subscripción
                            if handle is not None and state.tuner_sub_handle is None:
                                state.tuner_sub_handle = handle
                            if not state.tuner_subscribed and state.tuner_sub_handle is not None:
                                state.tuner_subscribed = True
                                state.tuner_sub_pending = False
                            # Procesar solo valores de nota válidos (> 0)
                            if value is not None and value > 0:
                                note_int = int(round(value))
                                cents = int(round((value - note_int) * 100))
                                note_name = NOTE_NAMES[note_int % 12]
                                octave = note_int // 12 - 1
                                t_msg = f"t:{note_name}{octave}{cents:+03d}"
                                logging.info("Tuner data: %s", t_msg)
                                udp_send(udp_transport, t_msg, state)

                        elif msg == "onControlChanged":
                            if isinstance(body, dict):
                                logging.info("ControlChanged: instance=%s symbol=%s value=%s",
                                    body.get("instanceId"), body.get("symbol"), body.get("value"))
                                inst_id = body.get("instanceId")
                                symbol = body.get("symbol")
                                value = body.get("value")
                                if (inst_id == state.tuner_instance_id
                                        and symbol == "MUTE"
                                        and value is not None):
                                    state.mute_state = int(value)
                                    state.mute_state_known = True

                        else:
                            logging.info("WS desconocido: msg=%s body=%s", msg, json.dumps(body))

                    except json.JSONDecodeError:
                        continue

        except websockets.ConnectionClosed:
            logging.warning("WebSocket desconectado, reconectando...")
        except OSError as e:
            logging.warning(f"WebSocket no disponible (PiPedal corriendo?): {e}")
        except Exception as e:
            logging.error(f"WebSocket error: {e}")
        await asyncio.sleep(3)


# =============================================================================
# Controlador UDP — consume la cola y llama a midi_to_GT
# =============================================================================

async def udp_controller(queue, midi_port, udp_transport, state):
    """
    Lee mensajes de la cola UDP (puesta por UDPProtocol) y los traduce
    a MIDI hacia PiPedal. La respuesta se envía de vuelta a la ESP
    usando la misma dirección desde la que llegó el mensaje original.

    Después de cada comando que modifica el estado (todo menos `kl`),
    espera 200ms para que PiPedal procese bindings MIDI, luego encola
    currentPedalboard para reflejar el cambio en la ESP.
    """
    while True:
        msg, addr = await queue.get()
        logging.info(f"UDP << {msg}")
        reply = midi_to_GT(msg, midi_port, state)
        if reply == "__mute_toggle__":
            if state.ws_request_queue is not None and state.tuner_instance_id is not None:
                new_val = 1 - state.mute_state
                state.ws_request_queue.put_nowait((
                    {"message": "setControl"},
                    {"instanceId": state.tuner_instance_id, "symbol": "MUTE", "value": new_val}
                ))
                state.mute_state = new_val
                state.mute_state_known = True
                reply = "ok"
            else:
                reply = "-1"
        if reply:
            udp_transport.sendto(reply.encode("utf-8"), addr)
            if msg != "kl" and state.ws_request_queue is not None:
                await asyncio.sleep(0.2)
                state.ws_request_queue.put_nowait({"message": "currentPedalboard"})


# =============================================================================
# Conexión MIDI — espera a que PiPedal esté listo
# =============================================================================

async def connect_midi():
    """
    Abre un puerto MIDI de salida hacia PiPedal.

    Usa el backend de ALSA (no JACK). Espera hasta 30 segundos a que
    PiPedal haya creado su puerto "PiPedal:in" en el ALSA sequencer.

    El cliente ALSA se registra con nombre "TobiGT" para facilitar
    la identificación (visible con 'aconnect -i' o 'aseqdump -l').
    """
    mido.set_backend(MIDI_BACKEND)
    for attempt in range(30):
        try:
            for name in mido.get_output_names():
                if "PiPedal" in name and "in" in name:
                    port = mido.open_output(name, client_name="TobiGT")
                    logging.info(f"MIDI conectado a {name}")
                    try:
                        subprocess.run(
                            ["aconnect", "TobiGT:0", "PiPedal:in"],
                            check=True, capture_output=True, timeout=5,
                        )
                        logging.info("MIDI: conexión ALSA establecida")
                    except Exception as e:
                        logging.warning(f"MIDI: aconnect falló ({e}) — "
                                        "puede que la conexión ya exista")
                    return port
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("No se encontro puerto 'PiPedal:in' en ALSA sequencer")


# =============================================================================
# Punto de entrada
# =============================================================================

async def main():
    """
    Coordina todas las capas:

    1. Conecta MIDI a PiPedal (con reintento)
    2. Abre servidor UDP para recibir comandos de la ESP
    3. Lanza dos tareas concurrentes:
       - udp_controller:  cola UDP → MIDI → PiPedal
       - ws_loop:         WebSocket ← PiPedal → estado → UDP → ESP

    Permanece ejecutándose hasta SIGINT/SIGTERM.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.info("=== TobiGT / PiPedal bridge ===")

    state = AppState()
    state.ws_request_queue = asyncio.Queue()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: (
            logging.info("Señal de parada recibida"),
            stop_event.set(),
        ))

    midi_port = await connect_midi()
    udp_queue = asyncio.Queue()

    transport, _ = await loop.create_datagram_endpoint(
        lambda: UDPProtocol(udp_queue, state),
        local_addr=(UDP_HOST, UDP_PORT),
    )
    logging.info(f"UDP escuchando en {UDP_HOST}:{UDP_PORT}")

    tasks = [
        asyncio.create_task(udp_controller(udp_queue, midi_port, transport, state)),
        asyncio.create_task(ws_loop(transport, state, stop_event)),
    ]

    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        transport.close()
        midi_port.close()
        logging.info("Terminado")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
