"""FootSwitch con Wemos D1 mini esp8266
FD --> D5 > 14
FI --> D6 > 12
BANCO --> D7 > 13
BOOST --> D8 > 15
PROG --> D0 > 16
tm1637A
--> clk=2
--> dio=0
tm1637A
--> clk=4
--> dio=5
"""
# Boot: check config.json for FTP mode flag
try:
  f = open('config.json')
  import json, conectar
  config = json.loads(f.read())
  f.close()
  print(config)
  if config.get('cliente').get('ftp'):
    config['cliente']['ftp'] = 0
    f = open('config.json', 'w')
    f.write(json.dumps(config))
    f.close()
    conectar.conectar_animal(0)
    import ftp
    import machine
    machine.reset()
except Exception as a:
      print('error:   ', a)

from machine import Pin
import time, network, socket, tm1637, credenciales

# Button pin definitions (pulled up, falling edge = press)
FD = Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
FI= Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)
BANCO = Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)
BOOST = Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)
PROG = Pin(16, machine.Pin.IN)
# TM1637 display modules: tmA = preset, tmB = snapshot
tmB= tm1637.TM1637(clk=Pin(2), dio=Pin(0))
tmA= tm1637.TM1637(clk=Pin(4), dio=Pin(5))

# IRQ flag and pin storage (set by btn_press, consumed in main loop)
inter = False
pin = 0
red = ''
# Operating mode: 'normal' or 'prog'
modo = 'normal'
keeplive_time = 60000
# ESP UDP listen port (bridge sends replies here)
MI_PUERTO = 4097
sock_global = None
# Long-press threshold for PROG button (ms)
swtime = 2000
boost_flag = False
contador_klive = time.ticks_ms()
# Display buffer: [preset_name, snapshot_name]
ultimo_texto = ['----', '----']
# PROG menu items (navigated with FD/FI, confirmed with BANCO)
opciones_prog = ["ShUt", "rEbt", "Hot", "SLP", "ESC"]
opcion_actual = 0
# Debounce timestamps for IRQ buttons and PROG polling
last_irq_ms = 0
last_prog_ms = 0
DEBOUNCE_MS = 200

# Characters not displayable on TM1637 mapped to safe alternatives
_TM1637_REPLACE = {
    '(': ' ', ')': ' ', '[': ' ', ']': ' ',
    '{': ' ', '}': ' ', '<': ' ', '>': ' ',
    '/': ' ', '\\': ' ', '"': ' ', "'": ' ',
    '`': ' ', '!': ' ', '@': 'a', '#': ' ',
    '$': 'S', '%': ' ', '^': ' ', '&': ' ',
    '*': ' ', '+': ' ', '=': ' ', '?': ' ',
    ',': ' ', '.': ' ', ':': ' ', ';': ' ',
    '~': ' ',
}

def sanitize_tm1637(s):
  """Replace unsupported TM1637 chars with safe alternatives."""
  s = str(s)
  return ''.join(_TM1637_REPLACE.get(c, c) for c in s)

def btn_press(pin):
  """IRQ handler for FD/FI/BANCO/BOOST — sets inter flag with debounce."""
  global inter, last_irq_ms, pin_i
  now = time.ticks_ms()
  if time.ticks_diff(now, last_irq_ms) < DEBOUNCE_MS:
    return
  last_irq_ms = now
  inter = True
  pin_i = pin

BANCO.irq(trigger=Pin.IRQ_FALLING, handler=btn_press)
FD.irq(trigger=Pin.IRQ_FALLING, handler=btn_press)
FI.irq(trigger=Pin.IRQ_FALLING, handler=btn_press)
BOOST.irq(trigger=Pin.IRQ_FALLING, handler=btn_press)

def limpiartms():
  """Turn off all segments on both displays."""
  tmA.write([0, 0, 0, 0])
  tmB.write([0, 0, 0, 0])

def cargar_tms(t=None):
  """Update both displays: tmA = preset, tmB = snapshot."""
  if t is None:
    t = ultimo_texto
  tmA.show(sanitize_tm1637(t[0]))
  tmB.show(sanitize_tm1637(t[1]))

def bienvenida():
  """Scroll welcome message on startup."""
  limpiartms()
  tmA.scroll('Bienvenido tobi', 50)
  tmA.brightness(2)
  tmB.brightness(2)
  limpiartms()

