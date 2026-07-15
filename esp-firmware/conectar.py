import network, time

def conectar_animal(red):
	"""Conecta el ESP como cliente WiFi.
	red=1: se conecta al hotspot de la Raspberry Pi (PiPedal AP).
	red=0: se conecta a la red WiFi doméstica.
	"""
	wlan = network.WLAN(network.STA_IF)
	wlan.active(True)
	wlan.disconnect()
	if red:
		print('conectando a PiPedal AP')
		# SSID y PSK del hotspot que genera la Raspberry con PiPedal.
		# Cambiar si configuraste otro nombre/contraseña en PiPedal.
		wlan.connect('pipedal', 'animalito')
	else:
		print('conectando a WiFi de casa')
		# --- REEMPLAZAR con tus credenciales de red doméstica ---
		wlan.connect('MI_WIFI_SSID', 'MI_WIFI_PSK')
		# ---------------------------------------------------------
	while not wlan.isconnected():
		pass
	return(wlan.ifconfig())


def accespoint(flag=False):
	ap = network.WLAN(network.AP_IF)
	ap.active(flag)
	ap.config(essid='animalito')


def bajar_AP():
	ap = network.WLAN(network.AP_IF)
	ap.active(False)

