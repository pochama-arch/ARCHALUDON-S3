from machine import Pin, PWM, SoftI2C
from servo import Servo
import tcs34725
import network
import socket
import time


# 1. CONSTANTES DE HARDWARE, CALIBRACIÓN Y CINEMÁTICA
# Wi-Fi Punto de Acceso (Red propia de la ESP32-S3)
WIFI_SSID = "Banda_Color_ESP32"
WIFI_PASS = "12345678"

# Umbrales ópticos para las tapas
UMBRAL_ROJO  = 60
UMBRAL_VERDE = 40

# Sincronización IR -> Sensor de color
RETARDO_IR_LENTE_MS = 300

# Ángulos del Deflector Bidireccional (Servo Clasificador)
ANGULO_REPOSO = 0     # Azul: pasa directo
ANGULO_VERDE  = 55    # Verde: rampa diagonal
ANGULO_ROJO   = 115   # Rojo: rampa de espera
ANGULO_GOLPE  = 180   # Rojo: Ángulo final para patear la tapa

# Tiempos cinemáticos del Clasificador
TIEMPO_LLEVAR_MS    = 10
DURACION_RAMPA_MS   = 2500  # Tiempo que el brazo sostiene la tapa
TIEMPO_GOLPE_MS     = 350   # Tiempo que dura el movimiento brusco hacia 180°
COOLDOWN_LECTURA_MS = 1500  # Evita leer la misma tapa tras la pausa

# Ángulos y tiempos del Dispensador
ANGULO_DISP_REPOSO     = 180
ANGULO_DISP_EMPUJAR    = 35
INTERVALO_DISPENSAR_MS = 4500

# Configuración del Barrido Suave del Dispensador
TIEMPO_EMPUJE_DISP_MS  = 1000
PASO_GRADOS            = 5
RETARDO_PASO_MS        = 10

# Velocidad de la banda y límite de alarma por caja
PWM_PORCENTAJE = 70
MAX_TAPAS_CAJA = 8     # Alarma si hay más de 8 tapas (> 8)

# 2. INICIALIZACIÓN DE PERIFÉRICOS

print("=== INICIANDO CELDA AUTOMATIZADA MAESTRA ===")

servo_clasificador = Servo(pin_id=5)
servo_clasificador.write(ANGULO_REPOSO)

servo_dispensador = Servo(pin_id=6)
servo_dispensador.write(ANGULO_DISP_REPOSO)

i2c = SoftI2C(scl=Pin(9), sda=Pin(8), freq=100000)
print("Dispositivos I2C detectados:", i2c.scan())

sensor_color = tcs34725.TCS34725(i2c)
sensor_color.integration_time(24)
sensor_color.gain(4)
sensor_color.active(True)

sensor_ir = Pin(2, Pin.IN, Pin.PULL_UP)

bin1 = Pin(39, Pin.OUT)
bin2 = Pin(40, Pin.OUT)
pwm_motor = PWM(Pin(41), freq=1000)

# 3. VARIABLES GLOBALES DE ESTADO Y CONTEO
sistema_activo    = False

# Contadores por color
cont_rojo         = 0
cont_verde        = 0
cont_azul         = 0

# Estados del Clasificador
servo_pendiente   = False
fase_clasificador = 0       # 0: Reposo, 1: Posición, 2: Golpe, 3: Regreso
requiere_golpe    = False
angulo_objetivo   = 0
t_activar_servo   = 0
t_iniciar_golpe   = 0
t_regresar_servo  = 0
t_ultima_lectura  = 0

# Estados del Dispensador
empujando_tapa        = False
t_proximo_dispensado  = 0
t_retraer_dispensador = 0
angulo_actual_disp    = ANGULO_DISP_REPOSO
t_ultimo_paso         = 0

# 4. FUNCIONES DE CONTROL DEL SISTEMA 
def controlar_banda(encender):
    """Enciende o detiene el motor DC de la banda transportadora."""
    global sistema_activo
    if encender:
        bin1.value(0)
        bin2.value(1)
        pwm_motor.duty_u16(int((PWM_PORCENTAJE / 100.0) * 65535))
        sistema_activo = True
    else:
        pwm_motor.duty_u16(0)
        sistema_activo = False


