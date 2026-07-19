import machine
from machine import Pin
import time, socket, tm1637, credenciales, conectar

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
btime = 600
TUNER_TIMEOUT = 10000
boost_flag = False
contador_klive = time.ticks_ms()
tuner_time = 0
tuner_str = ''
ultimo_texto = ['----', '----']
opciones_prog = ["ShUt", "rEbt", "Hot", "SLP", "ESC"]
opcion_actual = 0
last_irq_ms = 0
last_prog_ms = 0
DEBOUNCE_MS = 200

def sanitize_tm1637(s):
  s = str(s)
  out = ''
  for c in s:
    o = ord(c)
    if o == 64: out += 'a'
    elif o == 36: out += 'S'
    elif o in (40,41,91,93,123,125,60,62): out += ' '
    elif o in (33,34,35,37,38,39,42,43,44,45,46,47,58,59,61,63,92,94,96,126): out += ' '
    else: out += c
  return out

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
  if modo == 'tuner':
    return
  if modo == 'preset':
    tmB.show(sanitize_tm1637(t[0]))
    return
  tmA.show(sanitize_tm1637(t[0]))
  tmB.show(sanitize_tm1637(t[1]))

def bienvenida():
  limpiartms()
  tmA.scroll('Bienvenido tobi', 50)
  tmA.brightness(2)
  tmB.brightness(2)
  limpiartms()

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
    deadline = time.ticks_ms() + 100
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
      try:
        data, server = sock_global.recvfrom(256)
        msg = data.decode('utf-8')
        print('received "%s"' % msg)
        responses.append(msg)
        break
      except OSError:
        pass
      time.sleep_ms(5)
  except Exception as e:
    print('socket error:', e)
    return ['err1']
  if not responses:
    return ['err2']
  return responses

def control_UDP(responses):
  global modo, tuner_time
  result = 'ok'
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
        cargar_tms()
    elif res[0:5] == 'boost':
      result = res
      if modo == 'normal':
        if res == 'boost+':
          cargar_tms(['b**t', '--on'])
        else:
          cargar_tms()
    elif res == "ok":
      result = "ok"
    elif res[0:2] == 'k:':
      pass
    elif res[0:2] == 'b:' or res[0:2] == 'p:':
      name = sanitize_tm1637(res[2:])
      ultimo_texto[0] = name
      if modo != 'prog': cargar_tms()
    elif res[0:2] == 's:':
      name = sanitize_tm1637(res[2:])
      ultimo_texto[1] = name
      if modo == 'normal': cargar_tms()
    elif res[0:2] == 't:':
      if modo != 'tuner':
        return 'ok'
      payload = res[2:]
      if payload == 'OFF':
        modo = 'normal'
        cargar_tms()
        return 'ok'
      tuner_time = time.ticks_ms()
      if payload[1] == '#':
        letter = payload[0]
        octave = payload[2]
        sign = payload[3]
        cents = payload[4:6]
        tmA.show(letter + '*' + octave + ' ')
      else:
        letter = payload[0]
        octave = payload[1]
        sign = payload[2]
        cents = payload[3:5]
        tmA.show(letter + octave + '  ')
      if sign == '+':
        tmB.show(' ' + cents + ' ')
      else:
        tmB.show('-' + cents + ' ')
      return 'ok'
    else:
      try:
        if modo == 'normal': cargar_tms(['err-','err-'])
        result = '-1'
      except:
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
  tmA.show(opciones_prog[opcion_actual])

def prog_anterior():
  global opcion_actual
  opcion_actual = (opcion_actual - 1) % len(opciones_prog)
  tmA.show(opciones_prog[opcion_actual])

def prog_executar(accion):
  global modo, inter
  inter = False
  if accion == "ESC":
    modo = 'normal'
    cargar_tms()
    return
  for i in range(5, 0, -1):
    tmA.show(accion)
    tmB.show(" " + str(i))
    for _ in range(10):
      time.sleep_ms(100)
      if inter or not PROG.value():
        modo = 'normal'
        inter = False
        cargar_tms()
        return
  modo = 'normal'
  limpiartms()
  if accion == "SLP":
    machine.deepsleep()
  elif accion == "ShUt":
    enviarudp("note_on channel=0 note=73")
  elif accion == "rEbt":
    enviarudp("note_on channel=0 note=74")
  elif accion == "Hot":
    enviarudp("note_on channel=0 note=75")

