'use strict';

// ══════════════════════════════════  DICE  ══════════════════════════════════
// 3×3 grid positions (row,col) where dots appear for each face value
const PIPS = {
  1: [[1,1]],
  2: [[0,2],[2,0]],
  3: [[0,2],[1,1],[2,0]],
  4: [[0,0],[0,2],[2,0],[2,2]],
  5: [[0,0],[0,2],[1,1],[2,0],[2,2]],
  6: [[0,0],[0,2],[1,0],[1,2],[2,0],[2,2]],
};

/**
 * Build a CSS die element.
 * @param {number|null} value  1-6, or null/0 for face-down
 * @param {object}      opts   { size:'sm'|'lg'|null, matchFace:number|null }
 */
function makeDie(value, opts = {}) {
  const el = document.createElement('div');
  el.className = 'die' + (opts.size ? ` die-${opts.size}` : '');

  if (!value) {
    el.classList.add('die-down');
    // Fill grid so ::after trick works
    for (let i = 0; i < 9; i++) el.appendChild(document.createElement('div'));
    return el;
  }

  const layout = PIPS[value] || PIPS[1];
  const active = new Set(layout.map(([r,c]) => r*3+c));
  const isMatch = opts.matchFace != null && (value === opts.matchFace || value === 1 && opts.matchFace !== 1);

  for (let i = 0; i < 9; i++) {
    const pip = document.createElement('div');
    if (active.has(i)) {
      pip.className = 'pip' + (isMatch ? ' match' : '');
    } else {
      pip.className = 'pip empty';
    }
    el.appendChild(pip);
  }
  return el;
}

/**
 * Construye un div con dados dispuestos en filas escalonadas:
 * 5→(3,2)  4→(2,2)  3→(2,1)  2→(2)  1→(1)
 * diceOrCount: número (dado boca abajo) o array de valores (dado revelado)
 */
function buildDiceRows(diceOrCount, { size = 'sm', matchFace = null, revealed = false } = {}) {
  const isArr  = Array.isArray(diceOrCount);
  const count  = isArr ? diceOrCount.length : diceOrCount;
  const values = isArr ? diceOrCount : Array(count).fill(null);

  const wrap = document.createElement('div');
  wrap.className = 'dice-rows';

  if (count <= 2) {
    const row = document.createElement('div');
    row.className = 'dice-row-inner';
    values.forEach((val, i) => {
      const d = makeDie(val, { size, matchFace });
      if (revealed) { d.classList.add('revealed'); d.style.animationDelay = `${i * 60}ms`; }
      row.appendChild(d);
    });
    wrap.appendChild(row);
  } else {
    const top = Math.ceil(count / 2);
    [values.slice(0, top), values.slice(top)].forEach((chunk, ri) => {
      const row = document.createElement('div');
      row.className = 'dice-row-inner';
      chunk.forEach((val, ci) => {
        const d = makeDie(val, { size, matchFace });
        if (revealed) { d.classList.add('revealed'); d.style.animationDelay = `${(ri === 0 ? ci : top + ci) * 60}ms`; }
        row.appendChild(d);
      });
      wrap.appendChild(row);
    });
  }
  return wrap;
}

function animateRoll(container) {
  const dice = container.querySelectorAll('.die');
  dice.forEach((d, i) => {
    setTimeout(() => {
      d.classList.add('rolling');
      d.addEventListener('animationend', () => d.classList.remove('rolling'), { once: true });
    }, i * 80);
  });
}

// ══════════════════════════════════  STATE  ═══════════════════════════════════
const S = {
  ws:             null,
  playerId:       null,
  playerName:     '',
  roomId:         '',
  isHost:         false,
  isReady:        false,

  // Game
  phase:          'lobby',
  players:        {},   // id → {id, name, dice_count, connected, ready}
  playerOrder:    [],
  myDice:         [],
  currentPid:     null,
  currentBid:     null,
  activePaso:     null,  // {player_id, player_name} si la acción activa es un paso
  hasPassed:      false, // si yo ya pasé en esta ronda
  roundNum:       0,
  totalDice:      0,
  revealDice:       {},    // pid → dice[] durante la fase de reveal
  revealBidFace:    null,  // cara apostada para resaltar coincidencias
  direction:           1,   // 1 = horario, -1 = antihorario
  roundFirstPlayer:    '',
  hasFirstAction:      false,

  // UI bid inputs
  bidQty:         1,
  bidFace:        2,
};