def apagar_todo():
    """Apaga motor y lleva los servos a posición segura al detener."""
    global sistema_activo
    sistema_activo = False
    pwm_motor.duty_u16(0)
    bin1.value(0)
    bin2.value(0)
    servo_clasificador.write(ANGULO_REPOSO)
    servo_dispensador.write(ANGULO_DISP_REPOSO)


def verificar_alarmas():
    """Revisa si alguna caja superó las 8 tapas y devuelve lista de alertas."""
    alertas = []
    if cont_rojo > MAX_TAPAS_CAJA:
        alertas.append("ROJA")
    if cont_verde > MAX_TAPAS_CAJA:
        alertas.append("VERDE")
    if cont_azul > MAX_TAPAS_CAJA:
        alertas.append("AZUL")
    return alertas


def actualizar_dispensador(ahora):
    """Gestiona el empuje suave y retorno rápido del tubo dispensador."""
    global empujando_tapa, t_retraer_dispensador, angulo_actual_disp
    global t_ultimo_paso, t_proximo_dispensado

    # 1. Activar inicio de empuje
    if not empujando_tapa and ahora >= t_proximo_dispensado:
        empujando_tapa = True
        t_retraer_dispensador = ahora + TIEMPO_EMPUJE_DISP_MS
        print("[DISPENSADOR] Empujando tapa SUAVEMENTE...")

    # 2. Barrido progresivo desde 180° hasta 35°
    if empujando_tapa and angulo_actual_disp > ANGULO_DISP_EMPUJAR:
        if ahora >= t_ultimo_paso + RETARDO_PASO_MS:
            angulo_actual_disp -= PASO_GRADOS
            if angulo_actual_disp < ANGULO_DISP_EMPUJAR:
                angulo_actual_disp = ANGULO_DISP_EMPUJAR
            servo_dispensador.write(angulo_actual_disp)
            t_ultimo_paso = ahora

    # 3. Retorno rápido a posición de reposo
    if empujando_tapa and ahora >= t_retraer_dispensador:
        angulo_actual_disp = ANGULO_DISP_REPOSO
        servo_dispensador.write(ANGULO_DISP_REPOSO)
        empujando_tapa = False
        t_proximo_dispensado = ahora + INTERVALO_DISPENSAR_MS
        print("[DISPENSADOR] Retorno rápido ejecutado.\n")


def leer_y_clasificar_color(ahora):
    """Detecta tapa por IR, frena banda, lee RGB, cuenta y programa el servo."""
    global t_ultima_lectura, angulo_objetivo, requiere_golpe
    global t_activar_servo, t_iniciar_golpe, t_regresar_servo
    global fase_clasificador, servo_pendiente
    global cont_rojo, cont_verde, cont_azul

    ir_detecta = (sensor_ir.value() == 0)
    if not (ir_detecta and (ahora >= t_ultima_lectura + COOLDOWN_LECTURA_MS)):
        return

    # 1. Esperar a que la tapa llegue bajo el lente del TCS34725
    time.sleep_ms(RETARDO_IR_LENTE_MS)

    # 2. Paro momentáneo para lectura estática precisa
    print("[SISTEMA] Tapa en posición. Deteniendo banda para lectura...")
    pwm_motor.duty_u16(0)
    time.sleep_ms(150)

    # 3. Lectura cruda y cálculo de proporciones RGB
    r, g, b, c = sensor_color.read(raw=True)
    t_ultima_lectura = time.ticks_ms()
    ahora = t_ultima_lectura

    suma = r + g + b
    if suma > 0:
        porcentaje_rojo  = int((r / suma) * 100)
        porcentaje_verde = int((g / suma) * 100)
        porcentaje_azul  = int((b / suma) * 100)
    else:
        porcentaje_rojo = porcentaje_verde = porcentaje_azul = 0

    print(f"Tapa escaneada -> R: {porcentaje_rojo}% | G: {porcentaje_verde}% | B: {porcentaje_azul}% | Luz C: {c}")

    # 4. Reanudar marcha de la banda
    print("[SISTEMA] Lectura completa. Reanudando marcha.")
    controlar_banda(True)

    # 5. Decisión de color, conteo y programación cinemática
    if porcentaje_rojo >= UMBRAL_ROJO:
        cont_rojo += 1
        print(f" -> Clasificación: ROJO (Total Rojas: {cont_rojo})\n")
        angulo_objetivo   = ANGULO_ROJO
        requiere_golpe    = True
        t_activar_servo   = ahora + TIEMPO_LLEVAR_MS
        t_iniciar_golpe   = t_activar_servo + DURACION_RAMPA_MS
        t_regresar_servo  = t_iniciar_golpe + TIEMPO_GOLPE_MS
        fase_clasificador = 1
        servo_pendiente   = True

    elif porcentaje_verde >= UMBRAL_VERDE:
        cont_verde += 1
        print(f" -> Clasificación: VERDE (Total Verdes: {cont_verde})\n")
        angulo_objetivo   = ANGULO_VERDE
        requiere_golpe    = False
        t_activar_servo   = ahora + TIEMPO_LLEVAR_MS
        t_regresar_servo  = t_activar_servo + DURACION_RAMPA_MS
        fase_clasificador = 1
        servo_pendiente   = True

    else:
        cont_azul += 1
        print(f" -> Clasificación: AZUL (Total Azules: {cont_azul})\n")

    # Alerta por consola si se superan las 8 tapas
    alertas = verificar_alarmas()
    if alertas:
        print(f"*** [ALARMA DE CAPACIDAD] >{MAX_TAPAS_CAJA} TAPAS EN CAJA: {', '.join(alertas)} ***\n")


