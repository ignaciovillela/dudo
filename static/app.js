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

/**
 * Anima un dado saliendo (exit) o entrando (enter) desde/hacia el punto de los dados del jugador,
 * viajando hacia/desde el centro de la mesa.
 * @param {string} pid   id del jugador
 * @param {'exit'|'enter'} type
 */
function animateDieCup(pid, type) {
  const isMe = pid === S.playerId;
  let refEl;

  if (isMe) {
    // Para mí: usar my-dice-row como referencia
    refEl = document.querySelector('#my-dice-row');
  } else {
    // Para otros: usar la zona de dados perdidos (entre jugador y centro)
    const card = document.querySelector(`.player-card[data-pid="${pid}"]`);
    refEl = document.querySelector(`.player-lost-dice[data-for="${pid}"]`) ||
      card?.querySelector('.player-card-dice') || card;
  }
  if (!refEl) return;

  const rect = refEl.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  // Centro de la mesa
  const table = document.querySelector('.game-table');
  const tableRect = table ? table.getBoundingClientRect()
    : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  const tcx = tableRect.left + tableRect.width  / 2;
  const tcy = tableRect.top  + tableRect.height / 2;

  // Vector normalizado
  const dx = tcx - cx;
  const dy = tcy - cy;
  const dist = Math.hypot(dx, dy) || 1;
  const nx = dx / dist;
  const ny = dy / dist;

  const travel = Math.min(dist * 0.85, 260);

  const face = Math.ceil(Math.random() * 6);
  const size = isMe ? null : 'sm';
  const die = makeDie(face, { size });

  Object.assign(die.style, {
    position:      'fixed',
    left:          `${cx}px`,
    top:           `${cy}px`,
    margin:        '0',
    zIndex:        '9999',
    pointerEvents: 'none',
    transition:    'none',
  });

  document.body.appendChild(die);

  const tx = nx * travel;
  const ty = ny * travel;

  let keyframes, options;

  if (type === 'exit') {
    die.style.boxShadow = '0 0 14px rgba(192,57,43,0.85), 0 0 28px rgba(192,57,43,0.4)';
    keyframes = [
      { transform: 'translate(-50%, -50%) scale(0.55) rotate(0deg)',                                      opacity: 0.5, offset: 0    },
      { transform: `translate(calc(-50% + ${tx*0.18}px), calc(-50% + ${ty*0.18}px)) scale(1.15) rotate(-12deg)`, opacity: 1,   offset: 0.18 },
      { transform: `translate(calc(-50% + ${tx*0.6}px),  calc(-50% + ${ty*0.6}px))  scale(0.7)  rotate(28deg)`,  opacity: 0.7, offset: 0.6  },
      { transform: `translate(calc(-50% + ${tx}px),      calc(-50% + ${ty}px))       scale(0.05) rotate(65deg)`,  opacity: 0,   offset: 1    },
    ];
    options = { duration: 1320, easing: 'cubic-bezier(0.4, 0, 0.7, 1)', fill: 'forwards' };
  } else {
    die.style.boxShadow = '0 0 16px rgba(46,204,113,0.9), 0 0 32px rgba(46,204,113,0.5)';
    keyframes = [
      { transform: `translate(calc(-50% + ${tx}px),       calc(-50% + ${ty}px))       scale(0.08) rotate(-45deg)`, opacity: 0,   offset: 0    },
      { transform: `translate(calc(-50% + ${tx*0.35}px),  calc(-50% + ${ty*0.35}px))  scale(1.0)  rotate(10deg)`,  opacity: 1,   offset: 0.38 },
      { transform: `translate(calc(-50% + ${tx*0.05}px),  calc(-50% + ${ty*0.05}px))  scale(1.18) rotate(-5deg)`,  opacity: 1,   offset: 0.58 },
      { transform: 'translate(-50%, -50%) scale(0.7)  rotate(0deg)',                                       opacity: 0.8, offset: 0.80 },
      { transform: 'translate(-50%, -50%) scale(0.15) rotate(0deg)',                                       opacity: 0,   offset: 1    },
    ];
    options = { duration: 1220, easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)', fill: 'forwards' };
  }

  const anim = die.animate(keyframes, options);
  anim.onfinish = () => die.remove();
  setTimeout(() => { if (die.parentNode) die.remove(); }, 3600); // safety
}

// ══════════════════════════════════  STATE  ═══════════════════════════════════
const S = {
  ws:             null,
  playerId:       null,
  playerName:     '',
  playerAvatar:   '🎲',
  roomId:         '',
  hostId:         null,
  isHost:         false,
  isSpectator:    false,
  isReady:        false,
  rules:          null,

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
  lastActionPlayerId: null,
  lastActionType:     null, // 'dudo' | 'calzo'
  direction:           1,   // 1 = horario, -1 = antihorario
  roundFirstPlayer:    '',
  hasFirstAction:      false,

  // UI bid inputs
  bidQty:         1,
  bidFace:        2,

  // Reconnect
  manualClose:    false,
  reconnectTimer: null,
  reconnectAttempt: 0,
};

const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];
const BASE_TITLE = document.title || 'Dudo';
const TURN_ALERT_TITLE = '⚡ ¡TU TURNO! — Dudo';
const TURN_IDLE_TITLE = 'Dudo';

let titleBlinkTimer = null;
let titleBlinkState = false;
let notificationPrompted = false;
let turnCountdownTimer = null;
let turnCountdownDeadline = 0;