// ══════════════════════════════════  WEBSOCKET  ════════════════════════════════
function connect(roomId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  S.ws = new WebSocket(`${proto}://${location.host}/ws/${roomId}`);

  S.ws.onopen    = () => log('Conectado al servidor', 'system');
  S.ws.onclose   = () => { log('Desconectado', 'system'); showToast('Conexión cerrada', true); };
  S.ws.onerror   = () => showToast('Error de conexión', true);
  S.ws.onmessage = (e) => handleMsg(JSON.parse(e.data));
}

function send(obj) {
  if (S.ws && S.ws.readyState === WebSocket.OPEN)
    S.ws.send(JSON.stringify(obj));
}

// ══════════════════════════════════  HANDLERS  ════════════════════════════════
function handleMsg(msg) {
  const H = {
    connected:          onConnected,
    joined:             onJoined,
    player_joined:      onPlayerJoined,
    player_ready:       onPlayerReady,
    player_disconnected:onPlayerDisc,
    game_started:       onGameStarted,
    your_dice:          onYourDice,
    turn:               onTurn,
    bid_made:           onBidMade,
    paso_made:          onPasoMade,
    direction_set:      onDirectionSet,
    reveal:             onReveal,
    new_round:          onNewRound,
    player_eliminated:  onEliminated,
    game_over:          onGameOver,
    error:              onError,
  };
  const fn = H[msg.type];
  if (fn) fn(msg);
}

function onConnected(msg) {
  S.playerId = msg.player_id;
  S.roomId   = msg.room_id;
  // Now send join with the name
  send({ type: 'join', name: S.playerName });
}

function onJoined(msg) {
  S.isHost      = msg.is_host;
  S.players     = msg.players;
  S.playerOrder = msg.player_order;

  document.getElementById('disp-room-code').textContent = S.roomId;
  document.getElementById('lobby-form').style.display = 'none';
  document.getElementById('lobby-room').style.display = 'block';

  renderLobbyPlayers();

  if (S.isHost) {
    document.getElementById('btn-start').style.display = 'inline-flex';
  }
  log(`Unido a la sala ${S.roomId}`, 'system');
}

function onPlayerJoined(msg) {
  S.players[msg.player.id] = msg.player;
  S.playerOrder.push(msg.player.id);
  renderLobbyPlayers();
  log(`${msg.player.name} se unió`, 'system');
}

function onPlayerReady(msg) {
  if (S.players[msg.player_id])
    S.players[msg.player_id].ready = msg.ready;
  renderLobbyPlayers();
}

function onPlayerDisc(msg) {
  if (S.players[msg.player_id])
    S.players[msg.player_id].connected = false;
  renderLobbyPlayers();
  renderOtherPlayers();
  log(`${msg.player_name} se desconectó`, 'system');
}

function onGameStarted(msg) {
  S.phase       = 'playing';
  S.playerOrder = msg.player_order;
  S.currentBid      = null;
  S.activePaso      = null;
  S.hasPassed       = false;
  S.revealDice      = {};
  S.revealBidFace   = null;
  S.direction         = 1;
  S.roundFirstPlayer  = '';
  S.hasFirstAction    = false;
  showScreen('game');
  renderOtherPlayers();
  updateBidDisplay();
  // Limpiar log de partidas anteriores
  const logEl = document.getElementById('game-log');
  if (logEl) logEl.innerHTML = '';
  log('─── Juego iniciado ───', 'round');
}