def actualizar_clasificador(ahora):
    """Ejecuta las 3 fases no bloqueantes del brazo desviador."""
    global fase_clasificador, servo_pendiente

    if not servo_pendiente:
        return

    # FASE 1: Llevar al ángulo objetivo (55° o 115°)
    if fase_clasificador == 1 and ahora >= t_activar_servo:
        servo_clasificador.write(angulo_objetivo)
        fase_clasificador = 2 if requiere_golpe else 3
        print(f" -> [CLASIFICADOR] Brazo posicionado en {angulo_objetivo} grados")

    # FASE 2: Dar el golpe a 180° (solo Rojo)
    if fase_clasificador == 2 and ahora >= t_iniciar_golpe:
        servo_clasificador.write(ANGULO_GOLPE)
        fase_clasificador = 3
        print(f" -> [CLASIFICADOR] ¡Bateando tapa! Giro rápido a {ANGULO_GOLPE} grados")

    # FASE 3: Regresar a reposo (0°)
    if fase_clasificador == 3 and ahora >= t_regresar_servo:
        servo_clasificador.write(ANGULO_REPOSO)
        servo_pendiente = False
        fase_clasificador = 0
        print(" -> [CLASIFICADOR] Brazo de vuelta a 0 grados\n")


# 5. SERVIDOR WEB LOCAL (WI-FI AP NO BLOQUEANTE)

def iniciar_servidor_web():
    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        ap.config(essid=WIFI_SSID, password=WIFI_PASS, authmode=network.AUTH_WPA_WPA2_PSK)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", 80))
        srv.listen(2)
        srv.setblocking(False)  
        print(f"[WI-FI AP] Red '{WIFI_SSID}' activa | Clave: {WIFI_PASS} | IP: http://{ap.ifconfig()[0]}")
        return srv
    except Exception as e:
        print("[WI-FI AP] Advertencia al iniciar Wi-Fi:", e)
        return None


