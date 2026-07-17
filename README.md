# TobiGT — MIDI ↔ UDP bridge for PiPedal

Bridge que recibe comandos UDP desde un ESP pedalboard, los traduce a MIDI
para controlar **PiPedal** (guitar amp sim en Raspberry Pi), y reenvía eventos
WebSocket de PiPedal al ESP en tiempo real.

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
  (FD, FI, BANCO, BOOST, PROG)
- Red WiFi (hotspot de la RPi o LAN doméstica)

## Instalación

### 1. Bridge en la Raspberry Pi

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

Comandos de servicio:
```bash
systemctl start animalmidi
systemctl stop animalmidi
systemctl status animalmidi
systemctl restart animalmidi
```

### 2. Firmware ESP

Copiar todo el contenido de `esp-firmware/` al ESP (Thonny, ampy, mip, o FTP).

```
esp-firmware/
├── main.py           # Programa principal
├── tm1637.py         # Driver para displays TM1637
├── conectar.py       # Conexión WiFi (configurar SSID/PSK domésticos)
├── credenciales.py   # IP del server + puerto UDP
└── config.json       # Config persistente (se crea solo en el ESP)
```

En `conectar.py` y `credenciales.py`, ajustar las IPs, SSID y PSK según tu
red local y la IP de la Raspberry Pi.

### 3. MIDI Bindings en PiPedal

Desde la UI web de PiPedal, ir a Settings → MIDI Bindings → System y agregar
los siguientes bindings (ver [PiPedal MIDI
docs](https://rerdavies.github.io/pipedal/midi.html) para más detalles):

| Nota | Tipo   | Acción           |
|------|--------|------------------|
| 60   | System | Toggle Boost     |
| 70   | System | Next Preset      |
| 71   | System | Previous Preset  |
| 72   | System | Next Bank        |
| 73   | System | Shutdown         |
| 74   | System | Reboot           |
| 75   | System | Toggle Hotspot   |

## Uso

### Modo normal

| Botón | Nota | Acción PiPedal |
|-------|------|----------------|
| FD (der) | 76 | Next Snapshot |
| FI (izq) | 77 | Previous Snapshot |
| BANCO (corto) | 70 | Next Preset |
| BANCO (largo) | — | Entra en modo selección de preset |
| BOOST | 60 (toggle) | Boost on/off |
| PROG (corto) | 72 | Next Bank |

En **modo selección de preset** (BANCO largo):

| Botón | Nota | Acción |
|-------|------|--------|
| FD | 70 | Next Preset |
| FI | 71 | Previous Preset |
| BANCO | — | Sale del modo (cancelar) |
| BOOST | — | Sale del modo (confirmar) |

**Display normal:** tmA = preset, tmB = snapshot
**Display modo preset:** tmA = `PrSt`, tmB = preset (se actualiza al navegar)

### Menú PROG

Long-press PROG → menú navegable con **FD/FI**, confirmar con **BANCO**,
cancelar con **BOOST** o cualquier botón.

| Opción | tmA | Acción |
|--------|-----|--------|
| Shutdown | `ShUt` | note=73 → PiPedal: System Shutdown |
| Reboot | `rEbt` | note=74 → PiPedal: System Reboot |
| Hotspot | `Hot` | note=75 → PiPedal: Toggle Hotspot |
| Deep sleep | `SLP` | `machine.deepsleep()` (local ESP) |
| Salir | `ESC` | Sale sin acción |

Al confirmar (excepto ESC): countdown **5→0** en tmB. Cualquier botón cancela.

## MIDI Bindings

Resumen de los bindings que deben configurarse en PiPedal
([docs](https://rerdavies.github.io/pipedal/midi.html)):

| Nota | Tipo      | Acción           | Uso                 |
|------|-----------|------------------|---------------------|
| 60   | System    | Toggle Boost     | BOOST button        |
| 70   | System    | Next Preset      | BANCO button        |
| 72   | System    | Next Bank        | PROG (corto)        |
| 73   | System    | Shutdown         | PROG → ShUt         |
| 74   | System    | Reboot           | PROG → rEbt         |
| 75   | System    | Toggle Hotspot   | PROG → Hot          |
| 76   | System    | Next Snapshot    | FD button           |
| 77   | System    | Previous Snapshot| FI button           |

## Estructura del repositorio

```
tobigt-puente-pipedal/
├── animalMidi.py           # Bridge Python (UDP → MIDI → WebSocket)
├── esp-firmware/
│   ├── main.py             # Firmware principal ESP8266
│   ├── conectar.py         # Conexión WiFi (SSID/PSK a configurar)
│   ├── credenciales.py     # IP del server + puerto UDP
│   └── tm1637.py           # Driver displays TM1637
├── setup.sh                # Script de instalación del bridge
├── update.sh               # Script de actualización
├── deploy.sh               # Despliegue local (no trackeado en git)
├── animalmidi.service      # Systemd unit
├── requirements.txt        # Dependencias Python
├── DEVELOPMENT.md          # Documentación técnica detallada
└── README.md               # Este archivo
```

## TODO

- [ ] Archivo de configuración para MIDI bindings (mapeo notas → acciones,
      independiente de la UI de PiPedal)
- [ ] Esquemático del hardware (conexiones ESP → TM1637 → botones)
- [ ] Reemplazar FTP boot por OTA (microPythonOTA o similar) para actualizar
      firmware sin cable

## Licencia

**CC BY-SA 4.0 — Creative Commons Atribución-CompartirIgual 4.0 Internacional**

© 2025 Sebastián Tobías Castro

Esta obra está bajo licencia
[Creative Commons Atribución-CompartirIgual 4.0 Internacional]
(https://creativecommons.org/licenses/by-sa/4.0/).

Usted es libre de:
- **Compartir** — copiar y redistribuir el material en cualquier medio o formato
- **Adaptar** — remezclar, transformar y construir a partir del material

Bajo los siguientes términos:
- **Atribución** — debe dar crédito adecuado, proporcionar un enlace a la
  licencia e indicar si se realizaron cambios
- **CompartirIgual** — si remezcla, transforma o crea a partir del material,
  debe distribuir sus contribuciones bajo la misma licencia

| Enlace | URL |
|--------|-----|
| Resumen en español | https://creativecommons.org/licenses/by-sa/4.0/deed.es |
| Texto legal completo | https://creativecommons.org/licenses/by-sa/4.0/legalcode.es |

Sin garantías. La licencia podría no dar todos los permisos necesarios para el
uso previsto (ej. derechos de publicidad, privacidad o morales). Ver el
[texto legal completo](https://creativecommons.org/licenses/by-sa/4.0/legalcode.es)
para más detalles.

## Créditos

Parte de la reimplementación actual de TobiGT fue asistida por
[OpenCode](https://opencode.ai) y el modelo DeepSeek V4.

© 2025 Sebastián Tobías Castro