function onYourDice(msg) {
  S.myDice    = msg.dice;
  S.roundNum  = msg.round_number;
  S.totalDice = msg.total_dice;

  // Merge updated player counts
  Object.assign(S.players, msg.players);

  renderMyDice(true);
  renderOtherPlayers();
  document.getElementById('disp-round').textContent = S.roundNum;
  document.getElementById('disp-total').textContent = S.totalDice;
  document.getElementById('my-name-disp').textContent = S.playerName;
  document.getElementById('my-count-disp').textContent = '●'.repeat(S.myDice.length);
}

function onTurn(msg) {
  S.currentPid       = msg.player_id;
  S.currentBid       = msg.current_bid;
  S.activePaso       = msg.active_paso || null;
  S.direction        = msg.direction ?? 1;
  S.roundFirstPlayer = msg.round_first_player ?? '';
  S.hasFirstAction   = msg.has_first_action ?? false;
  S.phase            = 'playing';

  const isMe = S.currentPid === S.playerId;
  const name = S.players[S.currentPid]?.name || msg.player_name;

  const banner  = document.getElementById('turn-banner');
  const myArea  = document.querySelector('.my-area');
  const bidPanel = document.getElementById('bid-panel');

  banner.textContent = isMe ? '¡Tu turno!' : `Turno de ${name}`;

  if (isMe) {
    banner.classList.remove('my-turn', 'my-turn-entry');
    // Trigger reflow para reiniciar la animación de entrada
    void banner.offsetWidth;
    banner.classList.add('my-turn', 'my-turn-entry');
    banner.addEventListener('animationend', () => {
      banner.classList.remove('my-turn-entry');
    }, { once: true });

    myArea?.classList.add('my-turn');
    bidPanel?.classList.add('my-turn');
  } else {
    banner.classList.remove('my-turn', 'my-turn-entry');
    myArea?.classList.remove('my-turn');
    bidPanel?.classList.remove('my-turn');
  }

  updateBidDisplay();
  updateDirectionIndicator();
  updateControls();
  renderOtherPlayers();

  if (isMe) {
    resetBidInputs();
  }
}

function onBidMade(msg) {
  S.currentBid = msg.bid;
  S.activePaso = null;  // la apuesta reemplaza al paso como acción activa
  const b = msg.bid;
  const name = S.players[b.player_id]?.name || b.player_name;
  log(`${name}: ${b.quantity} × ${faceName(b.face)}`, 'bid');
  updateBidDisplay();
  updateControls();
}

function onPasoMade(msg) {
  S.activePaso = { player_id: msg.passer_id, player_name: msg.passer_name };
  if (msg.passer_id === S.playerId) S.hasPassed = true;
  const name = S.players[msg.passer_id]?.name || msg.passer_name;
  log(`${name}: PASO`, 'paso');
  updateBidDisplay();
  updateControls();
}

function onDirectionSet(msg) {
  S.direction = msg.direction === 'cw' ? 1 : -1;
  const arrow = msg.direction === 'cw' ? '↻' : '↺';
  const name  = S.players[msg.player_id]?.name || msg.player_name;
  log(`${name} eligió sentido ${arrow}`, 'system');
  updateDirectionIndicator();
  updateControls();
}