def generar_html():
    """Construye la interfaz web ligera para la tablet."""
    alertas = verificar_alarmas()
    hay_alarma = len(alertas) > 0
    total = cont_rojo + cont_verde + cont_azul

    estado_txt = "ACTIVO (En marcha)" if sistema_activo else "DETENIDO"
    estado_bg  = "#16a34a" if sistema_activo else "#dc2626"

    banner_alarma = ""
    script_sonido = ""
    if hay_alarma:
        cajas = ", ".join(alertas)
        banner_alarma = f"""
        <div class="alarma">
            &#9888; ALARMA: MÁS DE {MAX_TAPAS_CAJA} TAPAS EN CAJA {cajas} &#9888;<br>
            <small>Por favor realice cambio de caja y reinicie el contador.</small>
        </div>
        """
        script_sonido = """
        <script>
        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var osc = ctx.createOscillator();
            osc.type = 'square';
            osc.frequency.setValueAtTime(880, ctx.currentTime);
            osc.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.35);
        } catch(e) {}
        </script>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="2">
<title>Monitor Banda Clasificadora</title>
<style>
  body {{ font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; margin: 0; padding: 16px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 10px; }}
  .estado {{ background: {estado_bg}; padding: 12px; border-radius: 10px; font-weight: bold; font-size: 1.2rem; margin-bottom: 16px; }}
  .alarma {{ background: #ef4444; color: #fff; padding: 16px; border-radius: 10px; font-weight: bold; font-size: 1.2rem; margin-bottom: 16px; animation: parpadeo 0.8s infinite; border: 3px solid #fef08a; }}
  @keyframes parpadeo {{ 50% {{ opacity: 0.4; }} }}
  .grid {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; margin-bottom: 18px; }}
  .card {{ flex: 1; min-width: 110px; background: #1e293b; padding: 16px; border-radius: 12px; border-top: 6px solid #64748b; }}
  .rojo {{ border-color: #ef4444; }}
  .verde {{ border-color: #22c55e; }}
  .azul {{ border-color: #3b82f6; }}
  .num {{ font-size: 2.5rem; font-weight: bold; margin: 8px 0; }}
  .btn {{ display: inline-block; background: #f59e0b; color: #0f172a; text-decoration: none; font-weight: bold; padding: 14px 24px; border-radius: 10px; font-size: 1.05rem; }}
</style>
</head>
<body>
  <h1>Control Celda Clasificadora</h1>
  <div class="estado">SISTEMA: {estado_txt}</div>
  {banner_alarma}
  <div class="grid">
    <div class="card rojo"><div>ROJAS</div><div class="num">{cont_rojo}</div><div>Máx: {MAX_TAPAS_CAJA}</div></div>
    <div class="card verde"><div>VERDES</div><div class="num">{cont_verde}</div><div>Máx: {MAX_TAPAS_CAJA}</div></div>
    <div class="card azul"><div>AZULES</div><div class="num">{cont_azul}</div><div>Máx: {MAX_TAPAS_CAJA}</div></div>
  </div>
  <p>Total procesadas: <strong>{total}</strong></p>
  <a class="btn" href="/reset">Reiniciar Contadores (Cambio de Caja)</a>
  {script_sonido}
</body>
</html>"""
    return html


def atender_cliente_web(srv):
    """Atiende peticiones HTTP de la tablet sin bloquear la ejecución."""
    global cont_rojo, cont_verde, cont_azul

    if srv is None:
        return

    try:
        conn, addr = srv.accept()
    except OSError:
        # No hay peticiones en este milisegundo -> sale de inmediato
        return

    try:
        conn.settimeout(0.05)
        req = conn.recv(512).decode("utf-8", "ignore")
        if "GET /reset" in req:
            cont_rojo = 0
            cont_verde = 0
            cont_azul = 0
            print("[WEB] Contadores reiniciados desde la tablet (Cambio de caja).")
            resp = "HTTP/1.1 303 See Other\r\nLocation: /\r\nConnection: close\r\n\r\n"
            conn.sendall(resp.encode("utf-8"))
        else:
            cuerpo = generar_html().encode("utf-8")
            encabezado = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(cuerpo)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            conn.sendall(encabezado + cuerpo)
    except Exception:
        pass
    finally:
        conn.close()

# 6.MAIN

def main():
    global t_proximo_dispensado

    servidor_web = iniciar_servidor_web()
    controlar_banda(True)
    t_proximo_dispensado = time.ticks_ms() + 1500

    print("Banda en marcha y dispensador activo. Ciclo automático iniciado...\n")

    try:
        while True:
            ahora = time.ticks_ms()

            actualizar_dispensador(ahora)
            leer_y_clasificar_color(ahora)
            actualizar_clasificador(ahora)
            atender_cliente_web(servidor_web)

            time.sleep_ms(10)

    except KeyboardInterrupt:
        print("\n[PARADA] Apagando motor DC y llevando servos a posiciones seguras...")
        apagar_todo()


if __name__ == "__main__":
    main()
