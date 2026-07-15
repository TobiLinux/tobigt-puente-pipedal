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

FD = Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
FI= Pin(12, machine.Pin.IN, machine.Pin.PULL_UP)
BANCO = Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)
BOOST = Pin(15, machine.Pin.IN, machine.Pin.PULL_UP)
PROG = Pin(16, machine.Pin.IN)
tmB= tm1637.TM1637(clk=Pin(2), dio=Pin(0))
tmA= tm1637.TM1637(clk=Pin(4), dio=Pin(5))

inter = False
pin = 0
red = ''
modo = 'normal'
keeplive_time = 60000
MI_PUERTO = 4097
sock_global = None
swtime = 2000
boost_flag = False
contador_klive = time.ticks_ms()
ultimo_texto = ['----', '----']
opciones_prog = ["ShUt", "rEbt", "Hot", "SLP", "ESC"]
opcion_actual = 0
last_irq_ms = 0
DEBOUNCE_MS = 200

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
    s = str(s)
    return ''.join(_TM1637_REPLACE.get(c, c) for c in s)

def btn_press(pin):
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
  tmA.write([0, 0, 0, 0])
  tmB.write([0, 0, 0, 0])

def cargar_tms(t=None):
  if t is None:
    t = ultimo_texto
  tmA.show(sanitize_tm1637(t[0]))
  tmB.show(sanitize_tm1637(t[1]))

def bienvenida():
  limpiartms()
  tmA.scroll('Bienvenido tobi', 50)
  tmA.brightness(2)
  tmB.brightness(2)
  limpiartms()

def cargar_config(key, value):
  global config
  print(config)
  config['cliente'][key] = value
  n_config = json.dumps(config)
  f = open('config.json', 'w')
  f.write(n_config)
  f.close()

def seleccion_RED():
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
      name = sanitize_tm1637(res[2:])
      if modo == 'normal':
        tmA.scroll(name, 60)
        time.sleep_ms(200)
      ultimo_texto[0] = name
      if modo == 'normal': cargar_tms()
      server_updated = True
    elif res[0:2] == 'b:' or res[0:2] == 'p:':
      name = sanitize_tm1637(res[2:])
      ultimo_texto[1] = name
      if modo == 'normal': cargar_tms()
      server_updated = True
    elif res[0:2] == 's:':
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
  global contador_klive
  if time.ticks_diff(time.ticks_ms(), contador_klive) > keeplive_time:
    qlres = enviarudp('kl')
    control_UDP(qlres)
    contador_klive = time.ticks_ms()
    cargar_tms()

def poll_async_udp():
  try:
    data, server = sock_global.recvfrom(256)
    msg = data.decode('utf-8')
    print('async:', msg)
    control_UDP([msg])
  except OSError:
    pass

def prog_siguiente():
  global opcion_actual
  opcion_actual = (opcion_actual + 1) % len(opciones_prog)
  print('prog: FD -> opcion', opcion_actual, opciones_prog[opcion_actual])
  tmA.show(opciones_prog[opcion_actual])

def prog_anterior():
  global opcion_actual
  opcion_actual = (opcion_actual - 1) % len(opciones_prog)
  print('prog: FI -> opcion', opcion_actual, opciones_prog[opcion_actual])
  tmA.show(opciones_prog[opcion_actual])

def prog_executar(accion):
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
  if modo=='normal':
    print('normal: BANCO -> next bank')
    control_UDP(enviarudp("note_on channel=0 note=72"))
    time.sleep(0.1)
  elif modo=='prog':
    print('prog: BANCO -> confirmar')
    prog_executar(opciones_prog[opcion_actual])
    time.sleep(0.1)

def F_der():
  if modo=='normal':
    control_UDP(enviarudp("note_on channel=0 note=70"))
    time.sleep(0.1)
  elif modo=='prog':
    prog_siguiente()

def F_izq():
  if modo=='normal':
    control_UDP(enviarudp("note_on channel=0 note=71"))
    time.sleep(0.1)
  elif modo=='prog':
    prog_anterior()

def F_boost():
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
  switcher = {
        'Pin(12)': F_izq,
        'Pin(15)': F_boost,
        'Pin(14)': F_der,
        'Pin(13)': F_banco,
    }
  func = switcher.get(str(i), lambda: None)
  return func()

def boton_PROG():
  global modo, opcion_actual
  if modo == 'prog':
    return
  t = time.ticks_ms()
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

bienvenida()
seleccion_RED()

sock_global = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_global.setblocking(False)
sock_global.bind(('0.0.0.0', MI_PUERTO))

print('iniciando programa en modo ', modo)

while True:
  boton_PROG()
  keepAlive()
  poll_async_udp()
  if inter:
    print('IRQ: pin=%s modo=%s' % (pin_i, modo))
    boton(pin_i)
    inter = False
  time.sleep_ms(50)