function requestTurnNotificationPermission() {
  if (notificationPrompted) return;
  notificationPrompted = true;
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

function startTurnTitleBlink() {
  if (titleBlinkTimer) return;
  titleBlinkState = false;
  titleBlinkTimer = setInterval(() => {
    titleBlinkState = !titleBlinkState;
    document.title = titleBlinkState ? TURN_ALERT_TITLE : TURN_IDLE_TITLE;
  }, 700);
}

function stopTurnTitleBlink() {
  if (titleBlinkTimer) {
    clearInterval(titleBlinkTimer);
    titleBlinkTimer = null;
  }
  document.title = BASE_TITLE;
}

function notifyTurnIfHidden() {
  if (!document.hidden) {
    stopTurnTitleBlink();
    return;
  }
  startTurnTitleBlink();
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  try {
    new Notification('¡Tu turno en Dudo!', { icon: '/static/favicon.svg' });
  } catch (_) {}
}

const DEFAULT_RULES = {
  elimination_mode: 'winner',
  allow_gavilan: true,
  calzo_recovers_on_turn: false,
  turn_timeout_seconds: 0,
};

const AVATAR_OPTIONS = [
  '🎲', '🦅', '🐺', '🦁', '🐯', '🦊', '💀', '👑', '🎭', '🃏',
  '🏹', '⚔️', '🛡️', '🌙', '⚡', '🔥', '💎', '🎯', '🍀', '🎪',
];

// ══════════════════════════════════  SOUND  ═══════════════════════════════════
const AUDIO_STORAGE_KEY = 'dudoMuted';
const RULES_STORAGE_KEY = 'dudoRules';

function saveRulesToStorage(rules) {
  try { localStorage.setItem(RULES_STORAGE_KEY, JSON.stringify(rules)); } catch (_) {}
}

function loadRulesFromStorage() {
  try {
    const raw = localStorage.getItem(RULES_STORAGE_KEY);
    return raw ? normalizeRules(JSON.parse(raw)) : null;
  } catch (_) { return null; }
}

// ── Sesión de sala ─────────────────────────────────────────────────────────────
const SESSION_STORAGE_KEY = 'dudoSession';

function saveSession() {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
      room: S.roomId,
      name: S.playerName,
      avatar: S.playerAvatar,
      playerId: S.playerId,
    }));
  } catch (_) {}
}

function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

function clearSession() {
  try { localStorage.removeItem(SESSION_STORAGE_KEY); } catch (_) {}
}
const AudioState = {
  ctx: null,
  muted: localStorage.getItem(AUDIO_STORAGE_KEY) === '1',
};

function ensureAudioCtx() {
  if (AudioState.ctx) return AudioState.ctx;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  AudioState.ctx = new AC();
  return AudioState.ctx;
}

function unlockAudio() {
  const ctx = ensureAudioCtx();
  if (!ctx) return;
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
}

function playTone(freq, duration = 0.08, opts = {}) {
  if (AudioState.muted) return;
  const ctx = ensureAudioCtx();
  if (!ctx) return;

  const when = ctx.currentTime + (opts.delay || 0);
  const gain = ctx.createGain();
  const osc = ctx.createOscillator();

  osc.type = opts.type || 'sine';
  osc.frequency.setValueAtTime(freq, when);

  const volume = opts.volume ?? 0.05;
  gain.gain.setValueAtTime(0.0001, when);
  gain.gain.exponentialRampToValueAtTime(volume, when + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, when + duration);

  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(when);
  osc.stop(when + duration + 0.02);
}

const SFX = {
  click() {
    playTone(620, 0.05, { type: 'square', volume: 0.03 });
  },
  bid() {
    playTone(420, 0.07, { type: 'triangle', volume: 0.045 });
    playTone(540, 0.08, { type: 'triangle', delay: 0.06, volume: 0.04 });
  },
  paso() {
    playTone(260, 0.12, { type: 'sine', volume: 0.04 });
  },
  yourTurn() {
    playTone(740, 0.08, { type: 'square', volume: 0.05 });
    playTone(980, 0.12, { type: 'square', delay: 0.09, volume: 0.045 });
  },
  reveal() {
    playTone(360, 0.09, { type: 'triangle', volume: 0.04 });
    playTone(280, 0.12, { type: 'triangle', delay: 0.08, volume: 0.035 });
  },
  win() {
    playTone(650, 0.1, { type: 'triangle', volume: 0.055 });
    playTone(860, 0.12, { type: 'triangle', delay: 0.1, volume: 0.05 });
    playTone(1080, 0.16, { type: 'triangle', delay: 0.2, volume: 0.045 });
  },
  lose() {
    playTone(420, 0.1, { type: 'sawtooth', volume: 0.045 });
    playTone(320, 0.16, { type: 'sawtooth', delay: 0.1, volume: 0.04 });
  },
  error() {
    playTone(220, 0.08, { type: 'sawtooth', volume: 0.045 });
    playTone(180, 0.12, { type: 'sawtooth', delay: 0.07, volume: 0.04 });
  },
};

function playSfx(name) {
  unlockAudio();
  const fx = SFX[name];
  if (fx) fx();
}

function updateSoundButton() {
  const btn = document.getElementById('btn-sound');
  if (!btn) return;
  btn.classList.toggle('muted', AudioState.muted);
  btn.innerHTML = AudioState.muted
    ? '<i class="fa-solid fa-volume-xmark" aria-hidden="true"></i>'
    : '<i class="fa-solid fa-volume-high" aria-hidden="true"></i>';
  btn.setAttribute('aria-pressed', AudioState.muted ? 'true' : 'false');
  const label = AudioState.muted ? 'Activar sonido' : 'Silenciar sonido';
  btn.title = label;
  btn.setAttribute('aria-label', label);
}

function toggleSound() {
  AudioState.muted = !AudioState.muted;
  localStorage.setItem(AUDIO_STORAGE_KEY, AudioState.muted ? '1' : '0');
  updateSoundButton();
  if (!AudioState.muted) playSfx('click');
}

// ══════════════════════════════════  WEBSOCKET  ════════════════════════════════
function connect(roomId) {
  S.manualClose = false;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  if (S.reconnectTimer) {
    clearTimeout(S.reconnectTimer);
    S.reconnectTimer = null;
  }
  S.ws = new WebSocket(`${proto}://${location.host}/ws/${roomId}`);

  S.ws.onopen = () => {
    if (S.reconnectAttempt > 0) {
      showToast('Reconectado');
    }
    hideReconnectBanner();
    S.reconnectAttempt = 0;
    log('Conectado al servidor', 'system');
  };
  S.ws.onclose = () => {
    log('Desconectado', 'system');
    if (!S.manualClose && S.roomId) {
      scheduleReconnect();
      return;
    }
    showToast('Conexión cerrada', true);
  };
  S.ws.onerror   = () => showToast('Error de conexión', true);
  S.ws.onmessage = (e) => handleMsg(JSON.parse(e.data));
}

