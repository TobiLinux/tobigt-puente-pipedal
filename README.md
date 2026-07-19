# TobiGT — MIDI ↔ UDP bridge for PiPedal

Bridge que recibe comandos UDP desde un ESP pedalboard, los traduce a MIDI
para controlar **PiPedal** (guitar amp sim en Raspberry Pi), y reenvía eventos
WebSocket de PiPedal al ESP en tiempo real. Incluye afinador cromático
(TooB Tuner → ESP) y control de mute por WebSocket.

```
┌─────────┐  UDP   ┌──────────┐  MIDI   ┌──────────┐
│  ESP    │───────→│  bridge  │───────→│  PiPedal │
│ 8266/32 │←───────│ (Python) │←───────│ (RPi)    │
└─────────┘  UDP   └──────────┘  WS     └──────────┘
   (stateless)       async              amp sim
```

## Requisitos

- Raspberry Pi con [PiPedal](https://rerdavies.github.io/pipedal/) instalado y
  MIDI IN habilitado
- **ESP8266** (hardware actual: Wemos D1 mini) con 2 displays TM1637 y 5 botones
  (FD, FI, BANCO, BOOST, PROG), más el plugin **TooB Tuner** agregado al
  pedalboard activo
- Red WiFi (hotspot de la RPi o LAN doméstica)

## Instalación — Bridge (Raspberry Pi)

```bash
git clone <url-del-repo>
cd tobigt-puente-pipedal
bash setup.sh
```

Ejecutar **como usuario normal** (no con `sudo`). El script usa `sudo`
internamente donde hace falta (apt, systemd), pero si se corre todo con `sudo`
el venv se crea en `/root/` y el servicio falla al conectar el secuenciador
ALSA con PiPedal.

El script:
- Crea un venv en `~/.animalmidi-pipedal/` con `--system-site-packages`
- Instala dependencias (`mido`, `python3-rtmidi`, `python3-websockets`)
- Instala y habilita el servicio systemd `animalmidi.service`
  (`After=pipedald.service`)
- Crea el archivo de configuración `/etc/animalmidi/env` (todas las variables
  son opcionales, ver defaults en `animalMidi.py:43-54`)

Comandos:
```bash
sudo systemctl start|stop|status|restart animalmidi
```

## Instalación — Firmware ESP

### Opción A: deploy script (recomendado)

Con `ampy` instalado y el ESP conectado por USB:

```bash
cd tobigt-puente-pipedal
./deploy-esp.sh          # usa /dev/ttyUSB1 por defecto
TOBIGT_ESP_PORT=/dev/ttyUSB0 ./deploy-esp.sh   # puerto custom
```

El script borra los archivos `.mpy` compilados (usa los `.py` fuente),
sube todos los `.py` files + `config.json`, y pide resetear el ESP.

### Opción B: manual

Copiar `esp-firmware/` al ESP (Thonny, ampy, mip, etc.). Ajustar
`conectar.py` con SSID/PSK de tu red y `credenciales.py` con la IP de la RPi.

El split del firmware:
- `main.py` — entry point (solo `import main_code`)
- `main_code.py` — lógica completa (botones, modos, UDP, displays)
- `tm1637.py` — driver para displays TM1637
- `conectar.py` — conexión WiFi (configurar SSID/PSK)
- `credenciales.py` — IP del server + puerto UDP
- `config.json` — configuración opcional

> **`.mpy` vs `.py`:** El ESP carga primero `.mpy` si existe. El deploy script
> borra los `.mpy` para que se use el `.py` fuente, facilitando edición.
> Si querés compilar: `mpy-cross main_code.py` desde tu PC.

## MIDI Bindings en PiPedal

Desde Settings → MIDI Bindings → System, agregar:

| Nota | Tipo   | Acción           |
|------|--------|------------------|
| 60   | System | Toggle Boost     |
| 70   | System | Next Preset      |
| 71   | System | Previous Preset  |
| 72   | System | Next Bank        |
| 73   | System | Shutdown         |
| 74   | System | Reboot           |
| 75   | System | Toggle Hotspot   |
| 76   | System | Next Snapshot    |
| 77   | System | Previous Snapshot|

> **Nota 78 (MUTE)** no usa MIDI binding (ver sección MUTE más abajo).

## Botones y modos

La pedalera tiene 4 modos de operación:

### Modo normal

| Botón                | Nota  | Acción PiPedal          | Display           |
|----------------------|-------|-------------------------|-------------------|
| FD                   | 76    | Next Snapshot           | —                 |
| FI                   | 77    | Previous Snapshot       | —                 |
| BANCO (corto)        | 70    | Next Preset             | —                 |
| BANCO (largo)        | —     | Entra modo preset       | tmA=`PrSt`        |
| BOOST (corto)        | 60    | Toggle Boost on/off     | `b**t`/normal     |
| BOOST (largo)        | —     | Entra modo tuner        | tmA=nota, tmB=cts |
| PROG (corto)         | 72    | Next Bank               | —                 |
| PROG (largo)         | —     | Entra menú PROG         | tmA=`prog`        |

En modo normal, tmA = preset, tmB = snapshot.

### Modo preset (BANCO largo)

Navegar presets con FD/FI, salir con BANCO o BOOST:

| Botón | Nota  | Acción           |
|-------|-------|------------------|
| FD    | 70    | Next Preset      |
| FI    | 71    | Previous Preset  |
| BANCO | —     | Sale del modo    |
| BOOST | —     | Sale del modo    |

tmA = `PrSt`, tmB = preset actual (se actualiza al navegar).

### Modo tuner (BOOST largo)

Entra al afinador: envía nota 78 (MUTE) para silenciar la salida, y recibe
datos de frecuencia del TooB Tuner vía WebSocket → UDP.

| Display | Muestra       | Ejemplo         |
|---------|---------------|-----------------|
| tmA     | Nota + 8va    | `A1  `, `F°2 ` |
| tmB     | Cents         | ` 04 `, `-03 ` |

Cualquier botón (BANCO, FD, FI, BOOST) sale del modo tuner y envía nota 78
(UNMUTE). Timeout automático a los 10 segundos de inactividad.

El dato `t:` llega desde el bridge (que lo obtiene del monitorPort del TooB
Tuner via WebSocket). Incluye redondeo a semitono más cercano.

### Menú PROG (PROG largo)

Navegar con FD/FI, confirmar con BANCO, cancelar con BOOST o cualquier botón.

| Opción     | tmA   | Acción                           |
|------------|-------|----------------------------------|
| Shutdown   | ShUt  | note=73 → PiPedal: System Shutdown|
| Reboot     | rEbt  | note=74 → PiPedal: System Reboot |
| Hotspot    | Hot   | note=75 → PiPedal: Toggle Hotspot|
| Deep sleep | SLP   | `machine.deepsleep()` (local ESP)|
| Salir      | ESC   | Sale sin acción                  |

Al confirmar (excepto ESC): countdown **5→0** en tmB. Cualquier botón cancela.

## MUTE (workaround)

Los MIDI bindings de plugin en PiPedal tienen un bug: funcionan solo UNA vez
por carga de preset y luego se traban. Por eso, el MUTE (nota 78) **no se envía
por MIDI**. El bridge lo intercepta y lo convierte en un mensaje WebSocket
`setControl` con `symbol:"MUTE"` (no `key:"MUTE"`, que PiPedal ignora).

Esto aplica tanto al entrar (mute ON) como al salir del modo tuner (mute OFF).

## Configuración del bridge

Runtime config vía variables de entorno (definir en `/etc/animalmidi/env`):

| Variable              | Default                         |
|-----------------------|---------------------------------|
| `TOBIGT_UDP_HOST`     | `0.0.0.0`                       |
| `TOBIGT_UDP_PORT`     | `20001`                         |
| `TOBIGT_ESP_HOST`     | `192.168.60.195`                |
| `TOBIGT_ESP_PORT`     | `4097`                          |
| `TOBIGT_PIPEDAL_WS`   | `ws://127.0.0.1:80/pipedal`     |
| `TOBIGT_PIPEDAL_MIDI` | `PiPedal:in`                    |
| `TOBIGT_MIDI_BACKEND` | `mido.backends.rtmidi/LINUX_ALSA`|

## Deploy

**Bridge (Pi):**
```bash
cd tobigt-puente-pipedal && ./deploy.sh
```
Rsync + setup.sh (idempotente). Reiniciar: `ssh tobi@192.168.60.1 "sudo systemctl restart animalmidi"`

**ESP firmware (local):**
```bash
cd tobigt-puente-pipedal && ./deploy-esp.sh
```
Requiere `ampy`. Borra `.mpy`, sube `.py` + `config.json`. Resetear ESP después.

Logs del bridge: `ssh tobi@192.168.60.1 "sudo journalctl -u animalmidi --no-pager -n 50"`

## Estructura del repositorio

```
tobigt-puente-pipedal/
├── animalMidi.py           # Bridge Python (UDP → MIDI → WS)
├── esp-firmware/
│   ├── main.py             # Entry point ESP (import main_code)
│   ├── main_code.py        # Lógica completa del firmware ESP
│   ├── tm1637.py           # Driver displays TM1637
│   ├── conectar.py         # Conexión WiFi (configurar SSID/PSK)
│   ├── credenciales.py     # IP del server + puerto UDP
│   └── config.json         # Config opcional
├── setup.sh                # Instalación del bridge en la Pi
├── update.sh               # Actualización del bridge
├── deploy.sh               # Deploy bridge → Pi (no trackeado en git)
├── deploy-esp.sh           # Deploy firmware → ESP via ampy
├── animalmidi.service      # Systemd unit
├── requirements.txt        # Dependencias Python (mido)
├── DEVELOPMENT.md          # Documentación técnica detallada
├── AGENTS.md               # Contexto para asistentes AI
└── README.md               # Este archivo
```

## Licencia

**CC BY-SA 4.0 — Creative Commons Atribución-CompartirIgual 4.0 Internacional**

© 2025 Sebastián Tobías Castro

## Créditos

Parte de la reimplementación actual de TobiGT fue asistida por
[OpenCode](https://opencode.ai) y el modelo DeepSeek V4.