def cargar_config(key, value):
  """Persist a config key/value pair to config.json on the ESP."""
  global config
  print(config)
  config['cliente'][key] = value
  n_config = json.dumps(config)
  f = open('config.json', 'w')
  f.write(n_config)
  f.close()

def seleccion_RED():
  """Choose network at startup: BOOST pressed = home WiFi, else = PiPedal AP."""
  global red
  limpiartms()
  if BOOST.value():
    tmA.show('c-Wi')
    print(conectar.conectar_animal(0))
    tmA.show('casa')
    red='casa'
  else:
    tmB.show('c-ap')
    print('bajando AP')
    conectar.bajar_AP()
    print(conectar.conectar_animal(1))
    tmB.show('ap--')
    time.sleep(1)
    red='anim'

def enviarudp(a):
  """Send a UDP command to the bridge and collect replies (up to 1s wait)."""
  global sock_global
  responses = []
  try:
    print('sending "%s"' % a, credenciales.IP_SERVER_AP, credenciales.PUERTO)
    sock_global.sendto(a, (credenciales.IP_SERVER_AP, credenciales.PUERTO))
    deadline = time.ticks_ms() + 1000
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
      try:
        data, server = sock_global.recvfrom(256)
        msg = data.decode('utf-8')
        print('received "%s"' % msg)
        responses.append(msg)
      except OSError:
        pass
      time.sleep_ms(10)
  except Exception as e:
    print('socket error:', e)
    return ['err1']
  if not responses:
    return ['err2']
  return responses

def control_UDP(responses):
  """Parse UDP replies: update display for preset (b:/p:) and snapshot (s:).
  Bank changes (k:) are received but not shown on screen.
  In PROG mode, display updates are suppressed."""
  result = 'ok'
  server_updated = False
  for res in responses:
    if res == "err1":
      if modo == 'normal': cargar_tms(['err-', 'sock'])
      result = 'err1'
    elif res == "err2":
      if modo == 'normal': cargar_tms(['serv', 'mal-'])
      result = 'err2'
    elif res == "klok":
      if modo == 'normal':
        tmA.show('live', True)
        tmB.show('--ok', True)
        time.sleep(0.1)
        limpiartms()
    elif res[0:5] == 'boost':
      result = res
      if modo == 'normal':
        if res == 'boost+':
          cargar_tms(['b**t', '--on'])
        else:
          cargar_tms()
    elif res == "ok":
      result = "ok"
      server_updated = True
    elif res[0:2] == 'k:':
      # Bank changed — no display change (tmA = preset, tmB = snapshot)
      server_updated = True
    elif res[0:2] == 'b:' or res[0:2] == 'p:':
      name = sanitize_tm1637(res[2:])
      ultimo_texto[0] = name
      if modo == 'normal': cargar_tms()
      server_updated = True
    elif res[0:2] == 's:':
      name = sanitize_tm1637(res[2:])
      ultimo_texto[1] = name
      if modo == 'normal': cargar_tms()
      server_updated = True
    else:
      try:
        if modo == 'normal': cargar_tms(['err-','err-'])
        result = '-1'
      except Exception as e:
        print('error:   ', e)
        if modo == 'normal': cargar_tms(['err-','err-'])
        time.sleep(0.5)
        result = '-1'
  return result

def keepAlive():
  """Send keepalive every keeplive_time ms and refresh display with reply."""
  global contador_klive
  if time.ticks_diff(time.ticks_ms(), contador_klive) > keeplive_time:
    qlres = enviarudp('kl')
    control_UDP(qlres)
    contador_klive = time.ticks_ms()
    cargar_tms()

def poll_async_udp():
  """Check for unsolicited UDP messages (async events from bridge)."""
  try:
    data, server = sock_global.recvfrom(256)
    msg = data.decode('utf-8')
    print('async:', msg)
    control_UDP([msg])
  except OSError:
    pass

def prog_siguiente():
  """Move to next PROG menu option (called from FD in prog mode)."""
  global opcion_actual
  opcion_actual = (opcion_actual + 1) % len(opciones_prog)
  print('prog: FD -> opcion', opcion_actual, opciones_prog[opcion_actual])
  tmA.show(opciones_prog[opcion_actual])

def prog_anterior():
  """Move to previous PROG menu option (called from FI in prog mode)."""
  global opcion_actual
  opcion_actual = (opcion_actual - 1) % len(opciones_prog)
  print('prog: FI -> opcion', opcion_actual, opciones_prog[opcion_actual])
  tmA.show(opciones_prog[opcion_actual])