function onReveal(msg) {
  S.phase = 'reveal';
  // Guardar dados revelados para mostrarlos en la mesa
  S.revealDice    = msg.all_dice || {};
  S.revealBidFace = (msg.action === 'paso') ? null : (msg.bid?.face ?? null);
  hideControls();
  // Quitar indicadores de turno activo
  document.getElementById('turn-banner')?.classList.remove('my-turn', 'my-turn-entry');
  document.querySelector('.my-area')?.classList.remove('my-turn');
  document.getElementById('bid-panel')?.classList.remove('my-turn');
  // Mostrar dados revelados en la mesa
  renderMyDice();
  renderOtherPlayers();
  showReveal(msg);
  // Animar pérdida de dado (con un breve delay para que el flip termine)
  if (msg.loser_id) setTimeout(() => animateDieLoss(msg.loser_id), 600);

  const bid = msg.bid || null;
  const face = bid?.face;
  const isCalzo = msg.action === 'calzo';

  let resultText, resultClass;
  if (msg.action === 'paso') {
    if (msg.paso_valid) {
      resultText = `Paso válido. ${msg.challenger_name} pierde un dado.`;
      resultClass = 'lose';
    } else {
      resultText = `Paso inválido. ${msg.passer_name} pierde un dado.`;
      resultClass = 'win';
    }
  } else if (isCalzo) {
    if (msg.calzo_success) {
      const gainText = msg.challenger_gained
        ? `${msg.challenger_name} recupera un dado.`
        : 'La ronda se reinicia.';
      resultText = `¡CALZO! Exactamente ${msg.actual_count} ${faceName(face)}. ${gainText}`;
      resultClass = 'win';
    } else {
      resultText = `Calzo fallido. Había ${msg.actual_count}, no ${bid.quantity} ${faceName(face)}. ${msg.challenger_name} pierde un dado.`;
      resultClass = 'lose';
    }
  } else {
    if (msg.bid_holds) {
      resultText = `¡La apuesta se sostiene! Hay ${msg.actual_count} ${faceName(face)}. ${msg.challenger_name} pierde un dado.`;
      resultClass = 'lose';
    } else {
      resultText = `¡DUDO! Solo hay ${msg.actual_count} ${faceName(face)}. ${S.players[bid.player_id]?.name || bid.player_name} pierde un dado.`;
      resultClass = 'win';
    }
  }

  document.getElementById('reveal-result').textContent = resultText;
  document.getElementById('reveal-result').className = `reveal-result ${resultClass}`;

  log(resultText, resultClass);

  startRevealCountdown(7);
}

function onNewRound(msg) {
  S.roundNum      = msg.round_number;
  S.currentBid       = null;
  S.activePaso       = null;
  S.hasPassed        = false;
  S.revealDice       = {};
  S.revealBidFace    = null;
  S.direction          = 1;
  S.roundFirstPlayer   = '';
  S.hasFirstAction     = false;
  S.phase              = 'playing';
  hideReveal();
  updateDirectionIndicator();
  updateBidDisplay();
  log(`─── Ronda ${S.roundNum} ───`, 'round');
}

function onEliminated(msg) {
  if (S.players[msg.player_id])
    S.players[msg.player_id].dice_count = 0;
  log(`${msg.player_name} fue eliminado`, 'elim');
  renderOtherPlayers();
}

function onGameOver(msg) {
  S.phase = 'game_over';
  hideReveal();
  log(`═══ ${msg.winner_name} GANÓ ═══`, 'win');

  const isWinner = msg.winner_id === S.playerId;
  const overlay  = document.getElementById('game-over-overlay');
  document.getElementById('go-title').textContent  = isWinner ? '¡Ganaste!' : 'Fin de la partida';
  document.getElementById('go-winner').textContent = `${msg.winner_name} es el ganador`;
  overlay.style.display = 'flex';
}

function closeGameOver() {
  document.getElementById('game-over-overlay').style.display = 'none';
  S.phase = 'lobby';
  for (const p of Object.values(S.players)) {
    p.dice_count = 5;
    p.ready = false;
  }
  S.isReady = false;
  showScreen('lobby');
  document.getElementById('lobby-form').style.display = 'none';
  document.getElementById('lobby-room').style.display = 'block';
  renderLobbyPlayers();
  document.getElementById('btn-ready').textContent = '¡Listo!';
  document.getElementById('btn-ready').classList.remove('btn-start');
}

function onError(msg) {
  showToast(msg.message, true);
}

// ══════════════════════════════════  REVEAL UI  ════════════════════════════════
function showReveal(msg) {
  document.getElementById('reveal-overlay').style.display = 'flex';
}

function hideReveal() {
  document.getElementById('reveal-overlay').style.display = 'none';
}