function scheduleReconnect() {
  if (S.reconnectTimer) return;

  if (S.reconnectAttempt >= RECONNECT_DELAYS_MS.length) {
    showReconnectBanner('No se pudo reconectar. Recarga la pagina.', true);
    showToast('No se pudo reconectar', true);
    return;
  }

  const attempt = S.reconnectAttempt + 1;
  const delay = RECONNECT_DELAYS_MS[S.reconnectAttempt];
  S.reconnectAttempt = attempt;
  showReconnectBanner(`Reconectando... intento ${attempt}/${RECONNECT_DELAYS_MS.length}`);

  S.reconnectTimer = setTimeout(() => {
    S.reconnectTimer = null;
    connect(S.roomId);
  }, delay);
}

function showReconnectBanner(text, isError = false) {
  const el = document.getElementById('reconnect-banner');
  if (!el) return;
  el.textContent = text;
  el.classList.toggle('error', !!isError);
  el.style.display = 'block';
}

function hideReconnectBanner() {
  const el = document.getElementById('reconnect-banner');
  if (!el) return;
  el.style.display = 'none';
  el.classList.remove('error');
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
    reconnected:        onReconnected,
    player_joined:      onPlayerJoined,
    player_ready:       onPlayerReady,
    player_disconnected:onPlayerDisc,
    player_reconnected: onPlayerReconnected,
    host_changed:       onHostChanged,
    all_ready:          onAllReady,
    rules_updated:      onRulesUpdated,
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
    joined_spectator:   onJoinedSpectator,
    spectator_state:    onSpectatorState,
    spectator_joined:   onSpectatorJoined,
    spectator_left:     onSpectatorLeft,
    error:              onError,
  };
  const fn = H[msg.type];
  if (fn) fn(msg);
}

function onConnected(msg) {
  S.playerId = msg.player_id;
  S.roomId   = msg.room_id;
  // Enviar join con posible reconnect_id si la sala coincide
  const session = loadSession();
  if (session?.avatar && AVATAR_OPTIONS.includes(session.avatar)) {
    S.playerAvatar = session.avatar;
  }
  const reconnect_id = (session && session.room === S.roomId) ? session.playerId : null;
  send({ type: 'join', name: S.playerName, avatar: S.playerAvatar, reconnect_id });
}

function onJoined(msg) {
  S.isSpectator = false;
  S.hostId      = msg.host_id || msg.player_order?.[0] || null;
  S.isHost      = msg.is_host;
  S.players     = msg.players;
  S.playerOrder = msg.player_order;
  S.rules       = normalizeRules(msg.rules);
  S.playerAvatar = S.players[S.playerId]?.avatar || S.playerAvatar;
  saveSession();

  document.getElementById('disp-room-code').textContent = S.roomId;
  document.getElementById('lobby-form').style.display = 'none';
  document.getElementById('lobby-room').style.display = 'block';

  renderLobbyPlayers();

  if (S.isHost) {
    document.getElementById('btn-start').style.display = 'inline-flex';
    updateStartButton();
    // Restaurar reglas guardadas en localStorage y aplicarlas a la sala
    const saved = loadRulesFromStorage();
    if (saved) {
      S.rules = saved;
      send({ type: 'set_rules', rules: S.rules });
    }
  }
  renderLobbyRules();
  applySpectatorMode();
  log(`Unido a la sala ${S.roomId}`, 'system');
}

function onJoinedSpectator(msg) {
  S.isSpectator = true;
  S.phase = msg.phase || 'playing';
  S.hostId = msg.host_id || null;
  S.players = msg.players || {};
  S.playerOrder = msg.player_order || [];
  S.rules = normalizeRules(msg.rules || S.rules);
  S.roundNum = msg.round_number || 0;
  S.totalDice = msg.total_dice || 0;
  S.myDice = [];
  if (msg.turn) onTurn(msg.turn);
  showScreen('game');
  applySpectatorMode();
  renderOtherPlayers();
  renderMyDice();
  updateBidDisplay();
  document.getElementById('disp-round').textContent = S.roundNum;
  document.getElementById('disp-total').textContent = S.totalDice;
  log(`${msg.spectator_name || 'Espectador'} está observando la partida`, 'system');
}

function onSpectatorState(msg) {
  if (!S.isSpectator) return;
  S.phase = msg.phase || S.phase;
  S.players = msg.players || S.players;
  S.playerOrder = msg.player_order || S.playerOrder;
  S.rules = normalizeRules(msg.rules || S.rules);
  S.roundNum = msg.round_number || S.roundNum;
  S.totalDice = msg.total_dice || S.totalDice;
  if (msg.turn) onTurn(msg.turn);
  renderOtherPlayers();
  renderMyDice();
  updateBidDisplay();
  document.getElementById('disp-round').textContent = S.roundNum;
  document.getElementById('disp-total').textContent = S.totalDice;
}

function onSpectatorJoined(msg) {
  log(`${msg.spectator_name} se unió como espectador`, 'system');
}

function onSpectatorLeft(msg) {
  log(`${msg.spectator_name} dejó de observar`, 'system');
}