def F_banco():
  global modo
  if modo == 'tuner':
    print('>> modo tuner OFF (UNMUTE) FI')
    modo = 'normal'
    enviarudp("note_on channel=0 note=78")
    cargar_tms()
    return
  if modo == 'preset':
    print('preset: BANCO -> salir')
    modo = 'normal'
    cargar_tms()
    return
  if modo == 'normal':
    if not BANCO.value():
      t = time.ticks_ms()
      while not BANCO.value():
        if time.ticks_diff(time.ticks_ms(), t) > swtime:
          modo = 'preset'
          tmA.show('PrSt')
          time.sleep(0.5)
          cargar_tms()
          return
        time.sleep_ms(10)
    control_UDP(enviarudp("note_on channel=0 note=70"))
    time.sleep(0.02)
  elif modo=='prog':
    prog_executar(opciones_prog[opcion_actual])
    time.sleep(0.02)

def F_der():
  global modo
  if modo == 'tuner':
    modo = 'normal'
    enviarudp("note_on channel=0 note=78")
    cargar_tms()
    return
  if modo == 'preset':
    control_UDP(enviarudp("note_on channel=0 note=70"))
    time.sleep(0.02)
  elif modo == 'normal':
    control_UDP(enviarudp("note_on channel=0 note=76"))
    time.sleep(0.02)
  elif modo == 'prog':
    prog_siguiente()

def F_izq():
  global modo
  if modo == 'tuner':
    modo = 'normal'
    enviarudp("note_on channel=0 note=78")
    cargar_tms()
    return
  if modo == 'preset':
    control_UDP(enviarudp("note_on channel=0 note=71"))
    time.sleep(0.02)
  elif modo == 'normal':
    control_UDP(enviarudp("note_on channel=0 note=77"))
    time.sleep(0.02)
  elif modo == 'prog':
    prog_anterior()

def F_boost():
  global modo, inter, tuner_time
  if modo == 'tuner':
    print('>> modo tuner OFF (UNMUTE) BOOST')
    modo = 'normal'
    inter = False
    enviarudp("note_on channel=0 note=78")
    cargar_tms()
    return
  if modo == 'preset':
    modo = 'normal'
    cargar_tms()
    time.sleep(0.02)
    return
  if modo == 'prog':
    modo = 'normal'
    cargar_tms()
    time.sleep(0.02)
    return
  if not BOOST.value():
    t = time.ticks_ms()
    while not BOOST.value():
      if time.ticks_diff(time.ticks_ms(), t) > btime:
        inter = False
        modo = 'tuner'
        tuner_time = time.ticks_ms()
        tmA.show('tunE')
        tmB.show('----')
        print('>> modo tuner ON (MUTE)')
        enviarudp("note_on channel=0 note=78")
        time.sleep(0.02)
        return
      time.sleep_ms(10)
  # Button released: short press
  control_UDP(enviarudp('boost'))
  time.sleep(0.02)

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
  global modo, opcion_actual, last_prog_ms
  if modo == 'prog' or modo == 'preset' or modo == 'tuner':
    return
  if not PROG.value():
    t = time.ticks_ms()
    if time.ticks_diff(t, last_prog_ms) < DEBOUNCE_MS:
      return
    while not PROG.value():
      if time.ticks_diff(time.ticks_ms(), t) > swtime:
        modo = 'prog'
        opcion_actual = 0
        limpiartms()
        tmA.show('prog')
        time.sleep(2)
        tmA.show(opciones_prog[opcion_actual])
        return
      time.sleep_ms(5)
    time.sleep_ms(DEBOUNCE_MS)
    if PROG.value():
      last_prog_ms = t
      control_UDP(enviarudp("note_on channel=0 note=72"))

bienvenida()
seleccion_RED()

sock_global = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_global.setblocking(False)
sock_global.bind(('0.0.0.0', MI_PUERTO))

while True:
  boton_PROG()
  keepAlive()
  poll_async_udp()
  if modo == 'tuner' and tuner_time > 0 and time.ticks_diff(time.ticks_ms(), tuner_time) > TUNER_TIMEOUT:
    print('>> modo tuner OFF (TIMEOUT)')
    modo = 'normal'
    enviarudp("note_on channel=0 note=78")
    cargar_tms()
  if inter:
    boton(pin_i)
    inter = False
  time.sleep_ms(20)