function animateDieLoss(pid) {
  let diceRow;
  if (pid === S.playerId) {
    diceRow = document.getElementById('my-dice-row');
  } else {
    const card = document.querySelector(`.player-card[data-pid="${pid}"]`);
    diceRow = card?.querySelector('.player-card-dice');
  }
  if (!diceRow) return;
  const dice = Array.from(diceRow.querySelectorAll('.die'));
  if (!dice.length) return;
  // Animar el último dado visible
  const target = dice[dice.length - 1];
  target.classList.add('die-lost');
}

let countdownTimer = null;
function startRevealCountdown(seconds) {
  if (countdownTimer) clearInterval(countdownTimer);
  const el = document.getElementById('reveal-countdown');
  let remaining = seconds;
  el.textContent = `Nueva ronda en ${remaining}…`;
  countdownTimer = setInterval(() => {
    remaining--;
    if (remaining <= 0) {
      clearInterval(countdownTimer);
      el.textContent = '';
    } else {
      el.textContent = `Nueva ronda en ${remaining}…`;
    }
  }, 1000);
}

// ══════════════════════════════════  RENDER  ══════════════════════════════════
function renderLobbyPlayers() {
  const list = document.getElementById('lobby-player-list');
  list.innerHTML = '';
  for (const pid of S.playerOrder) {
    const p = S.players[pid];
    if (!p) continue;
    const row = document.createElement('div');
    row.className = 'lobby-player-row' + (S.playerOrder[0] === pid ? ' is-host' : '');

    const av = document.createElement('div');
    av.className = 'player-avatar';
    av.textContent = p.name.charAt(0).toUpperCase();
    av.style.background = playerColor(pid);

    const name = document.createElement('div');
    name.className = 'player-pname';
    name.textContent = p.name;

    const badge = document.createElement('div');
    badge.className = 'ready-badge' + (p.ready ? ' ready' : '');
    badge.textContent = p.ready ? 'Listo' : 'Esperando';

    row.appendChild(av);
    row.appendChild(name);
    row.appendChild(badge);
    list.appendChild(row);
  }
}

function renderOtherPlayers() {
  const container = document.getElementById('other-players');
  container.innerHTML = '';

  // Orden: jugadores que vienen después de mí en el turno, de forma circular
  for (const pid of turnOrderFrom(S.playerId)) {
    if (pid === S.playerId) continue;
    const p = S.players[pid];
    if (!p) continue;

    const card = document.createElement('div');
    card.className = 'player-card' +
      (pid === S.currentPid ? ' active-player' : '') +
      (p.dice_count <= 0 ? ' eliminated' : '');
    card.dataset.pid = pid;

    const nameEl = document.createElement('div');
    nameEl.className = 'player-card-name';
    nameEl.textContent = p.name;

    const countEl = document.createElement('div');
    countEl.className = 'player-card-count';
    countEl.textContent = p.dice_count > 0 ? `${p.dice_count} dado${p.dice_count !== 1 ? 's' : ''}` : 'Eliminado';

    const revealedDice = S.phase === 'reveal' ? S.revealDice[pid] : null;
    const diceRow = revealedDice
      ? buildDiceRows(revealedDice, { size: 'sm', matchFace: S.revealBidFace, revealed: true })
      : buildDiceRows(p.dice_count,  { size: 'sm' });
    diceRow.classList.add('player-card-dice');

    if (pid === S.currentPid && S.phase === 'playing') {
      const arrow = document.createElement('div');
      arrow.className = 'active-turn-arrow';
      arrow.textContent = '▼';
      card.appendChild(arrow);
    }

    card.appendChild(nameEl);
    card.appendChild(countEl);
    card.appendChild(diceRow);
    container.appendChild(card);
  }

  positionPlayers();
}

function renderMyDice(animate = false) {
  const row = document.getElementById('my-dice-row');
  row.innerHTML = '';
  const inReveal  = S.phase === 'reveal';
  const matchFace = inReveal ? S.revealBidFace : null;
  const wrap = buildDiceRows(S.myDice, { size: null, matchFace, revealed: inReveal });
  row.appendChild(wrap);
  if (animate && !inReveal) animateRoll(row);
}