def prog_executar(accion):
  """Execute the selected PROG action after countdown.
  Countdown 5→0 on tmB; any button press cancels (including PROG)."""
  global modo, inter
  inter = False
  print('prog: BANCO confirma', accion)
  if accion == "ESC":
    print('prog: ESC -> salir')
    modo = 'normal'
    cargar_tms()
    return
  for i in range(5, 0, -1):
    tmA.show(accion)
    tmB.show(" " + str(i))
    print('countdown:', i)
    for _ in range(10):
      time.sleep_ms(100)
      if inter or not PROG.value():
        print('countdown CANCELADO por interrupcion')
        modo = 'normal'
        inter = False
        cargar_tms()
        return
  modo = 'normal'
  limpiartms()
  print('ejecutando:', accion)
  if accion == "SLP":
    machine.deepsleep()
  elif accion == "ShUt":
    enviarudp("note_on channel=0 note=73")
  elif accion == "rEbt":
    enviarudp("note_on channel=0 note=74")
  elif accion == "Hot":
    enviarudp("note_on channel=0 note=75")

def F_banco():
  """BANCO button: next preset (normal) or confirm PROG action."""
  if modo=='normal':
    print('normal: BANCO -> next preset')
    control_UDP(enviarudp("note_on channel=0 note=70"))
    time.sleep(0.1)
  elif modo=='prog':
    print('prog: BANCO -> confirmar')
    prog_executar(opciones_prog[opcion_actual])
    time.sleep(0.1)

def F_der():
  """FD button: next snapshot (normal) or next PROG menu option."""
  if modo=='normal':
    print('normal: FD -> next snapshot')
    control_UDP(enviarudp("note_on channel=0 note=76"))
    time.sleep(0.1)
  elif modo=='prog':
    prog_siguiente()

def F_izq():
  """FI button: previous snapshot (normal) or previous PROG menu option."""
  if modo=='normal':
    print('normal: FI -> prev snapshot')
    control_UDP(enviarudp("note_on channel=0 note=77"))
    time.sleep(0.1)
  elif modo=='prog':
    prog_anterior()

def F_boost():
  """BOOST button: toggle boost (normal) or exit PROG mode."""
  global modo
  if modo=='normal':
    control_UDP(enviarudp('boost'))
    time.sleep(0.1)
  elif modo=='prog':
    print('prog: BOOST -> salir')
    modo = 'normal'
    cargar_tms()
    time.sleep(0.1)

def boton(i):
  """Dispatch IRQ pin to the corresponding button handler."""
  switcher = {
        'Pin(12)': F_izq,
        'Pin(15)': F_boost,
        'Pin(14)': F_der,
        'Pin(13)': F_banco,
    }
  func = switcher.get(str(i), lambda: None)
  return func()

def boton_PROG():
  """PROG button handler: short press = next bank, long press = enter PROG menu."""
  global modo, opcion_actual, last_prog_ms
  if modo == 'prog':
    return
  if not PROG.value():
    t = time.ticks_ms()
    if time.ticks_diff(t, last_prog_ms) < DEBOUNCE_MS:
      return
    while not PROG.value():
      if time.ticks_diff(time.ticks_ms(), t) > swtime:
        print('entrando a modo PROG')
        modo = 'prog'
        opcion_actual = 0
        limpiartms()
        tmA.show('prog')
        time.sleep(2)
        tmA.show(opciones_prog[opcion_actual])
        print('prog: opcion inicial', opcion_actual, opciones_prog[opcion_actual])
        return
      time.sleep_ms(5)
    time.sleep_ms(DEBOUNCE_MS)
    if PROG.value():
      last_prog_ms = t
      print('PROG short press -> next bank')
      control_UDP(enviarudp("note_on channel=0 note=72"))

bienvenida()
seleccion_RED()

# Persistent non-blocking UDP socket for all communication
sock_global = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_global.setblocking(False)
sock_global.bind(('0.0.0.0', MI_PUERTO))

print('iniciando programa en modo ', modo)

# Main loop: poll PROG, keepalive, async UDP, and IRQ-driven button dispatch
while True:
  boton_PROG()
  keepAlive()
  poll_async_udp()
  if inter:
    print('IRQ: pin=%s modo=%s' % (pin_i, modo))
    boton(pin_i)
    inter = False
  time.sleep_ms(50)