function onReconnected(msg) {
  // El backend reasignó el WS al player_id original
  S.isSpectator = false;
  S.playerId    = msg.player_id;
  S.hostId      = msg.host_id || msg.player_order?.[0] || null;
  S.isHost      = msg.is_host;
  S.players     = msg.players;
  S.playerOrder = msg.player_order;
  S.rules       = normalizeRules(msg.rules);
  S.phase       = msg.phase;
  S.playerAvatar = S.players[S.playerId]?.avatar || S.playerAvatar;
  saveSession();

  if (S.phase === 'lobby') {
    showScreen('lobby');
    document.getElementById('lobby-form').style.display = 'none';
    document.getElementById('lobby-room').style.display = 'block';
    document.getElementById('disp-room-code').textContent = S.roomId;
    const startBtn = document.getElementById('btn-start');
    if (startBtn) {
      startBtn.style.display = S.isHost ? 'inline-flex' : 'none';
    }
    renderLobbyPlayers();
    renderLobbyRules();
    updateStartButton();
    log('Reconectado al lobby', 'system');
    return;
  }

  showScreen('game');
  applySpectatorMode();
  renderOtherPlayers();
  updateBidDisplay();
  log('Reconectado a la partida en curso', 'system');
}

function onPlayerReconnected(msg) {
  if (S.players[msg.player_id]) {
    S.players[msg.player_id].connected = true;
  }
  renderOtherPlayers();
  renderLobbyPlayers();
  log(`${msg.player_name} se reconectó`, 'system');
}

function onHostChanged(msg) {
  S.hostId = msg.new_host_id || S.hostId;
  S.isHost = S.playerId === S.hostId;

  const startBtn = document.getElementById('btn-start');
  if (startBtn) {
    startBtn.style.display = S.isHost ? 'inline-flex' : 'none';
  }

  if (S.phase === 'lobby') {
    renderLobbyRules();
    updateStartButton();
    renderLobbyPlayers();
  }

  if (S.isHost) {
    showToast('Ahora eres el anfitrión');
  }
  log(`Nuevo anfitrión: ${msg.new_host_name}`, 'system');
}

function onAllReady() {
  if (S.isHost) showToast('¡Todos listos! Pulsa Iniciar Juego cuando quieras.');
  log('Todos los jugadores están listos', 'system');
}

function onRulesUpdated(msg) {
  S.rules = normalizeRules(msg.rules);
  // El backend reseteó ready de todos; sincronizamos localmente
  if (msg.players) {
    Object.assign(S.players, msg.players);
  }
  S.isReady = false;
  updateReadyButton(false);
  renderLobbyPlayers();
  updateStartButton();
  renderLobbyRules();
  log('Reglas actualizadas — estado listo reiniciado', 'system');
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
  updateStartButton();
}

function onPlayerDisc(msg) {
  if (S.players[msg.player_id])
    S.players[msg.player_id].connected = false;
  renderLobbyPlayers();
  renderOtherPlayers();
  log(`${msg.player_name} se desconectó`, 'system');
}

function onGameStarted(msg) {
  S.isSpectator = false;
  S.phase       = 'playing';
  S.playerOrder = msg.player_order;
  S.rules       = normalizeRules(msg.rules || S.rules);
  S.currentBid      = null;
  S.activePaso      = null;
  S.hasPassed       = false;
  S.revealDice      = {};
  S.revealBidFace   = null;
  S.lastActionPlayerId = null;
  S.lastActionType = null;
  S.direction         = 1;
  S.roundFirstPlayer  = '';
  S.hasFirstAction    = false;
  showScreen('game');
  applySpectatorMode();
  renderOtherPlayers();
  updateBidDisplay();
  // Limpiar log de partidas anteriores
  const logEl = document.getElementById('game-log');
  if (logEl) logEl.innerHTML = '';
  // Mostrar reglas activas al inicio del registro
  const rules = normalizeRules(S.rules);
  log('⚙ Reglas de esta partida:', 'system');
  const modeLabel = rules.elimination_mode === 'loser'
    ? 'Modo perdedor (termina al primer eliminado)'
    : 'Modo ganador (gana el último con dados)';
  log(`  • ${modeLabel}`, 'system');
  log(`  • Gavilán: ${rules.allow_gavilan ? 'activado' : 'desactivado'}`, 'system');
  log(`  • Calzo recupera en turno: ${rules.calzo_recovers_on_turn ? 'sí' : 'no'}`, 'system');
  log(`  • Tiempo por turno: ${rules.turn_timeout_seconds > 0 ? `${rules.turn_timeout_seconds}s` : 'sin límite'}`, 'system');
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
  if (S.playerAvatar) {
    document.getElementById('my-name-disp').textContent = `${S.playerAvatar} ${S.playerName}`;
  }
}