function updateBidDisplay() {
  const noMsg    = document.getElementById('no-bid-msg');
  const visual   = document.getElementById('bid-visual');
  const pasoEl   = document.getElementById('paso-indicator');

  // Paso indicator
  if (S.activePaso) {
    const name = S.players[S.activePaso.player_id]?.name || S.activePaso.player_name;
    pasoEl.textContent = `PASO de ${name}`;
    pasoEl.style.display = 'block';
  } else {
    pasoEl.style.display = 'none';
  }

  if (!S.currentBid) {
    noMsg.style.display = 'block';
    visual.style.display = 'none';
    return;
  }

  noMsg.style.display = 'none';
  visual.style.display = 'flex';

  document.getElementById('bv-qty').textContent = S.currentBid.quantity;

  const dieWrap = document.getElementById('bv-die');
  dieWrap.innerHTML = '';
  dieWrap.appendChild(makeDie(S.currentBid.face, { size: 'lg' }));

  document.getElementById('bv-wild').style.display =
    S.currentBid.face !== 1 ? 'inline' : 'none';
}

// ══════════════════════════════════  CONTROLS  ════════════════════════════════
function updateDirectionIndicator() {
  // Botones del toggle en el panel de apuesta
  const btnCW  = document.getElementById('btn-dir-cw');
  const btnCCW = document.getElementById('btn-dir-ccw');
  if (!btnCW || !btnCCW) return;

  btnCW.classList.toggle('dir-active',  S.direction === 1);
  btnCCW.classList.toggle('dir-active', S.direction === -1);

  // Solo el primer jugador puede cambiar sentido antes de su primera acción
  const canChange = S.playerId === S.roundFirstPlayer && !S.hasFirstAction && S.phase === 'playing';
  btnCW.disabled  = !canChange;
  btnCCW.disabled = !canChange;

  // Indicador en la mesa (junto al banner)
  const ind = document.getElementById('direction-indicator');
  if (ind) {
    ind.textContent = S.direction === 1 ? '↻' : '↺';
    ind.title = S.direction === 1 ? 'Sentido horario' : 'Sentido antihorario';
    ind.style.display = 'inline-flex';
  }
}

function updateControls() {
  const isMyTurn      = S.currentPid === S.playerId && S.phase === 'playing';
  const playing       = S.phase === 'playing';
  const amEliminated  = (S.players[S.playerId]?.dice_count ?? 1) <= 0;
  const hasActivePaso = S.activePaso != null;
  const myOwnPaso     = S.activePaso?.player_id === S.playerId;
  const hasBid        = S.currentBid != null;
  const myOwnBid      = S.currentBid?.player_id === S.playerId;

  // Dudo: disponible si hay acción activa (paso o apuesta) que no sea propia y no estoy eliminado
  const canDudo = playing && !amEliminated && (
    (hasActivePaso && !myOwnPaso) ||
    (!hasActivePaso && hasBid && !myOwnBid)
  );
  // Calzo: solo si la acción activa es una apuesta (no paso) y no estoy eliminado
  const canCalzo = playing && !amEliminated && !hasActivePaso && hasBid && !myOwnBid;
  // Paso: solo en mi turno y si no he pasado esta ronda
  const canPaso = isMyTurn && !S.hasPassed;

  document.getElementById('bid-panel').style.opacity  = isMyTurn ? '1' : '0.5';
  document.getElementById('btn-bid').disabled          = !isMyTurn;
  document.getElementById('btn-paso').disabled         = !canPaso;
  document.getElementById('btn-dudo').disabled         = !canDudo;
  document.getElementById('btn-calzo').disabled        = !canCalzo;
  document.getElementById('wait-msg').style.display   = isMyTurn ? 'none' : 'block';

  // Stepper cantidad y face picker
  document.querySelectorAll('.stepper-qty button').forEach(b => b.disabled = !isMyTurn);
  document.querySelectorAll('.face-btn').forEach(b => b.disabled = !isMyTurn);
}

