# 🎨 Banda Transportadora Selectora de Color | Automated Color-Sorting Conveyor Belt

*[Español](#español) | [English](#english)*

---

## <a name="español"></a>🇪🇸 Descripción del Proyecto

Prototipo mecatrónico de una **celda de clasificación automatizada** capaz de detectar, analizar y separar piezas en movimiento según su color (**Rojo, Verde y Azul**) hacia tres destinos distintos utilizando un único actuador desviador.

### ⚙️ Arquitectura del Sistema
* **Control y Lógica:** Microcontrolador **ESP32-S3** programado en **MicroPython**, utilizando temporización no bloqueante (`time.ticks_ms`) y el canal claro (C) del sensor óptico como disparador (*trigger*) por software.
* **Sensado:** Sensor colorimétrico RGB **TCS34725** (comunicación I2C, tiempo de integración de 24ms} calibrado para lectura continua en movimiento.
* **Actuación y Transmisión:** Motorreductor DC **JGA25-370** (130RPM) con doble correa dentada paralela **GT2** y un servomotor **MG90S** configurado como deflector bidireccional de tres estados (115° Rojo, 55° Verde, 0° Azul).
* **Electrónica y Potencia:** PCB propia con conectores modulares **XH 2.54**, alimentada por banco **Li-Ion 2S 7.4V** con regulación multinivel aislada (7.4V potencia vía puente H MOSFET **TB6612FNG**, 5V para servo con **LM323T** y 3.3V lógicos con **LM1117T-3.3**).
* **Estructura:** Armadura plana tipo **Warren** en acrílico (PMMA) de 2.6mm diseñada bajo análisis estático (Método de Nodos) y alimentador vertical por gravedad.

---

## <a name="english"></a>🇺🇸 Project Overview

Mechatronic prototype of an **automated color-sorting conveyor cell** designed to detect, analyze, and sort moving objects (**Red, Green, and Blue**) into three separate bins using a single bi-directional plow diverter.

### ⚙️ System Architecture
* **Control & Logic:** **ESP32-S3** microcontroller running **MicroPython**, implementing non-blocking timing (`time.ticks_ms`) and software triggering via the optical sensor's Clear C channel.
* **Sensing:** **TCS34725** RGB color sensor (I2C protocol, 24 integration time) calibrated for real-time color classification in motion.
* **Actuation & Transmission:** **JGA25-370** DC gearmotor 130RPM) driving dual parallel **GT2** timing belts, paired with an **MG90S** micro-servo acting as a 3-state bi-directional diverter (115° Red, 55° Green, 0° Blue).
* **Electronics & Power:** Custom single-layer PCB with **XH 2.54** locking connectors, powered by a **7.4V 2S Li-Ion** pack with isolated multi-rail regulation (7.4V motor rail via **TB6612FNG** MOSFET H-bridge, 5V servo rail via **LM323T**, and 3.3V} logic rail via **LM1117T-3.3**).
* **Mechanical Structure:** Dual planar **Warren truss** frame laser-cut in 2.6mm PMMA acrylic (validated via Method of Joints static analysis) with a gravity-fed vertical dispenser.