function onTurn(msg) {
  S.currentPid       = msg.player_id;
  S.currentBid       = msg.current_bid;
  S.activePaso       = msg.active_paso || null;
  S.direction        = msg.direction ?? 1;
  S.roundFirstPlayer = msg.round_first_player ?? '';
  S.hasFirstAction   = msg.has_first_action ?? false;
  S.phase            = 'playing';

  const timeoutSeconds = Number(msg.turn_timeout_seconds || 0);
  if (timeoutSeconds > 0) {
    startTurnCountdown(timeoutSeconds);
  } else {
    stopTurnCountdown();
  }

  const isMe = S.currentPid === S.playerId;
  const name = S.players[S.currentPid]?.name || msg.player_name;

  const banner  = document.getElementById('turn-banner');
  const myArea  = document.querySelector('.my-area');
  const bidPanel = document.getElementById('bid-panel');

  banner.textContent = isMe ? '¡Tu turno!' : `Turno de ${name}`;

  if (isMe && !S.isSpectator) {
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

  if (isMe && !S.isSpectator) {
    playSfx('yourTurn');
    resetBidInputs();
    notifyTurnIfHidden();
  } else {
    stopTurnTitleBlink();
  }
}

function onBidMade(msg) {
  playSfx('bid');
  S.currentBid = msg.bid;
  S.activePaso = null;  // la apuesta reemplaza al paso como acción activa
  const b = msg.bid;
  const name = S.players[b.player_id]?.name || b.player_name;
  log(`${name}: ${b.quantity} × ${faceName(b.face)}`, 'bid');
  updateBidDisplay();
  updateControls();
}

function onPasoMade(msg) {
  playSfx('paso');
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
  playSfx('reveal');
  stopTurnCountdown();
  S.phase = 'reveal';
  if (msg.action === 'dudo' || msg.action === 'calzo') {
    S.lastActionPlayerId = msg.challenger_id || null;
    S.lastActionType = msg.action;
  } else {
    S.lastActionPlayerId = null;
    S.lastActionType = null;
  }
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
  // Animar dado saliendo del cacho (pérdida)
  if (msg.loser_id) setTimeout(() => animateDieCup(msg.loser_id, 'exit'), 400);
  // Actualizar conteo y animar dado entrando al cacho (recuperación)
  if (msg.challenger_gained && msg.challenger_id) {
    if (S.players[msg.challenger_id]) {
      S.players[msg.challenger_id].dice_count += 1;
      renderOtherPlayers();
      if (msg.challenger_id === S.playerId) {
        renderMyDice();
      }
    }
    setTimeout(() => animateDieCup(msg.challenger_id, 'enter'), 750);
  }

  const bid = msg.bid || null;
  const face = bid?.face;
  const isCalzo = msg.action === 'calzo';

  let resultText, resultClass;
  if (msg.action === 'paso') {
    const gavilan = msg.is_gavilan;
    if (msg.paso_valid) {
      if (gavilan) {
        resultText = `Gavilán fallido: ${msg.challenger_name} dudó el paso de ${msg.passer_name}. Paso válido → ${msg.challenger_name} pierde un dado.`;
      } else {
        resultText = `${msg.challenger_name} dudó el paso de ${msg.passer_name}. Paso válido → ${msg.challenger_name} pierde un dado.`;
      }
      resultClass = 'lose';
    } else {
      const gainText = msg.challenger_gained ? ' ¡Recupera un dado!' : '';
      if (gavilan) {
        resultText = `¡Gavilán! ${msg.challenger_name} dudó el paso de ${msg.passer_name}. Paso inválido → ${msg.passer_name} pierde un dado.${gainText}`;
      } else {
        resultText = `${msg.challenger_name} dudó el paso de ${msg.passer_name}. Paso inválido → ${msg.passer_name} pierde un dado.`;
      }
      resultClass = 'win';
    }
  } else if (isCalzo) {
    if (msg.calzo_success) {
      const gainText = msg.challenger_gained
        ? `${msg.challenger_name} recupera un dado.`
        : 'La ronda se reinicia.';
      resultText = `${msg.challenger_name} calzó. ¡Exactamente ${msg.actual_count} ${faceName(face)}! ${gainText}`;
      resultClass = 'win';
    } else {
      resultText = `${msg.challenger_name} calzó. Había ${msg.actual_count}, no ${bid.quantity} ${faceName(face)} → ${msg.challenger_name} pierde un dado.`;
      resultClass = 'lose';
    }
  } else {
    if (msg.bid_holds) {
      resultText = `${msg.challenger_name} dudó. ¡La apuesta se sostiene! Hay ${msg.actual_count} ${faceName(face)} → ${msg.challenger_name} pierde un dado.`;
      resultClass = 'lose';
    } else {
      resultText = `${msg.challenger_name} dudó. Solo hay ${msg.actual_count} ${faceName(face)} → ${S.players[bid.player_id]?.name || bid.player_name} pierde un dado.`;
      resultClass = 'win';
    }
  }

  document.getElementById('reveal-result').textContent = resultText;
  document.getElementById('reveal-result').className = `reveal-result ${resultClass}`;

  log(resultText, resultClass);

  if (resultClass === 'win') playSfx('win');
  if (resultClass === 'lose') playSfx('lose');

  startRevealCountdown(7);
}

function onNewRound(msg) {
  stopTurnCountdown();
  S.roundNum      = msg.round_number;
  S.currentBid       = null;
  S.activePaso       = null;
  S.hasPassed        = false;
  S.revealDice       = {};
  S.revealBidFace    = null;
  S.lastActionPlayerId = null;
  S.lastActionType = null;
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
  stopTurnCountdown();
  S.phase = 'game_over';
  const isLoserMode = msg.result_mode === 'loser';
  const titleText = isLoserMode
    ? `═══ ${msg.loser_name} PERDIÓ ═══`
    : `═══ ${msg.winner_name} GANÓ ═══`;
  log(titleText, isLoserMode ? 'lose' : 'win');

  const isWinner = !isLoserMode && msg.winner_id === S.playerId;
  const isLoser = isLoserMode && msg.loser_id === S.playerId;

  // Preparar el overlay ya, pero mostrarlo al terminar el countdown de reveal (7 s)
  const overlay = document.getElementById('game-over-overlay');
  if (isLoserMode) {
    document.getElementById('go-title').textContent = isLoser ? 'Perdiste' : 'Fin de la partida';
    document.getElementById('go-winner').textContent = `${msg.loser_name} quedó como perdedor`;
  } else {
    document.getElementById('go-title').textContent = isWinner ? '¡Ganaste!' : 'Fin de la partida';
    document.getElementById('go-winner').textContent = `${msg.winner_name} es el ganador`;
  }

  setTimeout(() => {
    hideReveal();
    const endSfx = isLoserMode ? (isLoser ? 'lose' : 'win') : (isWinner ? 'win' : 'lose');
    playSfx(endSfx);
    overlay.style.display = 'flex';
  }, 7000);
}

function closeGameOver() {
  stopTurnCountdown();
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
  applySpectatorMode();
  updateReadyButton(false);
  document.getElementById('btn-ready').classList.remove('btn-start');
}

function onError(msg) {
  playSfx('error');
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

function animateDieGain(pid) {
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
  // Animar el último dado (el recién recuperado)
  const target = dice[dice.length - 1];
  target.classList.add('die-gained');
  target.addEventListener('animationend', () => target.classList.remove('die-gained'), { once: true });
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

function stopTurnCountdown() {
  if (turnCountdownTimer) {
    clearInterval(turnCountdownTimer);
    turnCountdownTimer = null;
  }
  const el = document.getElementById('turn-countdown');
  if (!el) return;
  el.style.display = 'none';
  el.textContent = '';
}

function startTurnCountdown(seconds) {
  stopTurnCountdown();
  const el = document.getElementById('turn-countdown');
  if (!el) return;
  turnCountdownDeadline = Date.now() + (seconds * 1000);
  const render = () => {
    const left = Math.max(0, Math.ceil((turnCountdownDeadline - Date.now()) / 1000));
    if (left <= 0 || S.phase !== 'playing') {
      stopTurnCountdown();
      return;
    }
    el.textContent = `⏳ ${left}s`;
    el.style.display = 'inline-flex';
  };
  render();
  turnCountdownTimer = setInterval(render, 250);
}

// ══════════════════════════════════  RENDER  ══════════════════════════════════
function renderLobbyPlayers() {
  const list = document.getElementById('lobby-player-list');
  list.innerHTML = '';
  const hostId = S.hostId || S.playerOrder[0];
  for (const pid of S.playerOrder) {
    const p = S.players[pid];
    if (!p) continue;
    const row = document.createElement('div');
    row.className = 'lobby-player-row' + (hostId === pid ? ' is-host' : '');

    const av = document.createElement('div');
    av.className = 'player-avatar';
    av.textContent = p.avatar || '🎲';
    av.style.background = playerColor(pid);

    const name = document.createElement('div');
    name.className = 'player-pname';
    name.textContent = p.name;

    const badge = document.createElement('div');
    badge.className = 'ready-badge' + (p.ready ? ' ready' : '');
    badge.innerHTML = p.ready
      ? '<i class="fa-solid fa-check" aria-hidden="true"></i> Listo'
      : '<i class="fa-regular fa-clock" aria-hidden="true"></i> Esperando';

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
    const actionType = pid === S.lastActionPlayerId ? S.lastActionType : null;
    card.className = 'player-card' +
      (pid === S.currentPid ? ' active-player' : '') +
      (actionType ? ` action-actor action-${actionType}` : '') +
      (p.dice_count <= 0 ? ' eliminated' : '');
    card.dataset.pid = pid;

    const nameEl = document.createElement('div');
    nameEl.className = 'player-card-name';
    nameEl.textContent = `${p.avatar || '🎲'} ${p.name}`;

    const actionBadge = actionType ? document.createElement('div') : null;
    if (actionBadge) {
      actionBadge.className = `player-action-badge action-${actionType}`;
      actionBadge.textContent = actionType === 'dudo' ? '🎲 ¡DUDO!' : '🔒 ¡CALZO!';
    }

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
    card.appendChild(diceRow);
    if (actionBadge) card.appendChild(actionBadge);
    container.appendChild(card);

    // Dados perdidos del oponente, colocados entre su carta y el centro de la mesa
    const lostWrap = document.createElement('div');
    lostWrap.className = 'player-lost-dice';
    lostWrap.dataset.for = pid;
    const lostCount = Math.max(0, 5 - (p.dice_count || 0));
    if (lostCount > 0) {
      lostWrap.appendChild(buildDiceRows(lostCount, { size: 'sm' }));
    }
    container.appendChild(lostWrap);
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

  // Mostrar dados perdidos fuera del my-area, entre éste y el centro
  const totalDice = 5;
  const lostCount = totalDice - S.myDice.length;
  const lostDiceEl = document.getElementById('my-lost-dice');
  lostDiceEl.innerHTML = '';
  if (lostCount > 0) {
    lostDiceEl.appendChild(buildDiceRows(lostCount, { size: 'sm' }));
  }
}

function updateBidDisplay() {
  const noMsg    = document.getElementById('no-bid-msg');
  const visual   = document.getElementById('bid-visual');
  const pasoEl   = document.getElementById('paso-indicator');

  // Paso indicator
  if (S.activePaso) {
    const name = S.players[S.activePaso.player_id]?.name || S.activePaso.player_name;
    pasoEl.innerHTML = `<i class="fa-solid fa-forward" aria-hidden="true"></i> PASO de ${name}`;
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
    ind.innerHTML = S.direction === 1
      ? '<i class="fa-solid fa-rotate-right" aria-hidden="true"></i>'
      : '<i class="fa-solid fa-rotate-left" aria-hidden="true"></i>';
    ind.title = S.direction === 1 ? 'Sentido horario' : 'Sentido antihorario';
    ind.style.display = 'inline-flex';
  }
}

function updateControls() {
  if (S.isSpectator) {
    hideControls();
    document.getElementById('bid-panel').style.opacity = '0.45';
    document.getElementById('wait-msg').style.display = 'block';
    document.getElementById('wait-msg').textContent = 'Modo espectador: solo observas.';
    return;
  }

  const isMyTurn      = S.currentPid === S.playerId && S.phase === 'playing';
  const playing       = S.phase === 'playing';
  const amEliminated  = (S.players[S.playerId]?.dice_count ?? 1) <= 0;
  const hasActivePaso = S.activePaso != null;
  const myOwnPaso     = S.activePaso?.player_id === S.playerId;
  const hasBid        = S.currentBid != null;
  const myOwnBid      = S.currentBid?.player_id === S.playerId;

  // Gavilán habilita acciones fuera de turno (dudo/calzo).
  const canOutOfTurn = !!S.rules?.allow_gavilan;

  // Dudo: disponible si hay acción activa (paso o apuesta) que no sea propia y no estoy eliminado
  const canDudo = playing && !amEliminated && (
    (hasActivePaso && !myOwnPaso && (isMyTurn || canOutOfTurn)) ||
    (!hasActivePaso && hasBid && !myOwnBid && (isMyTurn || canOutOfTurn))
  );
  // Calzo: solo si la acción activa es una apuesta (no paso) y no estoy eliminado
  const canCalzo = playing && !amEliminated && !hasActivePaso && hasBid && !myOwnBid && (isMyTurn || canOutOfTurn);
  // Paso: solo en mi turno y si no he pasado esta ronda
  const canPaso = isMyTurn && !S.hasPassed;

  document.getElementById('bid-panel').style.opacity  = isMyTurn ? '1' : '0.5';
  document.getElementById('btn-bid').disabled          = !isMyTurn;
  document.getElementById('btn-paso').disabled         = !canPaso;
  document.getElementById('btn-dudo').disabled         = !canDudo;
  document.getElementById('btn-calzo').disabled        = !canCalzo;
  document.getElementById('wait-msg').style.display   = isMyTurn ? 'none' : 'block';
  document.getElementById('wait-msg').textContent = 'Esperando tu turno…';

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
  if (S.isSpectator) return;
  playSfx('click');
  send({ type: 'bid', quantity: S.bidQty, face: S.bidFace });
}

function sendDirection(value) {
  if (S.isSpectator) return;
  playSfx('click');
  send({ type: 'direction', value });
}

function sendPaso() {
  if (S.isSpectator) return;
  playSfx('click');
  send({ type: 'paso' });
}

function sendDudo() {
  if (S.isSpectator) return;
  playSfx('click');
  send({ type: 'dudo' });
}

function sendCalzo() {
  if (S.isSpectator) return;
  playSfx('click');
  send({ type: 'calzo' });
}

function applySpectatorMode() {
  const badge = document.getElementById('spectator-badge');
  const sidebar = document.querySelector('.sidebar');
  const myArea = document.querySelector('.my-area');
  const myLost = document.getElementById('my-lost-dice');
  if (badge) badge.style.display = S.isSpectator ? 'inline-flex' : 'none';
  sidebar?.classList.toggle('spectator-mode', S.isSpectator);
  if (myArea) myArea.style.display = S.isSpectator ? 'none' : 'flex';
  if (myLost) myLost.style.display = S.isSpectator ? 'none' : '';
}

// ══════════════════════════════════  LOBBY ACTIONS  ════════════════════════════
function joinRoom() {
  const name = document.getElementById('inp-name').value.trim();
  const room = document.getElementById('inp-room').value.trim();
  const avatar = document.getElementById('inp-avatar')?.value || '🎲';
  if (!name) { showToast('Ingresa tu nombre', true); return; }
  if (!room) { showToast('Ingresa el código de sala', true); return; }
  S.playerName = name;
  S.playerAvatar = AVATAR_OPTIONS.includes(avatar) ? avatar : '🎲';
  S.roomId = room;
  // Guardar nombre inmediatamente, antes de conectar
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
      ...loadSession(),
      name,
      avatar: S.playerAvatar,
    }));
  } catch (_) {}
  playSfx('click');
  connect(room);
}