function hideControls() {
  document.getElementById('btn-bid').disabled   = true;
  document.getElementById('btn-paso').disabled  = true;
  document.getElementById('btn-dudo').disabled  = true;
  document.getElementById('btn-calzo').disabled = true;
}

/** Cantidad mínima válida para apostar la cara `face` dado el estado actual. */
function minQtyForFace(face) {
  if (!S.currentBid) return 1;
  const { quantity: q, face: f } = S.currentBid;
  if (f !== 1 && face === 1) return Math.ceil(q / 2);   // Regular → Ases
  if (f === 1 && face !== 1) return q * 2 + 1;           // Ases → Regular
  // Misma categoría
  if (face > f)  return q;       // cara mayor → misma cantidad válida
  if (face === f) return q + 1;  // misma cara → necesita más cantidad
  return q + 1;                  // cara menor → necesita más cantidad
}

function selectFace(face) {
  S.bidFace = face;
  S.bidQty  = minQtyForFace(face);
  refreshBidInputUI();
}

function adjBid(which, delta) {
  if (which === 'q') {
    const min = minQtyForFace(S.bidFace);
    S.bidQty = Math.max(min, S.bidQty + delta);
  }
  refreshBidInputUI();
}

function resetBidInputs() {
  if (!S.currentBid) {
    S.bidFace = 2;
    S.bidQty  = 1;
  } else {
    S.bidFace = S.currentBid.face;
    S.bidQty  = minQtyForFace(S.bidFace);
  }
  refreshBidInputUI();
}

function refreshBidInputUI() {
  // Cantidad
  document.getElementById('bb-qty').textContent = S.bidQty;

  // Face picker: render si no está inicializado aún
  const picker = document.getElementById('face-picker');
  if (!picker) return;
  if (!picker.dataset.ready) {
    picker.innerHTML = '';
    for (let f = 1; f <= 6; f++) {
      const btn = document.createElement('button');
      btn.className = 'face-btn';
      btn.dataset.face = f;
      btn.onclick = () => selectFace(f);
      btn.appendChild(makeDie(f, { size: 'sm' }));
      const name = ['As','Tonto','Tren','Cuadra','Quina','Cena'][f-1];
      const lbl = document.createElement('span');
      lbl.className = 'face-btn-name';
      lbl.textContent = name;
      btn.appendChild(lbl);
      picker.appendChild(btn);
    }
    picker.dataset.ready = '1';
  }
  // Marcar seleccionada y deshabilitar inválidas
  picker.querySelectorAll('.face-btn').forEach(btn => {
    const f = +btn.dataset.face;
    btn.classList.toggle('selected', f === S.bidFace);
    const min = minQtyForFace(f);
    // Nunca deshabilitar completamente; solo marcar si la cantidad actual la haría inválida
    btn.classList.toggle('face-invalid', false); // siempre seleccionable, se ajusta al hacer click
  });

  // Hint de mínimo
  const hint = document.getElementById('bb-min-hint');
  if (hint) {
    const min = minQtyForFace(S.bidFace);
    hint.textContent = min > 1 ? `(mín. ${min})` : '';
  }
}

// ══════════════════════════════════  ACTIONS  ════════════════════════════════
function sendBid() {
  send({ type: 'bid', quantity: S.bidQty, face: S.bidFace });
}

function sendDirection(value) {
  send({ type: 'direction', value });
}

function sendPaso() {
  send({ type: 'paso' });
}

function sendDudo() {
  send({ type: 'dudo' });
}

function sendCalzo() {
  send({ type: 'calzo' });
}

// ══════════════════════════════════  LOBBY ACTIONS  ════════════════════════════
function joinRoom() {
  const name = document.getElementById('inp-name').value.trim();
  const room = document.getElementById('inp-room').value.trim();
  if (!name) { showToast('Ingresa tu nombre', true); return; }
  if (!room) { showToast('Ingresa el código de sala', true); return; }
  S.playerName = name;
  connect(room);
}

