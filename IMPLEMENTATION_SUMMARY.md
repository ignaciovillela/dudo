# Implementación: Juego Automático con Apuesta Seleccionada

## Descripción
Cuando se agota el tiempo de turno (timeout), el juego ahora ejecuta la apuesta que el jugador tiene seleccionada, en lugar de hacer un paso automático.

## Cambios Realizados

### Backend (Python)

#### game/models.py
- **Nuevo campo en Player**: `selected_bid: Optional[Bid] = None`
  - Almacena la apuesta que el jugador tiene seleccionada
  - Se usa cuando se agota el timeout del turno

#### game/manager.py
- **Nuevo handler**: `_h_select_bid()`
  - Recibe mensajes de tipo `select_bid` del cliente
  - Valida que la apuesta sea válida
  - Almacena la apuesta en `player.selected_bid` sin ejecutarla

- **Rate limit exception**: Agregado `select_bid` a la lista de tipos sin límite de rate
  - Permite que el cliente envíe actualizaciones frecuentemente sin penalización

- **Modificación**: `_run_timeout_action()`
  - Si existe `player.selected_bid`, ejecuta esa apuesta
  - Si no existe, mantiene el comportamiento anterior (paso o apuesta mínima)

### Frontend (JavaScript)

#### static/app.js
- **Nueva función**: `saveBidSelection()`
  - Envía un mensaje `select_bid` al servidor
  - Solo se ejecuta si es el turno del jugador

- **Modificación**: `selectFace()`
  - Ahora llama a `saveBidSelection()` después de cambiar la cara

- **Modificación**: `adjBid()`
  - Ahora llama a `saveBidSelection()` después de cambiar la cantidad

## Flujo de Uso

1. **Jugador en turno cambia su apuesta**: Selecciona una cara o cantidad diferentes
2. **Cliente envía select_bid**: Se envía el mensaje al servidor automáticamente
3. **Servidor guarda la apuesta**: Se almacena en `player.selected_bid`
4. **Se agota el timeout del turno**: 
   - Si hay una apuesta guardada: Se ejecuta automáticamente
   - Si no hay: Se mantiene el comportamiento anterior

## Comportamiento

- Si el jugador **hace una acción manualmente** (bid, paso, dudo, calzo), la acción seleccionada se limpia
- Si el jugador **no hace nada y se agota el tiempo**, se ejecuta la apuesta seleccionada
- Si el jugador **no ha seleccionado nada**, se ejecuta un paso o apuesta mínima (como antes)

## Compatibilidad

- Todos los cambios son retrocompatibles
- El comportamiento anterior se mantiene si el jugador no utiliza la nueva funcionalidad