function toggleReady() {
  S.isReady = !S.isReady;
  updateReadyButton(S.isReady);
  playSfx('click');
  send({ type: 'ready' });
  if (S.isHost) renderLobbyRules(); // bloquea/desbloquea controles de reglas
}

function updateReadyButton(isReady) {
  const btn = document.getElementById('btn-ready');
  if (!btn) return;
  btn.innerHTML = isReady
    ? '<i class="fa-solid fa-ban" aria-hidden="true"></i><span>Cancelar</span>'
    : '<i class="fa-solid fa-circle-check" aria-hidden="true"></i><span>¡Listo!</span>';
}

function updateStartButton() {
  const btn = document.getElementById('btn-start');
  if (!btn) return;
  const connected = Object.values(S.players).filter(p => p.connected);
  const allReady = connected.length >= 2 && connected.every(p => p.ready);
  btn.disabled = !allReady;
}

function startGame() {
  playSfx('click');
  send({ type: 'start' });
}

function normalizeRules(rules) {
  const src = (rules && typeof rules === 'object') ? rules : {};
  const mode = src.elimination_mode === 'loser' ? 'loser' : 'winner';
  const timeoutRaw = Number(src.turn_timeout_seconds ?? DEFAULT_RULES.turn_timeout_seconds);
  const timeout = [0, 30, 60, 90].includes(timeoutRaw) ? timeoutRaw : DEFAULT_RULES.turn_timeout_seconds;
  return {
    elimination_mode: mode,
    allow_gavilan: !!(src.allow_gavilan ?? DEFAULT_RULES.allow_gavilan),
    calzo_recovers_on_turn: !!(src.calzo_recovers_on_turn ?? DEFAULT_RULES.calzo_recovers_on_turn),
    turn_timeout_seconds: timeout,
  };
}