function toggleReady() {
  S.isReady = !S.isReady;
  document.getElementById('btn-ready').textContent = S.isReady ? 'Cancelar' : '¡Listo!';
  send({ type: 'ready' });
}

function startGame() {
  send({ type: 'start' });
}

function copyRoomCode() {
  navigator.clipboard.writeText(S.roomId)
    .then(() => showToast('Código copiado'))
    .catch(() => showToast(S.roomId));
}

// ══════════════════════════════════  UTILS  ══════════════════════════════════
function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => {
    s.classList.remove('active');
    s.style.display = 'none';
  });
  const el = document.getElementById(`${name}-screen`);
  if (el) {
    el.style.display = 'flex';
    el.classList.add('active');
  }
}

let toastTimer = null;
function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isError ? ' error' : '');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}

function log(text, type = 'bid') {
  const logEl = document.getElementById('game-log');
  if (!logEl) return;
  const entry = document.createElement('div');
  entry.className = `log-entry log-${type}`;
  entry.textContent = text;
  logEl.appendChild(entry);
  // Keep last 60 entries
  while (logEl.children.length > 60) logEl.removeChild(logEl.firstChild);
  logEl.scrollTop = logEl.scrollHeight;
}

function faceName(face) {
  const names = { 1: 'uno (comodín)', 2: 'dos', 3: 'tres', 4: 'cuatro', 5: 'cinco', 6: 'seis' };
  return names[face] || face;
}

/**
 * Posiciona las cartas de los oponentes alrededor de una elipse centrada en la mesa.
 * Los jugadores se distribuyen en el arco superior (de derecha a izquierda pasando por arriba).
 */
function positionPlayers() {
  const table = document.querySelector('.game-table');
  if (!table) return;
  const W = table.clientWidth;
  const H = table.clientHeight;
  if (!W || !H) return;

  // Centro y radios de la elipse (coincide con el ::after del CSS)
  const cx = W * 0.50;
  const cy = H * 0.43;
  const rx = W * 0.42;
  const ry = H * 0.35;

  const cards = Array.from(table.querySelectorAll('.player-card[data-pid]'));
  const N = cards.length;
  if (N === 0) return;

  // Arco superior: de ~210° a ~330° pasando por 270° (arriba en coords de pantalla)
  // Para N jugadores: spread proporcional, máx 280°
  const arcDeg = N === 1 ? 0 : Math.min(280, 100 + (N - 1) * 40);
  const startDeg = 270 - arcDeg / 2;

  cards.forEach((card, i) => {
    const deg = N === 1 ? 270 : startDeg + i * (arcDeg / (N - 1));
    const rad = deg * Math.PI / 180;
    // En coords de pantalla (y hacia abajo): sin(270°)=-1 → arriba ✓
    const x = cx + rx * Math.cos(rad);
    const y = cy + ry * Math.sin(rad);
    card.style.left = `${x}px`;
    card.style.top  = `${y}px`;
  });
}

window.addEventListener('resize', () => {
  if (S.phase === 'playing' || S.phase === 'reveal') positionPlayers();
});

/** Devuelve S.playerOrder empezando desde startId (inclusive), de forma circular. */
function turnOrderFrom(startId) {
  const idx = S.playerOrder.indexOf(startId);
  if (idx === -1) return [...S.playerOrder];
  const result = [];
  for (let i = 0; i < S.playerOrder.length; i++) {
    result.push(S.playerOrder[(idx + i) % S.playerOrder.length]);
  }
  return result;
}

const COLORS = ['#2e86ab','#a23b72','#f18f01','#c73e1d','#3b1f2b','#44bba4','#e94f37'];
function playerColor(pid) {
  let hash = 0;
  for (const c of pid) hash = (hash * 31 + c.charCodeAt(0)) & 0xffffffff;
  return COLORS[Math.abs(hash) % COLORS.length];
}

// ══════════════════════════════════  INIT  ════════════════════════════════════
// Init bid UI on load
refreshBidInputUI();
