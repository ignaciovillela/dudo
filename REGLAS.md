# Dudo — El Juego de los Cachos

## Objetivo

Ser el último jugador con dados. Cada jugador comienza con **5 dados**.

---

## Conceptos base

### Pintas

- 1: As
- 2: Tonto
- 3: Tren
- 4: Cuadra
- 5: Quina
- 6: Cena

### Ases

- Los ases (1) son comodines para apuestas de caras distintas de 1.
- En apuestas de ases, solo cuentan los dados con cara 1.

---

## Estructura del juego

### Inicio

- El jugador inicial de la primera ronda se elige aleatoriamente.

### Ronda

Una ronda se define como:

1. Todos los jugadores lanzan sus dados.
2. El primer jugador elige el sentido de la ronda (antes de su primera acción).
3. El jugador correspondiente inicia con una apuesta.
4. Los turnos avanzan en el sentido elegido.
5. La ronda termina inmediatamente cuando ocurre un desafío (Dudo o Calzo).

---

## Sentido de la ronda

Al inicio de cada ronda, el primer jugador elige el sentido en que avanzan los turnos:

- **Horario (↻)**
- **Anti-horario (↺)**

### Reglas del sentido

- Solo el primer jugador de la ronda puede elegir o cambiar el sentido.
- Puede cambiarlo libremente hasta que realice su primera acción (apuesta o paso).
- Una vez realizada la primera acción, el sentido queda bloqueado para esa ronda.
- El sentido por defecto es horario.

---

## Turnos

En su turno, un jugador debe realizar exactamente una de las siguientes acciones:

1. **Apostar (subir la apuesta)**
2. **Pasar**
3. **Dudar (Dudo)**
4. **Calzar (Calzo)**

- Cada jugador realiza solo una acción por turno.
- Después de apostar o pasar, el turno avanza al siguiente jugador en el sentido activo.
- Después de un desafío, la ronda termina.

---

## Apuestas

Una apuesta se define como:

- cantidad: entero ≥ 1  
- cara: valor entre 1 y 6  

La apuesta vigente es siempre la última apuesta realizada y se mantiene hasta ser reemplazada o hasta el fin de la ronda.

### Reglas de incremento

Toda nueva apuesta debe ser estrictamente mayor que la anterior:

- Misma cara → mayor cantidad
- Misma cantidad → cara mayor

#### Cambio entre normales y ases

- Regular → Ases: mínimo `ceil(cantidad_anterior / 2)`
- Ases → Regular: mínimo `cantidad_anterior × 2 + 1`

Estas reglas aplican siempre al cambiar entre ases y otras caras.

---

## Paso

El paso es un tipo de apuesta especial.

### Reglas generales

- Cada jugador puede pasar **una vez por ronda**.
- Pasar no modifica la apuesta vigente.
- El turno avanza normalmente en el sentido activo.

### Validación del paso

Un paso es válido si los dados del jugador cumplen una de las siguientes condiciones:

- Todos distintos
- Todos iguales
- Full (3 dados de un valor y 2 de otro)

Los dados se evalúan por su valor real (los ases no son comodines).

> El sistema no valida automáticamente el paso. Solo se verifica si es desafiado.

### Interacciones

- Si la acción activa es un paso:
  - Se puede **dudar el paso**
  - No se puede calzar
  - No se puede dudar la apuesta anterior

- Solo el último paso realizado puede ser desafiado.
- Pasos anteriores pasan a ser historial y no pueden ser desafiados.

- Si un jugador realiza una nueva apuesta después de un paso:
  - El juego continúa normalmente
  - La nueva apuesta pasa a ser la acción activa

---

## Acción activa

La acción activa es siempre la última acción realizada:

- Si es una apuesta → se puede dudar o calzar
- Si es un paso → solo se puede dudar ese paso

Acciones anteriores son historial y no pueden ser desafiadas.

---

## Desafíos

Un desafío finaliza inmediatamente la ronda.

No se puede desafiar la propia acción.

Un jugador eliminado (0 dados) no puede realizar desafíos.

Si múltiples desafíos ocurren simultáneamente, se resuelve el primero recibido por el backend.

---

### Dudo

Se cuestiona la acción activa.

#### Si la acción activa es una apuesta:

- Se revelan todos los dados.
- Se cuentan los dados que coinciden con la cara (incluyendo ases si aplica).

| Resultado | Consecuencia |
|----------|-------------|
| Cantidad ≥ apuesta | El dudador pierde 1 dado |
| Cantidad < apuesta | El apostador pierde 1 dado |

#### Si la acción activa es un paso:

| Resultado | Consecuencia |
|----------|-------------|
| Paso válido | El dudador pierde 1 dado |
| Paso inválido | El jugador que pasó pierde 1 dado |

---

### Calzo

Solo se puede aplicar sobre la acción activa si esta es una apuesta.

Se declara que la cantidad es exacta.

| Resultado | Consecuencia |
|----------|-------------|
| Exacto | El calzador no pierde dado. Si no era su turno, recupera 1 dado (máx. 5) |
| No exacto | El calzador pierde 1 dado |

- El apostador nunca pierde dados en un calzo.
- El jugador en turno no recupera dados.

---

## Resolución de ronda

- Se revelan todos los dados durante 7 segundos.
- Los dados revelados se muestran en la mesa, sobre las cartas de cada jugador.
- Se determina el resultado del desafío.
- El jugador que:
  - perdió un dado, o
  - realizó el calzo

  inicia la siguiente ronda.

- Si ese jugador fue eliminado, comienza el siguiente jugador activo.

---

## Eliminación y victoria

- Un jugador queda eliminado al llegar a 0 dados.
- No puede volver a participar en la partida (no puede apostar, pasar ni desafiar).

El juego termina cuando queda un solo jugador con dados.

Al finalizar:
- Se muestran los resultados de la última ronda antes de declarar al ganador.
- Cada jugador vuelve al lobby cuando lo decide (no hay cierre automático).

---

## Notas de implementación

- El sistema debe impedir apuestas inválidas.
- El paso no se valida automáticamente; solo se verifica si es desafiado.
- Solo la acción activa puede ser desafiada.
- Cada jugador puede pasar una sola vez por ronda.
- Los desafíos tienen prioridad sobre cualquier otra acción.
- El Dudo no otorga dados al dudador (solo el Calzo exitoso fuera de turno otorga dados).
- El sentido de la ronda es bloqueado tras la primera acción del primer jugador.
- Los jugadores eliminados siguen conectados pero no pueden actuar.