function rulesSummaryItems() {
  const rules = normalizeRules(S.rules);
  return [
    {
      label: `Modo de partida: ${rules.elimination_mode === 'loser' ? 'Perdedor' : 'Ganador'}`,
      detail: 'Modo perdedor: termina cuando alguien pierde todos sus dados.\nModo ganador: gana el ultimo jugador con dados.',
    },
    {
      label: `Permitir Gavilan: ${rules.allow_gavilan ? 'Si' : 'No'}`,
      detail: rules.allow_gavilan
        ? 'Permite dudar o calzar fuera de turno.'
        : 'Solo puedes dudar o calzar en tu turno.',
    },
    {
      label: `Calzo recupera en mi turno: ${rules.calzo_recovers_on_turn ? 'Si' : 'No'}`,
      detail: rules.calzo_recovers_on_turn
        ? 'Un calzo correcto recupera dado incluso en tu turno.'
        : 'Un calzo correcto solo recupera dado fuera de turno.',
    },
    {
      label: `Tiempo por turno: ${rules.turn_timeout_seconds > 0 ? `${rules.turn_timeout_seconds}s` : 'Sin limite'}`,
      detail: 'Al expirar el tiempo, el servidor ejecuta una accion automatica conservadora.',
    },
  ];
}

function renderLobbyRules() {
  const hostControls = document.getElementById('host-rules-controls');
  const summary = document.getElementById('rules-summary');
  if (!hostControls || !summary) return;

  const rules = normalizeRules(S.rules);
  S.rules = rules;
  const hostCanEdit = S.isHost && !S.isReady;
  hostControls.style.display = S.isHost ? 'grid' : 'none';

  const modeEl = document.getElementById('rule-elimination-loser');
  const gavilanEl = document.getElementById('rule-allow-gavilan');
  const calzoEl = document.getElementById('rule-calzo-on-turn');
  const timeoutEl = document.getElementById('rule-turn-timeout');
  if (modeEl)    { modeEl.checked = rules.elimination_mode === 'loser'; modeEl.disabled = !hostCanEdit; }
  if (gavilanEl) { gavilanEl.checked = rules.allow_gavilan;             gavilanEl.disabled = !hostCanEdit; }
  if (calzoEl)   { calzoEl.checked = rules.calzo_recovers_on_turn;     calzoEl.disabled = !hostCanEdit; }
  if (timeoutEl) { timeoutEl.value = String(rules.turn_timeout_seconds); timeoutEl.disabled = !hostCanEdit; }

  // Opacidad reducida cuando el anfitrión no puede editar
  hostControls.style.opacity = hostCanEdit ? '1' : '0.45';
  hostControls.style.pointerEvents = hostCanEdit ? '' : 'none';

  summary.innerHTML = '';
  for (const item of rulesSummaryItems()) {
    const li = document.createElement('li');
    li.textContent = item.label;
    const help = document.createElement('button');
    help.type = 'button';
    help.className = 'rule-help';
    help.innerHTML = '<i class="fa-regular fa-circle-question" aria-hidden="true"></i>';
    help.setAttribute('data-tooltip', item.detail);
    help.setAttribute('aria-label', `Detalle: ${item.label}`);
    li.appendChild(document.createTextNode(' '));
    li.appendChild(help);
    summary.appendChild(li);
  }
}

function onHostRulesChanged() {
  if (!S.isHost) return;
  const next = {
    elimination_mode: document.getElementById('rule-elimination-loser')?.checked ? 'loser' : 'winner',
    allow_gavilan: !!document.getElementById('rule-allow-gavilan')?.checked,
    calzo_recovers_on_turn: !!document.getElementById('rule-calzo-on-turn')?.checked,
    turn_timeout_seconds: Number(document.getElementById('rule-turn-timeout')?.value || 0),
  };
  S.rules = normalizeRules(next);
  saveRulesToStorage(S.rules);
  renderLobbyRules();
  send({ type: 'set_rules', rules: S.rules });
}

function copyRoomCode() {
  playSfx('click');
  const shareUrl = `${location.origin}/?sala=${encodeURIComponent(S.roomId)}`;
  navigator.clipboard.writeText(shareUrl)
    .then(() => showToast('Enlace de sala copiado'))
    .catch(() => showToast(shareUrl));
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

    const pid = card.dataset.pid;
    const lost = table.querySelector(`.player-lost-dice[data-for="${pid}"]`);
    if (!lost) return;
    // Interpolar hacia el centro para que quede entre la carta y la mesa
    const t = 0.34;
    const lx = x + (cx - x) * t;
    const ly = y + (cy - y) * t;
    lost.style.left = `${lx}px`;
    lost.style.top = `${ly}px`;
  });
}

window.addEventListener('resize', () => {
  if (S.phase === 'playing' || S.phase === 'reveal') positionPlayers();
});

/** Devuelve S.playerOrder empezando desde startId (inclusive), de forma circular,
 *  respetando S.direction (1 = horario, -1 = antihorario). */
function turnOrderFrom(startId) {
  const idx = S.playerOrder.indexOf(startId);
  if (idx === -1) return [...S.playerOrder];
  const n   = S.playerOrder.length;
  const dir = S.direction ?? 1;
  const result = [];
  for (let i = 0; i < n; i++) {
    result.push(S.playerOrder[((idx + i * dir) % n + n) % n]);
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
updateSoundButton();
window.toggleSound = toggleSound;
window.onHostRulesChanged = onHostRulesChanged;

// Pre-rellenar formulario con la sesión guardada y guardar nombre en tiempo real
(function () {
  const session = loadSession();
  const roomFromUrl = new URLSearchParams(window.location.search).get('sala');
  const nameEl = document.getElementById('inp-name');
  const roomEl = document.getElementById('inp-room');
  const avatarEl = document.getElementById('inp-avatar');
  if (nameEl && session?.name) nameEl.value = session.name;
  if (roomEl) {
    roomEl.value = roomFromUrl || session?.room || '';
  }
  if (avatarEl && session?.avatar && AVATAR_OPTIONS.includes(session.avatar)) {
    avatarEl.value = session.avatar;
    S.playerAvatar = session.avatar;
  }

  // Guardar nombre en tiempo real al escribir
  if (nameEl) {
    nameEl.addEventListener('input', () => {
      const name = nameEl.value.trim();
      if (!name) return;
      try {
        localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
          ...loadSession(),
          name,
          avatar: avatarEl?.value || S.playerAvatar || '🎲',
        }));
      } catch (_) {}
    });
  }

  if (avatarEl) {
    avatarEl.addEventListener('change', () => {
      const avatar = AVATAR_OPTIONS.includes(avatarEl.value) ? avatarEl.value : '🎲';
      S.playerAvatar = avatar;
      try {
        localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
          ...loadSession(),
          name: nameEl?.value?.trim() || session?.name || '',
          avatar,
        }));
      } catch (_) {}
    });
  }
})();

// Desbloquea audio en la primera interacción del usuario (requisito del navegador).
['pointerdown', 'keydown'].forEach(evt => {
  window.addEventListener(evt, unlockAudio, { once: true });
  window.addEventListener(evt, requestTurnNotificationPermission, { once: true });
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) stopTurnTitleBlink();
});

window.addEventListener('focus', stopTurnTitleBlink);

window.addEventListener('beforeunload', () => {
  stopTurnTitleBlink();
  S.manualClose = true;
  if (S.ws && S.ws.readyState === WebSocket.OPEN) {
    S.ws.close();
  }
});

