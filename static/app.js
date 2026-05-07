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
    : { left: 0, top: 0, width: 1280, height: 800 };
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
      { transform: 'translate(-50%, -50%) scale(0.55) rotate(0deg)',                                      opacity: 0.5, filter: 'hue-rotate(0deg) saturate(1)', offset: 0    },
      { transform: `translate(calc(-50% + ${tx*0.18}px), calc(-50% + ${ty*0.18}px)) scale(1.15) rotate(-12deg)`, opacity: 1,   filter: 'hue-rotate(-10deg) saturate(1.2)', offset: 0.18 },
      { transform: `translate(calc(-50% + ${tx*0.6}px),  calc(-50% + ${ty*0.6}px))  scale(0.7)  rotate(28deg)`,  opacity: 0.7, filter: 'hue-rotate(-35deg) saturate(1.6)', offset: 0.6  },
      { transform: `translate(calc(-50% + ${tx}px),      calc(-50% + ${ty}px))       scale(0.05) rotate(65deg)`,  opacity: 0,   filter: 'hue-rotate(-55deg) saturate(2)', offset: 1    },
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
  lastLossPlayerId:    null,
  pendingStats: {
    dudoOk: 0,
    dudoFail: 0,
    calzoOk: 0,
    calzoFail: 0,
  },
  // Streaks: rondas consecutivas sobrevividas (sin perder dados)
  streaks: {},        // pid → current streak count
  bestStreaks: {},     // pid → best streak this game

  // UI bid inputs
  bidQty:         1,
  bidFace:        2,

  // Reconnect
  manualClose:    false,
  reconnectTimer: null,
  reconnectAttempt: 0,
  pendingKickTargetId: null,
  pendingKickTargetName: '',
  gameOverTimer: null,
  spectatorCount: 0,
};

const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];
const BASE_TITLE = document.title || 'Dudo';
const TURN_ALERT_TITLE = '⚡ ¡TU TURNO! — Dudo';
const TURN_IDLE_TITLE = 'Dudo';

let titleBlinkTimer = null;
let titleBlinkState = false;
let notificationPrompted = false;
let turnCountdownTimer = null;
let _activeNotification = null;
let turnCountdownDeadline = 0;

const NOTIF_PREF_STORAGE_KEY = 'dudoNotifPref';

function loadNotificationPref() {
  try { return localStorage.getItem(NOTIF_PREF_STORAGE_KEY) || ''; } catch (_) { return ''; }
}

function saveNotificationPref(value) {
  try { localStorage.setItem(NOTIF_PREF_STORAGE_KEY, value); } catch (_) {}
}

async function requestTurnNotificationPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    try {
      await Notification.requestPermission();
    } catch (_) {}
  }
  updateNotificationButton();
}

function updateNotificationButton() {
  const btn = document.getElementById('btn-notif');
  if (!btn) return;
  if (!('Notification' in window)) {
    btn.style.display = 'none';
    return;
  }
  const pref = loadNotificationPref();
  const show = Notification.permission !== 'granted' && (pref === 'rejected' || Notification.permission === 'denied');
  btn.style.display = show ? 'inline-flex' : 'none';
}

function openNotificationModal() {
  if (!('Notification' in window)) return;
  const modal = document.getElementById('notif-modal');
  if (modal) modal.style.display = 'flex';
}

function closeNotificationModal() {
  const modal = document.getElementById('notif-modal');
  if (modal) modal.style.display = 'none';
}

function acceptNotificationPrompt() {
  saveNotificationPref('accepted');
  closeNotificationModal();
  requestTurnNotificationPermission();
}

function rejectNotificationPrompt() {
  saveNotificationPref('rejected');
  closeNotificationModal();
  updateNotificationButton();
}

function maybeShowNotificationIntro() {
  if (notificationPrompted) return;
  notificationPrompted = true;
  if (!('Notification' in window)) return;
  if (Notification.permission === 'granted') return;
  const pref = loadNotificationPref();
  if (pref === 'accepted') {
    requestTurnNotificationPermission();
    return;
  }
  if (pref === 'rejected') {
    updateNotificationButton();
    return;
  }
  openNotificationModal();
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
    if (_activeNotification) { _activeNotification.close(); }
    const n = new Notification('¡Tu turno en Dudo!', { icon: '/static/favicon.svg' });
    n.onclick = () => { window.focus(); n.close(); _activeNotification = null; };
    _activeNotification = n;
  } catch (_) {}
}

const DEFAULT_RULES = {
  elimination_mode: 'winner',
  allow_gavilan: true,
  calzo_recovers_on_turn: false,
  turn_timeout_seconds: 0,
  allow_throwable_emojis: true,
};

// ══════════════════════════════════  LEVELS  ══════════════════════════════════
// Emojis ordered from "boring" to "exciting", each unlocked at a given level.
const AVATAR_LEVEL_MAP = [
  { emoji: '🎲', level: 1 },
  { emoji: '🃏', level: 1 },
  { emoji: '😏', level: 1 },

  { emoji: '🎭', level: 2 },
  { emoji: '🌚', level: 2 },

  { emoji: '🦊', level: 3 },
  { emoji: '🐍', level: 3 },

  { emoji: '🐺', level: 4 },
  { emoji: '🔥', level: 4 },

  { emoji: '🦁', level: 5 },
  { emoji: '⚔️', level: 5 },

  { emoji: '🍀', level: 6 },
  { emoji: '💎', level: 6 },

  { emoji: '🦂', level: 7 },
  { emoji: '👁️', level: 7 },

  { emoji: '👑', level: 8 },
  { emoji: '☠️', level: 8 },

  { emoji: '💀', level: 9 },
  { emoji: '👹', level: 9 },

  { emoji: '🜏', level: 10 },
];
const AVATAR_OPTIONS = AVATAR_LEVEL_MAP.map(e => e.emoji);

// XP thresholds per level (index = level - 1). Level 1 starts at 0 XP.
const LEVEL_XP_THRESHOLDS = [
  0,    // level 1
  50,   // level 2
  120,  // level 3
  210,  // level 4
  320,  // level 5
  450,  // level 6
  600,  // level 7
  780,  // level 8
  990,  // level 9
  1230, // level 10
];
const MAX_LEVEL = LEVEL_XP_THRESHOLDS.length;

const LEVEL_STORAGE_KEY = 'dudoLevel';

const EMPTY_LEVEL_DATA = { xp: 0, level: 1 };

function loadLevelData() {
  try {
    const raw = localStorage.getItem(LEVEL_STORAGE_KEY);
    return raw ? { ...EMPTY_LEVEL_DATA, ...JSON.parse(raw) } : { ...EMPTY_LEVEL_DATA };
  } catch (_) { return { ...EMPTY_LEVEL_DATA }; }
}

function saveLevelData(data) {
  try { localStorage.setItem(LEVEL_STORAGE_KEY, JSON.stringify(data)); } catch (_) {}
}

function xpToLevel(xp) {
  let level = 1;
  for (let i = LEVEL_XP_THRESHOLDS.length - 1; i >= 0; i--) {
    if (xp >= LEVEL_XP_THRESHOLDS[i]) { level = i + 1; break; }
  }
  return Math.min(level, MAX_LEVEL);
}

function xpForNextLevel(level) {
  if (level >= MAX_LEVEL) return null;
  return LEVEL_XP_THRESHOLDS[level]; // index = level (next level threshold)
}

function isAvatarUnlocked(emoji) {
  const entry = AVATAR_LEVEL_MAP.find(e => e.emoji === emoji);
  if (!entry) return false;
  const { level } = loadLevelData();
  return level >= entry.level;
}

/**
 * Add XP immediately and persist it. Returns { xpGained, oldLevel, newLevel, newXp, unlockedEmojis }.
 * Safe to call multiple times during a game — each call commits to localStorage right away.
 */
function addXp(amount) {
  if (amount === 0) return null;
  const data = loadLevelData();
  const oldLevel = data.level;
  const newXp = data.xp + amount;
  const newLevel = xpToLevel(newXp);
  saveLevelData({ xp: newXp, level: newLevel });
  const unlockedEmojis = AVATAR_LEVEL_MAP
    .filter(e => e.level > oldLevel && e.level <= newLevel)
    .map(e => e.emoji);
  return { xpGained: amount, oldLevel, newLevel, newXp, unlockedEmojis };
}

/**
 * Called on reveal: award XP for dudo/calzo outcome immediately.
 * Always grants at least 1 XP — actions that fail give less, never negative.
 *   dudo/calzo correcto: +5 XP
 *   dudo/calzo fallado:  +1 XP
 */
function awardActionXp(action, success) {
  const xp = success ? 5 : 1;
  return addXp(xp);
}

/**
 * Called on new_round: award a small XP bonus for surviving the round.
 */
function awardRoundXp() {
  return addXp(1);
}

/**
 * Called on game_over: award base XP + win bonus.
 * Action XP was already saved during reveals, so we only add the game-completion portion.
 * Returns { xpGained, oldLevel, newLevel, newXp, unlockedEmojis }.
 */
function awardGameOverXp({ won }) {
  let xp = 10; // base for finishing a game
  if (won) xp += 20;
  return addXp(xp);
}

function renderLevelBadge() {
  const badge = document.getElementById('level-badge');
  if (!badge) return;
  const { level, xp } = loadLevelData();
  const nextThreshold = xpForNextLevel(level);
  const prevThreshold = LEVEL_XP_THRESHOLDS[level - 1] || 0;
  let progressHtml = '';
  if (nextThreshold !== null) {
    const range = nextThreshold - prevThreshold;
    const progress = xp - prevThreshold;
    const pct = Math.min(100, Math.round((progress / range) * 100));
    progressHtml = `
      <div class="level-xp-bar-wrap" title="${xp} XP · siguiente nivel en ${nextThreshold} XP">
        <div class="level-xp-bar" style="width:${pct}%"></div>
      </div>
      <span class="level-xp-text">${xp} / ${nextThreshold} XP</span>`;
  } else {
    progressHtml = `<span class="level-xp-text">${xp} XP · ¡Nivel máximo!</span>`;
  }
  badge.innerHTML = `<span class="level-num">Nv. ${level}</span>${progressHtml}`;
}

// ─────────────────────────────────────────────────────────────────────────────
const AVATAR_VISIBLE_LIMIT = 8;
let avatarPickerExpanded = false;

function orderedAvatars(selected) {
  const picked = AVATAR_OPTIONS.includes(selected) ? selected : '🎲';
  return [picked, ...AVATAR_OPTIONS.filter(a => a !== picked)];
}

function persistLobbyIdentity(name) {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({
      ...loadSession(),
      name,
      avatar: S.playerAvatar || '🎲',
    }));
  } catch (_) {}
}

function selectAvatar(avatar) {
  if (!AVATAR_OPTIONS.includes(avatar)) return;
  if (!isAvatarUnlocked(avatar)) return; // locked avatars can't be selected
  S.playerAvatar = avatar;
  const name = document.getElementById('inp-name')?.value?.trim() || S.playerName || '';
  persistLobbyIdentity(name);
  renderAvatarPicker();
}

function toggleAvatarPicker() {
  avatarPickerExpanded = !avatarPickerExpanded;
  renderAvatarPicker();
}

function renderAvatarPicker() {
  const row = document.getElementById('avatar-picker');
  const toggle = document.getElementById('btn-avatar-toggle');
  if (!row || !toggle) return;

  row.innerHTML = '';
  const ordered = orderedAvatars(S.playerAvatar);
  const { level } = loadLevelData();
  ordered.forEach((avatar, idx) => {
    const unlocked = isAvatarUnlocked(avatar);
    const entry = AVATAR_LEVEL_MAP.find(e => e.emoji === avatar);
    const btn = document.createElement('button');
    btn.type = 'button';
    let cls = 'avatar-chip';
    if (avatar === S.playerAvatar) cls += ' selected';
    if (!unlocked) cls += ' locked';
    if (!avatarPickerExpanded && idx >= AVATAR_VISIBLE_LIMIT) cls += ' hidden-chip';
    btn.className = cls;
    if (unlocked) {
      btn.textContent = avatar;
      btn.setAttribute('aria-label', `Seleccionar avatar ${avatar}`);
      btn.onclick = () => selectAvatar(avatar);
    } else {
      btn.innerHTML = `<span class="avatar-locked-emoji">${avatar}</span><span class="avatar-lock-icon">🔒</span>`;
      btn.setAttribute('aria-label', `Avatar ${avatar} bloqueado hasta nivel ${entry ? entry.level : '?'}`);
      btn.title = `Se desbloquea en nivel ${entry ? entry.level : '?'}`;
      btn.disabled = true;
    }
    row.appendChild(btn);
  });

  row.classList.toggle('expanded', avatarPickerExpanded);
  toggle.textContent = avatarPickerExpanded ? 'Contraer' : 'Ver todos';
}

// ══════════════════════════════  LOGROS  ══════════════════════════════════════

const ACHIEVEMENTS_STORAGE_KEY = 'dudoAchievements';

const ACHIEVEMENTS_CATALOG = [
  { id: 'first_dudo',      emoji: '🎯', name: 'Primer dudo',        desc: 'Acertar un dudo por primera vez.' },
  { id: 'first_calzo',     emoji: '🔒', name: 'Calzo perfecto',     desc: 'Acertar un calzo por primera vez.' },
  { id: 'survivor',        emoji: '🏃', name: 'Sobreviviente',      desc: 'Ganar una partida sin perder ningún dado.' },
  { id: 'streak5',         emoji: '🔥', name: 'En llamas',          desc: 'Alcanzar una racha de 5 rondas sin perder dados.' },
  { id: 'veteran',         emoji: '🎲', name: 'Veterano',           desc: 'Jugar 10 partidas.' },
  { id: 'champion',        emoji: '🏆', name: 'Campeón',            desc: 'Ganar 5 partidas.' },
  { id: 'gavilan_win',     emoji: '🦅', name: 'Gavilán certero',    desc: 'Gavilán exitoso (dudo fuera de turno correcto).' },
  { id: 'last_die_win',    emoji: '💀', name: 'Al filo',            desc: 'Ganar una partida con un solo dado.' },
  { id: 'three_dudos',     emoji: '⚡', name: 'Certero',            desc: 'Acertar 3 dudos en una misma partida.' },
  { id: 'calzo_one_die',   emoji: '🧊', name: 'Imperturbable',      desc: 'Calzo exitoso teniendo solo 1 dado.' },
];

function loadAchievements() {
  try {
    const raw = localStorage.getItem(ACHIEVEMENTS_STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch (_) { return new Set(); }
}

function saveAchievements(set) {
  try { localStorage.setItem(ACHIEVEMENTS_STORAGE_KEY, JSON.stringify([...set])); } catch (_) {}
}

function unlockAchievement(id) {
  const unlocked = loadAchievements();
  if (unlocked.has(id)) return; // ya desbloqueado
  unlocked.add(id);
  saveAchievements(unlocked);
  const def = ACHIEVEMENTS_CATALOG.find(a => a.id === id);
  if (def) showToast(`${def.emoji} Logro desbloqueado: ${def.name}`);
}

function checkAchievements(context) {
  // context: { action, isGavilan, dudoSuccess, calzoSuccess, myDiceCount,
  //            isGameOver, won, noDiceLost, dudoOkThisGame, stats }
  if (context.dudoSuccess)                         unlockAchievement('first_dudo');
  if (context.calzoSuccess)                         unlockAchievement('first_calzo');
  if (context.calzoSuccess && context.myDiceCount === 1) unlockAchievement('calzo_one_die');
  if (context.isGavilan && context.dudoSuccess)     unlockAchievement('gavilan_win');
  if (context.dudoOkThisGame >= 3)                  unlockAchievement('three_dudos');
  if ((S.streaks[S.playerId] || 0) >= 5)            unlockAchievement('streak5');
  if (context.isGameOver) {
    const stats = context.stats || loadStats();
    if (stats.gamesPlayed >= 10)                    unlockAchievement('veteran');
    if (context.won) {
      if (stats.gamesWon >= 5)                      unlockAchievement('champion');
      if (context.noDiceLost)                       unlockAchievement('survivor');
      if (context.myDiceCount === 1)                unlockAchievement('last_die_win');
    }
  }
}

function renderAchievementsModal() {
  const body = document.getElementById('achievements-body');
  if (!body) return;
  const unlocked = loadAchievements();
  body.innerHTML = '';
  for (const a of ACHIEVEMENTS_CATALOG) {
    const div = document.createElement('div');
    const isUnlocked = unlocked.has(a.id);
    div.className = 'achievement-row' + (isUnlocked ? ' achievement-row--unlocked' : '');
    div.innerHTML = `<span class="ach-emoji">${isUnlocked ? a.emoji : '🔒'}</span><div class="ach-info"><span class="ach-name">${a.name}</span><span class="ach-desc">${a.desc}</span></div>`;
    body.appendChild(div);
  }
}

function openAchievementsModal() {
  renderAchievementsModal();
  const modal = document.getElementById('achievements-modal');
  if (modal) modal.style.display = 'flex';
}

function closeAchievementsModal() {
  const modal = document.getElementById('achievements-modal');
  if (modal) modal.style.display = 'none';
}
const AUDIO_STORAGE_KEY = 'dudoMuted';
const RULES_STORAGE_KEY = 'dudoRules';
const STATS_STORAGE_KEY = 'dudoStats';
// LEVEL_STORAGE_KEY is defined above in the LEVELS section

const EMPTY_STATS = {
  gamesPlayed: 0,
  gamesWon: 0,
  roundsPlayed: 0,
  dudoOk: 0,
  dudoFail: 0,
  calzoOk: 0,
  calzoFail: 0,
};

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

function loadStats() {
  try {
    const raw = localStorage.getItem(STATS_STORAGE_KEY);
    return raw ? { ...EMPTY_STATS, ...JSON.parse(raw) } : { ...EMPTY_STATS };
  } catch (_) {
    return { ...EMPTY_STATS };
  }
}

function saveStats(stats) {
  try { localStorage.setItem(STATS_STORAGE_KEY, JSON.stringify(stats)); } catch (_) {}
}

function ratio(ok, fail) {
  const total = ok + fail;
  if (!total) return '0%';
  return `${Math.round((ok / total) * 100)}%`;
}

function renderStatsModal() {
  const body = document.getElementById('stats-table-body');
  if (!body) return;
  const s = loadStats();
  const rows = [
    ['Partidas jugadas', String(s.gamesPlayed)],
    ['Partidas ganadas / no-perdedor', String(s.gamesWon)],
    ['Rondas jugadas', String(s.roundsPlayed)],
    ['Dudos acertados', `${s.dudoOk} (${ratio(s.dudoOk, s.dudoFail)})`],
    ['Dudos fallados', String(s.dudoFail)],
    ['Calzos acertados', `${s.calzoOk} (${ratio(s.calzoOk, s.calzoFail)})`],
    ['Calzos fallados', String(s.calzoFail)],
  ];
  body.innerHTML = '';
  for (const [label, value] of rows) {
    const tr = document.createElement('tr');
    const tdLabel = document.createElement('td');
    const tdValue = document.createElement('td');
    tdLabel.textContent = label;
    tdValue.textContent = value;
    tr.appendChild(tdLabel);
    tr.appendChild(tdValue);
    body.appendChild(tr);
  }
}

function openStatsModal() {
  renderStatsModal();
  const modal = document.getElementById('stats-modal');
  if (modal) modal.style.display = 'flex';
}

function closeStatsModal() {
  const modal = document.getElementById('stats-modal');
  if (modal) modal.style.display = 'none';
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
  const pan = opts.pan ?? 0;
  if (pan !== 0 && ctx.createStereoPanner) {
    const panner = ctx.createStereoPanner();
    panner.pan.value = Math.max(-1, Math.min(1, pan));
    gain.connect(panner);
    panner.connect(ctx.destination);
  } else {
    gain.connect(ctx.destination);
  }
  osc.start(when);
  osc.stop(when + duration + 0.02);
}

function playSweep(startFreq, endFreq, duration = 0.12, opts = {}) {
  if (AudioState.muted) return;
  const ctx = ensureAudioCtx();
  if (!ctx) return;
  const when = ctx.currentTime + (opts.delay || 0);
  const gain = ctx.createGain();
  const osc = ctx.createOscillator();
  osc.type = opts.type || 'sine';
  osc.frequency.setValueAtTime(startFreq, when);
  osc.frequency.exponentialRampToValueAtTime(Math.max(1, endFreq), when + duration);
  const volume = opts.volume ?? 0.05;
  gain.gain.setValueAtTime(0.0001, when);
  gain.gain.exponentialRampToValueAtTime(volume, when + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, when + duration);
  osc.connect(gain);
  const pan = opts.pan ?? 0;
  if (pan !== 0 && ctx.createStereoPanner) {
    const panner = ctx.createStereoPanner();
    panner.pan.value = Math.max(-1, Math.min(1, pan));
    gain.connect(panner);
    panner.connect(ctx.destination);
  } else {
    gain.connect(ctx.destination);
  }
  osc.start(when);
  osc.stop(when + duration + 0.02);
}

function playNoiseBurst(duration = 0.12, opts = {}) {
  if (AudioState.muted) return;
  const ctx = ensureAudioCtx();
  if (!ctx) return;
  const when = ctx.currentTime + (opts.delay || 0);
  const sampleRate = ctx.sampleRate;
  const frameCount = Math.max(1, Math.floor(sampleRate * duration));
  const buffer = ctx.createBuffer(1, frameCount, sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < frameCount; i++) {
    data[i] = (Math.random() * 2 - 1) * (1 - i / frameCount);
  }
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  const filter = ctx.createBiquadFilter();
  filter.type = 'bandpass';
  filter.frequency.value = opts.freq || 1200;
  filter.Q.value = opts.q || 1.4;
  const gain = ctx.createGain();
  const volume = opts.volume ?? 0.045;
  gain.gain.setValueAtTime(0.0001, when);
  gain.gain.exponentialRampToValueAtTime(volume, when + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, when + duration);
  source.connect(filter);
  filter.connect(gain);
  const pan = opts.pan ?? 0;
  if (pan !== 0 && ctx.createStereoPanner) {
    const panner = ctx.createStereoPanner();
    panner.pan.value = Math.max(-1, Math.min(1, pan));
    gain.connect(panner);
    panner.connect(ctx.destination);
  } else {
    gain.connect(ctx.destination);
  }
  source.start(when);
}

const SFX = {
  click() {
    playTone(620, 0.05, { type: 'square', volume: 0.03 });
  },
  bid(pan = 0) {
    playTone(420, 0.07, { type: 'triangle', volume: 0.045, pan });
    playTone(540, 0.08, { type: 'triangle', delay: 0.06, volume: 0.04, pan });
  },
  paso(pan = 0) {
    playTone(260, 0.12, { type: 'sine', volume: 0.04, pan });
  },
  yourTurn() {
    playTone(740, 0.08, { type: 'square', volume: 0.05 });
    playTone(980, 0.12, { type: 'square', delay: 0.09, volume: 0.045 });
  },
  reveal(pan = 0) {
    playTone(360, 0.09, { type: 'triangle', volume: 0.04, pan });
    playTone(280, 0.12, { type: 'triangle', delay: 0.08, volume: 0.035, pan });
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
  roll() {
    playNoiseBurst(0.13, { freq: 980, q: 1.2, volume: 0.05 });
    playNoiseBurst(0.1, { freq: 620, q: 1.1, delay: 0.03, volume: 0.04 });
  },
  gavilan(pan = 0) {
    playSweep(900, 1800, 0.11, { type: 'triangle', volume: 0.04, pan });
  },
  eliminated(pan = 0) {
    playTone(420, 0.16, { type: 'sawtooth', volume: 0.05, pan });
    playTone(300, 0.2, { type: 'sawtooth', delay: 0.14, volume: 0.045, pan });
    playTone(210, 0.24, { type: 'sawtooth', delay: 0.32, volume: 0.04, pan });
  },
  reconnect() {
    playTone(880, 0.06, { type: 'sine', volume: 0.035 });
    playTone(1040, 0.1, { type: 'triangle', delay: 0.06, volume: 0.03 });
  },
  tick() {
    playTone(1450, 0.03, { type: 'square', volume: 0.025 });
  },
  emojiHit() {
    // Sonido al recibir un emoji: "pop" suave con dos tonos cortos
    playTone(800, 0.04, { type: 'sine', volume: 0.04 });
    playTone(1100, 0.05, { type: 'sine', delay: 0.04, volume: 0.03 });
  },
};

function playSfx(name) {
  unlockAudio();
  const fx = SFX[name];
  if (fx) fx();
}

/**
 * Calcula el valor de pan estéreo (-1 a +1) para un jugador dado su pid.
 * Usa la posición CSS de su carta en la mesa para determinar su ángulo.
 * Retorna 0 (centrado) si no se encuentra la carta o es el propio jugador.
 */
function panForPid(pid) {
  if (!pid || pid === S.playerId) return 0;
  const card = document.querySelector(`.player-card[data-pid="${pid}"]`);
  if (!card) return 0;
  const table = document.querySelector('.game-table');
  if (!table) return 0;
  const cx = table.clientWidth  * 0.50;
  const cy = table.clientHeight * 0.43;
  const x = parseFloat(card.style.left);
  const y = parseFloat(card.style.top);
  if (isNaN(x) || isNaN(y)) return 0;
  // cos(ángulo): -1 = izquierda, 0 = centro (arriba/abajo), +1 = derecha
  return Math.cos(Math.atan2(y - cy, x - cx));
}

/**
 * Reproduce un SFX con pan estéreo basado en la posición del jugador en la mesa.
 * Los sonidos del propio jugador o eventos de mesa suenan centrados (pan=0).
 */
function playSfxFor(name, pid = null) {
  unlockAudio();
  const fx = SFX[name];
  if (!fx) return;
  const pan = pid ? panForPid(pid) : 0;
  fx(pan);
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
  updateNotificationButton();
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
      playSfx('reconnect');
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
    player_kicked:      onPlayerKicked,
    kicked:             onKicked,
    error:              onError,
    emoji_thrown:       onEmojiThrown,
    quick_chat:         onQuickChat,
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
  S.spectatorCount = msg.spectator_count ?? 0;
  updateSpectatorCount();
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
  maybeInitEmojiHover();
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
  S.spectatorCount = msg.spectator_count ?? S.spectatorCount;
  updateSpectatorCount();
  if (msg.turn) onTurn(msg.turn);
  renderOtherPlayers();
  renderMyDice();
  updateBidDisplay();
  document.getElementById('disp-round').textContent = S.roundNum;
  document.getElementById('disp-total').textContent = S.totalDice;
}

function onSpectatorJoined(msg) {
  if (msg.spectator_count !== undefined) {
    S.spectatorCount = msg.spectator_count;
    updateSpectatorCount();
  }
  log(`${msg.spectator_name} se unió como espectador`, 'system');
}

function onSpectatorLeft(msg) {
  if (msg.spectator_count !== undefined) {
    S.spectatorCount = msg.spectator_count;
    updateSpectatorCount();
  }
  log(`${msg.spectator_name} dejó de observar`, 'system');
}

function updateSpectatorCount() {
  const el = document.getElementById('spectator-count');
  if (!el) return;
  if (S.spectatorCount > 0) {
    el.textContent = `👁 ${S.spectatorCount}`;
    el.style.display = 'inline-flex';
  } else {
    el.style.display = 'none';
  }
}

function onPlayerKicked(msg) {
  delete S.players[msg.player_id];
  S.playerOrder = S.playerOrder.filter(pid => pid !== msg.player_id);
  if (S.currentPid === msg.player_id) S.currentPid = null;
  renderLobbyPlayers();
  renderOtherPlayers();
  updateStartButton();
  log(`${msg.player_name} fue expulsado por ${msg.kicked_by_name}`, 'system');
}

function onKicked(msg) {
  showToast(msg.message || 'Fuiste expulsado de la sala', true);
  log(msg.message || 'Fuiste expulsado de la sala', 'system');
  closeKickConfirm();
  clearSession();
  S.manualClose = true;
  if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.close();
  S.roomId = '';
  S.players = {};
  S.playerOrder = [];
  showScreen('lobby');
  const form = document.getElementById('lobby-form');
  const room = document.getElementById('lobby-room');
  if (form) form.style.display = 'block';
  if (room) room.style.display = 'none';
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
  S.spectatorCount = msg.spectator_count ?? S.spectatorCount;
  updateSpectatorCount();
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
    playSfx('reconnect');
    log('Reconectado al lobby', 'system');
    return;
  }

  showScreen('game');
  applySpectatorMode();
  renderOtherPlayers();
  maybeInitEmojiHover();
  updateBidDisplay();
  playSfx('reconnect');
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
  if (S.gameOverTimer !== null) { clearTimeout(S.gameOverTimer); S.gameOverTimer = null; }
  document.getElementById('game-over-overlay').style.display = 'none';
  applyEliminatedMode(false);
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
  S.lastLossPlayerId = null;
  S.pendingStats = { dudoOk: 0, dudoFail: 0, calzoOk: 0, calzoFail: 0 };
  S.streaks = {};
  S.bestStreaks = {};
  showScreen('game');
  applySpectatorMode();
  renderOtherPlayers();
  maybeInitEmojiHover();
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
  playSfx('roll');
}

function onYourDice(msg) {
  S.myDice    = msg.dice;
  S.roundNum  = msg.round_number;
  S.totalDice = msg.total_dice;
  if (msg.has_passed !== undefined) S.hasPassed = msg.has_passed;

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
  playSfxFor('bid', msg.bid?.player_id);
  hideTimeoutActionHint();
  S.currentBid = msg.bid;
  S.activePaso = null;  // la apuesta reemplaza al paso como acción activa
  const b = msg.bid;
  const name = S.players[b.player_id]?.name || b.player_name;
  log(`${name}: ${b.quantity} × ${faceName(b.face)}`, 'bid');
  updateBidDisplay();
  updateControls();
}

function onPasoMade(msg) {
  playSfxFor('paso', msg.passer_id);
  hideTimeoutActionHint();
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
  playSfxFor('reveal', msg.challenger_id);
  stopTurnCountdown();
  S.phase = 'reveal';
  S.lastLossPlayerId = msg.loser_id || null;
  // Romper racha del jugador que pierde un dado
  if (msg.loser_id) {
    S.streaks[msg.loser_id] = 0;
  }
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
  if (msg.loser_id && S.players[msg.loser_id]) {
    S.players[msg.loser_id].dice_count = Math.max(0, (S.players[msg.loser_id].dice_count || 0) - 1);
    renderOtherPlayers();
  }
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

  if (msg.challenger_id === S.playerId) {
    let actionSuccess = false;
    if (msg.action === 'calzo') {
      actionSuccess = !!msg.calzo_success;
      if (actionSuccess) S.pendingStats.calzoOk += 1;
      else S.pendingStats.calzoFail += 1;
    } else if (msg.action === 'dudo') {
      actionSuccess = !msg.bid_holds;
      if (actionSuccess) S.pendingStats.dudoOk += 1;
      else S.pendingStats.dudoFail += 1;
    } else if (msg.action === 'paso') {
      actionSuccess = !msg.paso_valid;
      if (actionSuccess) S.pendingStats.dudoOk += 1;
      else S.pendingStats.dudoFail += 1;
    }
    // Save XP immediately — always positive, just more if correct
    const actionXpResult = awardActionXp(msg.action, actionSuccess);
    if (actionXpResult && actionXpResult.unlockedEmojis.length > 0) {
      showToast(`¡Desbloqueaste: ${actionXpResult.unlockedEmojis.join(' ')}! (Nv. ${actionXpResult.newLevel})`);
    }
    // Check achievements for this action
    checkAchievements({
      dudoSuccess: msg.action === 'dudo' && actionSuccess,
      calzoSuccess: msg.action === 'calzo' && actionSuccess,
      isGavilan: !!msg.is_gavilan && msg.action === 'dudo' && actionSuccess,
      myDiceCount: S.myDice.length || (S.players[S.playerId]?.dice_count ?? 5),
      dudoOkThisGame: S.pendingStats.dudoOk,
    });
  }

  if (msg.is_gavilan) {
    playSfxFor('gavilan', msg.challenger_id);
  }

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

  startRevealCountdown(Number(msg.reveal_seconds || 7));
}

function onNewRound(msg) {
  stopTurnCountdown();
  // Award 1 XP for surviving the previous round (skip on round 1 start)
  if (S.roundNum > 0) {
    awardRoundXp();
    // Increment streak for all players still alive (dice_count > 0)
    for (const pid of Object.keys(S.players)) {
      const p = S.players[pid];
      if (p && p.dice_count > 0) {
        S.streaks[pid] = (S.streaks[pid] || 0) + 1;
        if ((S.streaks[pid] || 0) > (S.bestStreaks[pid] || 0)) {
          S.bestStreaks[pid] = S.streaks[pid];
        }
      }
    }
    renderStreakBadges();
  }
  S.roundNum      = msg.round_number;
  S.currentBid       = null;
  S.activePaso       = null;
  S.hasPassed        = false;
  S.revealDice       = {};
  S.revealBidFace    = null;
  S.lastActionPlayerId = null;
  S.lastActionType = null;
  S.roundFirstPlayer   = '';
  S.hasFirstAction     = false;
  S.lastLossPlayerId   = null;
  S.phase              = 'playing';
  hideReveal();
  updateDirectionIndicator();
  updateBidDisplay();
  log(`─── Ronda ${S.roundNum} ───`, 'round');
  playSfx('roll');
  renderOtherPlayers();
}

function renderStreakBadges() {
  // Actualiza badges de racha en cartas de oponentes ya renderizadas
  renderOtherPlayers();
  // Badge en la propia carta
  const myStreak = S.streaks[S.playerId] || 0;
  const nameEl = document.getElementById('my-name-disp');
  if (nameEl) {
    const base = S.playerAvatar ? `${S.playerAvatar} ${S.playerName}` : S.playerName;
    nameEl.textContent = myStreak >= 2 ? `${base} 🔥${myStreak}` : base;
  }
}

function onEliminated(msg) {  if (S.players[msg.player_id])
    S.players[msg.player_id].dice_count = 0;
  playSfxFor('eliminated', msg.player_id);
  log(`${msg.player_name} fue eliminado`, 'elim');
  renderOtherPlayers();
  if (msg.player_id === S.playerId) applyEliminatedMode(true);
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

  const stats = loadStats();
  stats.gamesPlayed += 1;
  stats.roundsPlayed += Math.max(1, S.roundNum || 0);
  if ((!isLoserMode && isWinner) || (isLoserMode && !isLoser)) {
    stats.gamesWon += 1;
  }
  stats.dudoOk += S.pendingStats.dudoOk;
  stats.dudoFail += S.pendingStats.dudoFail;
  stats.calzoOk += S.pendingStats.calzoOk;
  stats.calzoFail += S.pendingStats.calzoFail;
  saveStats(stats);

  const won = (!isLoserMode && isWinner) || (isLoserMode && !isLoser);
  // Check game-over achievements
  const myFinalDice = S.myDice.length || (S.players[S.playerId]?.dice_count ?? 0);
  const noDiceLost = myFinalDice >= 5;
  checkAchievements({
    isGameOver: true,
    won,
    noDiceLost,
    myDiceCount: myFinalDice,
    dudoOkThisGame: S.pendingStats.dudoOk,
    stats,
  });

  // Award XP: base + win bonus (action XP was already saved during reveals)
  const xpResult = awardGameOverXp({ won });

  // Preparar el overlay ya, pero mostrarlo al terminar el countdown de reveal (7 s)
  const overlay = document.getElementById('game-over-overlay');
  if (isLoserMode) {
    document.getElementById('go-title').textContent = isLoser ? 'Perdiste' : 'Fin de la partida';
    document.getElementById('go-winner').textContent = `${msg.loser_name} quedó como perdedor`;
  } else {
    document.getElementById('go-title').textContent = isWinner ? '¡Ganaste!' : 'Fin de la partida';
    document.getElementById('go-winner').textContent = `${msg.winner_name} es el ganador`;
  }

  // Build XP summary to show in overlay
  let xpLines = `+${xpResult.xpGained} XP`;
  if (xpResult.newLevel > xpResult.oldLevel) {
    xpLines += ` · ¡Subiste al nivel ${xpResult.newLevel}!`;
  }
  if (xpResult.unlockedEmojis.length > 0) {
    xpLines += ` · Desbloqueaste: ${xpResult.unlockedEmojis.join(' ')}`;
  }
  const goXp = document.getElementById('go-xp');
  if (goXp) goXp.textContent = xpLines;

  // Build standings table
  const goStandings = document.getElementById('go-standings');
  if (goStandings && Array.isArray(msg.standings) && msg.standings.length > 1) {
    goStandings.innerHTML = '';
    const total = msg.standings.length;
    msg.standings.slice().reverse().forEach((entry, i) => {
      const pos = total - i;
      const li = document.createElement('li');
      li.className = 'go-standing-row';
      const isSelf = entry.id === S.playerId;
      if (isSelf) li.classList.add('go-standing-row--self');
      const best = S.bestStreaks[entry.id] || 0;
      const streakStr = best >= 2 ? ` <span class="go-streak">🔥${best}</span>` : '';
      li.innerHTML = `<span class="go-pos">${pos}</span><span class="go-avatar">${entry.avatar}</span><span class="go-sname">${entry.name}</span>${streakStr}`;
      goStandings.appendChild(li);
    });
    goStandings.style.display = 'flex';
  } else if (goStandings) {
    goStandings.style.display = 'none';
  }

  const revealSeconds = Number(msg.reveal_seconds || 7);
  S.gameOverTimer = setTimeout(() => {
    S.gameOverTimer = null;
    hideReveal();
    const endSfx = isLoserMode ? (isLoser ? 'lose' : 'win') : (isWinner ? 'win' : 'lose');
    playSfx(endSfx);
    overlay.style.display = 'flex';
  }, Math.max(0, revealSeconds) * 1000);
}

function closeGameOver() {
  if (S.gameOverTimer !== null) { clearTimeout(S.gameOverTimer); S.gameOverTimer = null; }
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
  renderAvatarPicker(); // refresh locked/unlocked state after XP gain
  renderLevelBadge();
  applySpectatorMode();
  updateReadyButton(false);
  document.getElementById('btn-ready').classList.remove('btn-start');
}

function onError(msg) {
  playSfx('error');
  showToast(msg.message, true);
}

// ══════════════════════════════════  EMOJI  ════════════════════════════════════

// Fuente de verdad: /static/emojis.json  (compartido con el servidor)
// Se carga una sola vez al inicio; vacío hasta que resuelva el fetch.
let THROWABLE_EMOJIS = [];
fetch('/static/emojis.json')
  .then(r => r.json())
  .then(data => { THROWABLE_EMOJIS = data; })
  .catch(() => { /* si falla, el array queda vacío y los emojis simplemente no aparecen */ });

// Cuántos emojis se muestran en la primera fila (sin expandir)
const EMOJI_ROW_SIZE = 5;

function throwEmoji(targetPid, emoji) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return;
  if (!S.rules?.allow_throwable_emojis) return;
  send({ type: 'emoji', target_id: targetPid, emoji });
}

// ══════════════════════════════  QUICK CHAT  ═══════════════════════════════════

const QUICK_PHRASES = [
  '¡Mentira!', '¡Suerte!', 'Buen bluff', 'No te creo',
  '¡Calzo!', 'Vamos', '😅', '🤔', 'Eso era mentira',
  '¡Bien jugado!', 'Mala suerte', 'Ups',
];

function sendQuickChat(phrase) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return;
  send({ type: 'quick_chat', phrase });
}

function onQuickChat(msg) {
  const isSelf = msg.from_id === S.playerId;
  const label = isSelf ? 'Tú' : msg.from_name;
  log(`${msg.from_avatar} ${label}: "${msg.phrase}"`, 'chat');
  _showQuickChatBubble(msg.from_id, msg.phrase);
}

function _showQuickChatBubble(fromId, phrase) {
  // Busca la carta del jugador (propio o oponente) y muestra una burbuja temporal
  const card = document.querySelector(
    `#other-players .player-card[data-pid="${fromId}"], #self-card`
  );
  if (!card) return;
  const existing = card.querySelector('.qc-bubble');
  if (existing) existing.remove();
  const bubble = document.createElement('div');
  bubble.className = 'qc-bubble';
  bubble.textContent = phrase;
  card.appendChild(bubble);
  setTimeout(() => bubble.remove(), 3000);
}

function onEmojiThrown(msg) {
  animateEmojiThrow(msg.from_id, msg.target_id, msg.emoji);
  if (msg.target_id === S.playerId) playSfx('emojiHit');
}

/**
 * Sistema de popup de emojis.
 * El popup vive en document.body (position:fixed) para escapar cualquier
 * stacking context. Show/hide se maneja con dos flags booleanos sin timers:
 * _efOverCard y _efOverPopup. Se oculta solo cuando ambos son false.
 */

let _efPopup        = null;
let _efPid          = null;
let _efHideTimer    = null;

function _efHide() {
  if (_efPopup) {
    _efPopup.classList.remove('ef-popup--visible');
    _efPopup.classList.remove('ef-popup--expanded');
    const ch = _efPopup.querySelector('.ef-chevron');
    if (ch) ch.textContent = '›';
    _efPopup.style.top  = '';
    _efPopup.style.left = '';
  }
  _efPid = null;
  _efHideTimer = null;
}

function _efScheduleHide() {
  clearTimeout(_efHideTimer);
  _efHideTimer = setTimeout(_efHide, 400);
}

function _efCancelHide() {
  clearTimeout(_efHideTimer);
  _efHideTimer = null;
}

// Comprueba si el punto (x,y) está dentro del rect de un elemento, con margen opcional
function _efHitTest(el, x, y, margin = 0) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return x >= r.left - margin && x <= r.right + margin && y >= r.top - margin && y <= r.bottom + margin;
}

function _efPosition(card) {
  if (!_efPopup || !card) return;
  // Asegurarse de que el popup está renderizado para medir
  _efPopup.style.top  = '-9999px';
  _efPopup.style.left = '-9999px';
  _efPopup.classList.add('ef-popup--visible');

  const cr = card.getBoundingClientRect();
  const pw = _efPopup.offsetWidth  || 180;
  const ph = _efPopup.offsetHeight || 40;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let top = cr.bottom;
  if (top + ph > vh - 8) top = cr.top - ph;
  top = Math.max(8, Math.min(top, vh - ph - 8));

  let left = cr.left + cr.width / 2 - pw / 2;
  left = Math.max(8, Math.min(left, vw - pw - 8));

  _efPopup.style.top  = `${top}px`;
  _efPopup.style.left = `${left}px`;
}

function _efShow(pid, card) {
  _efCancelHide();
  _efPid = pid;
  _efEnsurePopup();
  _efRefreshPopupLocks();
  _efPosition(card);
}

function _efBuildPopup() {
  if (_efPopup) { _efPopup.remove(); _efPopup = null; }

  const popup = document.createElement('div');
  popup.className = 'ef-popup';

  const row = document.createElement('div');
  row.className = 'ef-row';

  // Crear todos los botones (desbloqueados e bloqueados), se actualizan al mostrar
  THROWABLE_EMOJIS.slice(0, EMOJI_ROW_SIZE).forEach(item => row.appendChild(_efMakeBtn(item)));

  const chevron = document.createElement('button');
  chevron.type = 'button';
  chevron.className = 'ef-chevron';
  chevron.setAttribute('aria-label', 'Más emojis');
  chevron.textContent = '›';
  chevron.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const open = popup.classList.toggle('ef-popup--expanded');
    chevron.textContent = open ? '‹' : '›';
  });
  row.appendChild(chevron);

  const extra = document.createElement('div');
  extra.className = 'ef-extra';
  THROWABLE_EMOJIS.slice(EMOJI_ROW_SIZE).forEach(item => extra.appendChild(_efMakeBtn(item)));

  popup.appendChild(row);
  popup.appendChild(extra);

  // Separador + frases rápidas
  const sep = document.createElement('div');
  sep.className = 'ef-phrases-sep';
  popup.appendChild(sep);

  const phrases = document.createElement('div');
  phrases.className = 'ef-phrases';
  QUICK_PHRASES.forEach(phrase => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ef-phrase-btn';
    btn.textContent = phrase;
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      sendQuickChat(phrase);
      _efScheduleHide();
    });
    phrases.appendChild(btn);
  });
  popup.appendChild(phrases);

  document.body.appendChild(popup);
  _efPopup = popup;
  return popup;
}

function _efMakeBtn(item) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.dataset.emojiLevel = item.level;
  btn.dataset.emoji = item.emoji;
  btn.className = 'ef-btn';
  btn.textContent = item.emoji;
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const pid = _efPid;
    if (pid) throwEmoji(pid, item.emoji);
  });
  return btn;
}

// Actualiza el estado bloqueado/desbloqueado de cada botón según el nivel actual
function _efRefreshPopupLocks() {
  if (!_efPopup) return;
  const { level } = loadLevelData();
  const isSelf = _efPid === S.playerId;
  // Ocultar sección de emojis lanzables cuando es la propia carta
  const row = _efPopup.querySelector('.ef-row');
  const extra = _efPopup.querySelector('.ef-extra');
  const sep = _efPopup.querySelector('.ef-phrases-sep');
  if (row) row.style.display = isSelf ? 'none' : '';
  if (extra) { if (isSelf) { extra.style.display = 'none'; _efPopup.classList.remove('ef-popup--expanded'); } else { extra.style.display = ''; } }
  if (sep) sep.style.display = isSelf ? 'none' : '';
  _efPopup.querySelectorAll('.ef-btn[data-emoji-level]').forEach(btn => {
    const needed = parseInt(btn.dataset.emojiLevel, 10);
    const locked = level < needed;
    btn.disabled = locked;
    btn.classList.toggle('ef-btn--locked', locked);
    btn.title = locked ? `Se desbloquea en nivel ${needed}` : '';
    if (locked) {
      btn.innerHTML = `<span class="ef-btn-emoji">${btn.dataset.emoji}</span><span class="ef-btn-lock">🔒</span>`;
    } else {
      btn.textContent = btn.dataset.emoji;
    }
  });
}

function _efEnsurePopup() {
  if (_efPopup) return _efPopup;
  return _efBuildPopup();
}

function buildEmojiBar(targetPid) {
  const trigger = document.createElement('div');
  trigger.className = 'emoji-bar-trigger';
  trigger.dataset.pid = targetPid;
  if (!S.rules?.allow_throwable_emojis) {
    trigger.style.display = 'none';
  }
  return trigger;
}

function attachEmojiHoverToCard(card) {
  // No usar mouseenter/mouseleave — son poco fiables con elementos superpuestos.
  // En su lugar, mousemove global detecta si el puntero está sobre card o popup.
}

// Listener global de mousemove — única fuente de verdad para show/hide
let _efMoveInited = false;
function maybeInitEmojiHover() {
  if (_efMoveInited) return;
  _efMoveInited = true;

  document.addEventListener('mousemove', (e) => {
    if (S.phase !== 'playing' && S.phase !== 'reveal') {
      if (_efPid) _efHide();
      return;
    }

    const x = e.clientX, y = e.clientY;

    // ¿Está sobre el popup activo? (margen de 16px para cubrir el gap card→popup)
    if (_efPopup && _efPopup.classList.contains('ef-popup--visible')) {
      if (_efHitTest(_efPopup, x, y, 16)) {
        _efCancelHide();
        return;
      }
    }

    // ¿Está sobre alguna card de rival?
    const cards = document.querySelectorAll('#other-players .player-card[data-pid]');
    for (const card of cards) {
      if (_efHitTest(card, x, y)) {
        const pid = card.dataset.pid;
        if (pid !== _efPid) {
          _efShow(pid, card);
        } else {
          _efCancelHide();
        }
        return;
      }
    }

    // ¿Está sobre la propia carta? (solo frases rápidas, sin emojis lanzables)
    const selfCard = document.getElementById('self-card');
    if (selfCard && _efHitTest(selfCard, x, y)) {
      if (S.playerId !== _efPid) {
        _efShow(S.playerId, selfCard);
      } else {
        _efCancelHide();
      }
      return;
    }

    // Fuera de todo — programar ocultamiento
    if (_efPid) _efScheduleHide();
  });

  document.addEventListener('mouseleave', _efHide);
}

function resetEmojiPopup() {
  _efHide();
}



/**
 * Anima un emoji con trayectoria parabólica hacia el receptor,
 * luego cae al "piso" (bottom del viewport) y da un bote con dirección dinámica.
 */
function animateEmojiThrow(fromId, targetId, emoji) {
  function getCardCenter(pid) {
    if (pid === S.playerId) {
      const el = document.getElementById('my-area') || document.getElementById('my-dice-row');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }
    const card = document.querySelector(`.player-card[data-pid="${pid}"]`);
    if (!card) return null;
    const r = card.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }

  const from = getCardCenter(fromId);
  const to   = getCardCenter(targetId);

  const x0 = from ? from.x : 640;
  const y0 = from ? from.y : 400;
  const x1 = to   ? to.x   : 640;
  const y1 = to   ? to.y   : 400;

  // Punto de control de Bézier cuadrática: arco hacia arriba proporcional a la distancia
  const dist   = Math.hypot(x1 - x0, y1 - y0);
  const arcH   = Math.min(dist * 0.55, 260);   // altura del arco
  const cpx    = (x0 + x1) / 2;
  const cpy    = Math.min(y0, y1) - arcH;       // siempre por encima del origen

  // Rotación total: para pulgares siempre termina derecho (múltiplo de 360°)
  // para el resto es aleatoria
  const UPRIGHT_EMOJIS = ['👍', '👎'];
  const totalRot = UPRIGHT_EMOJIS.includes(emoji)
    ? (Math.random() < 0.5 ? 1 : -1) * 360 * (1 + Math.floor(Math.random() * 2))
    : (Math.random() < 0.5 ? 1 : -1) * (360 + Math.random() * 360);

  const el = document.createElement('div');
  el.className = 'emoji-projectile';
  el.textContent = emoji;
  Object.assign(el.style, { left: '0px', top: '0px' });
  document.body.appendChild(el);

  // ── Fase 1: vuelo parabólico (Bézier cuadrática) ─────────────────────────
  const FLIGHT_MS = 700;
  let startTs = null;

  function bézier(t, p0, p1, p2) {
    // B(t) = (1-t)²·p0 + 2(1-t)t·p1 + t²·p2
    return (1 - t) * (1 - t) * p0 + 2 * (1 - t) * t * p1 + t * t * p2;
  }

  function flyFrame(ts) {
    if (!startTs) startTs = ts;
    let t = Math.min((ts - startTs) / FLIGHT_MS, 1);

    // ease-in-out para el progreso horizontal; aceleración gravitacional en y
    const tEase = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;

    const bx = bézier(tEase, x0, cpx, x1);
    const by = bézier(t,     y0, cpy, y1);   // t sin ease → caída natural

    // Escala: crece al salir, se mantiene, se agranda al impactar
    // font-size base es 3rem; escala max = 1.0 para evitar upscaling y pixelado
    const scale = t < 0.1  ? 0.27 + t * 4.6
                : t < 0.85 ? 0.73
                :             0.73 + (t - 0.85) * 1.8; // llega a ~1.0 al impactar

    const rot = totalRot * t;
    const opacity = t < 0.08 ? t / 0.08 : 1;

    el.style.transform = `translate(calc(${bx}px - 50%), calc(${by}px - 50%)) scale(${scale}) rotate(${rot}deg)`;
    el.style.opacity   = opacity;

    if (t < 1) {
      requestAnimationFrame(flyFrame);
    } else {
      // Impacto sobre el receptor
      triggerHitEffect(targetId);
      // Pausa en el punto de impacto para que se vea bien, luego fase 2
      setTimeout(() => bounceFall(el, x1, y1, totalRot), 100);
    }
  }

  requestAnimationFrame(flyFrame);

  // ── Fase 2: caída corta + bote suave (animación de muerte, baja prioridad) ──
  function bounceFall(el, ix, iy, rot) {
    // Bajar z-index: es decorativo, no debe tapar nada importante
    el.style.zIndex = '100';
    el.style.filter = 'none';

    const FALL_DIST = 180 + Math.random() * 40;   // ~180-220px, no hasta el fondo
    const floorY    = iy + FALL_DIST;

    // Lateral aleatorio puro, lado variable
    const side    = Math.random() < 0.5 ? 1 : -1;
    const lateral = side * (30 + Math.random() * 50);
    const bounceH = 18 + Math.random() * 22;       // bote pequeño: 18-40px

    const FALL_MS   = 260;
    const BOUNCE_MS = 300;

    let fallStart = null;

    function fallFrame(ts) {
      if (!fallStart) fallStart = ts;
      const t = Math.min((ts - fallStart) / FALL_MS, 1);
      const by    = iy + FALL_DIST * t * t;         // gravedad t²
      const scale = 0.6 - t * 0.13;                // encoge suavemente
      const r     = rot + 25 * t * side;
      const op    = 0.75 - t * 0.25;                // ya empieza semitransparente
      el.style.transform = `translate(calc(${ix}px - 50%), calc(${by}px - 50%)) scale(${scale}) rotate(${r}deg)`;
      el.style.opacity   = op;

      if (t < 1) {
        requestAnimationFrame(fallFrame);
      } else {
        // Squash mínimo al tocar "piso"
        const r2 = rot + 25 * side;
        el.style.transform = `translate(calc(${ix}px - 50%), calc(${floorY}px - 50%)) scaleX(1.2) scaleY(0.7) rotate(${r2}deg)`;
        setTimeout(() => bounceUp(el, ix, floorY, r2, lateral, bounceH, BOUNCE_MS), 40);
      }
    }

    requestAnimationFrame(fallFrame);
  }

  function bounceUp(el, ix, floorY, rot, lateral, bounceH, dur) {
    let bounceStart = null;

    function bounceFrame(ts) {
      if (!bounceStart) bounceStart = ts;
      const t  = Math.min((ts - bounceStart) / dur, 1);
      const arcY   = floorY - bounceH * 4 * t * (1 - t);
      const bx     = ix + lateral * t;
      const scale  = 0.43 + 0.07 * Math.sin(t * Math.PI);
      const r      = rot + 60 * t * (lateral > 0 ? 1 : -1);
      const opacity = 0.5 * (1 - t);               // desvanece rápido

      el.style.transform = `translate(calc(${bx}px - 50%), calc(${arcY}px - 50%)) scale(${scale}) rotate(${r}deg)`;
      el.style.opacity   = opacity;

      if (t < 1) {
        requestAnimationFrame(bounceFrame);
      } else {
        el.remove();
      }
    }

    requestAnimationFrame(bounceFrame);
  }

  // ── Efecto de impacto en el receptor ─────────────────────────────────────
  function triggerHitEffect(targetId) {
    const hitEl = targetId === S.playerId
      ? document.getElementById('my-area')
      : document.querySelector(`.player-card[data-pid="${targetId}"]`);
    if (!hitEl) return;
    hitEl.classList.remove('emoji-hit');
    void hitEl.offsetWidth;
    hitEl.classList.add('emoji-hit');
    hitEl.addEventListener('animationend', () => hitEl.classList.remove('emoji-hit'), { once: true });
  }
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
      if (remaining <= 3) playSfx('tick');
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
  el.classList.remove('turn-countdown--urgent', 'turn-countdown--critical');
  hideTimeoutActionHint();
}

function _timeoutActionHintText() {
  // Replica la lógica de _run_timeout_action del backend para mostrar qué acción se ejecutará
  if (S.currentPid !== S.playerId) return null;
  if (S.currentBid && !S.hasPassed) return '⏱ Paso automático…';
  const face = S.currentBid ? S.currentBid.face : 2;
  const faceName = ['', 'As', 'Dos', 'Tres', 'Cuatro', 'Cinco', 'Seis'][face] || face;
  return `⏱ Apuesta automática (${faceName})…`;
}

function hideTimeoutActionHint() {
  const hint = document.getElementById('timeout-action-hint');
  if (hint) { hint.style.display = 'none'; hint.textContent = ''; }
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
    el.classList.toggle('turn-countdown--urgent',   left <= 10);
    el.classList.toggle('turn-countdown--critical', left <= 5);
    // Aviso de acción automática en los últimos 3s solo si es mi turno
    const hint = document.getElementById('timeout-action-hint');
    if (hint) {
      if (left <= 3) {
        const text = _timeoutActionHintText();
        if (text) { hint.textContent = text; hint.style.display = 'inline-flex'; }
      } else {
        hideTimeoutActionHint();
      }
    }
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
    row.className = 'lobby-player-row' + (hostId === pid ? ' is-host' : '') + (p.connected ? '' : ' inactive');

    const av = document.createElement('div');
    av.className = 'player-avatar';
    av.textContent = p.avatar || '🎲';
    av.style.background = playerColor(pid);

    const name = document.createElement('div');
    name.className = 'player-pname';
    name.textContent = p.name;

    const badge = document.createElement('div');
    badge.className = 'ready-badge' + (p.connected ? (p.ready ? ' ready' : '') : ' inactive');
    badge.innerHTML = !p.connected
      ? '<i class="fa-solid fa-plug-circle-xmark" aria-hidden="true"></i> Inactivo'
      : (p.ready
        ? '<i class="fa-solid fa-check" aria-hidden="true"></i> Listo'
        : '<i class="fa-regular fa-clock" aria-hidden="true"></i> Esperando');

    if (S.isHost && pid !== S.playerId) {
      const kickBtn = document.createElement('button');
      kickBtn.type = 'button';
      kickBtn.className = 'kick-btn';
      kickBtn.title = `Expulsar a ${p.name}`;
      kickBtn.setAttribute('aria-label', `Expulsar a ${p.name}`);
      kickBtn.innerHTML = '<i class="fa-solid fa-user-xmark" aria-hidden="true"></i>';
      kickBtn.onclick = () => openKickConfirm(pid, p.name);
      row.appendChild(av);
      row.appendChild(kickBtn);
      row.appendChild(name);
      row.appendChild(badge);
    } else {
      row.appendChild(av);
      row.appendChild(name);
      row.appendChild(badge);
    }
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
      (p.connected ? '' : ' inactive') +
      (p.dice_count <= 0 ? ' eliminated' : '');
    card.dataset.pid = pid;

    const nameEl = document.createElement('div');
    nameEl.className = 'player-card-name';
    nameEl.textContent = `${p.avatar || '🎲'} ${p.name}`;

    const headerEl = document.createElement('div');
    headerEl.className = 'player-card-header';

    const offlineEl = !p.connected ? document.createElement('div') : null;
    if (offlineEl) {
      offlineEl.className = 'player-offline-tag';
      offlineEl.innerHTML = '<i class="fa-solid fa-plug-circle-xmark" aria-hidden="true"></i> INACTIVO';
    }

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

    if (S.isHost && pid !== S.playerId) {
      const kickBtn = document.createElement('button');
      kickBtn.type = 'button';
      kickBtn.className = 'kick-btn';
      kickBtn.title = `Expulsar a ${p.name}`;
      kickBtn.setAttribute('aria-label', `Expulsar a ${p.name}`);
      kickBtn.innerHTML = '<i class="fa-solid fa-user-xmark" aria-hidden="true"></i>';
      kickBtn.onclick = () => openKickConfirm(pid, p.name);
      headerEl.appendChild(kickBtn);
    }

    headerEl.appendChild(nameEl);

    // Streak badge
    const streak = S.streaks[pid] || 0;
    if (streak >= 2) {
      const streakBadge = document.createElement('span');
      streakBadge.className = 'streak-badge';
      streakBadge.textContent = `🔥${streak}`;
      streakBadge.title = `${streak} rondas consecutivas sin perder dados`;
      headerEl.appendChild(streakBadge);
    }

    // Selector de emoji inline (aparece al hover sobre la card)
    const emojiBar = buildEmojiBar(pid);

    card.appendChild(headerEl);
    if (offlineEl) card.appendChild(offlineEl);
    card.appendChild(diceRow);
    if (actionBadge) card.appendChild(actionBadge);
    card.appendChild(emojiBar);
    container.appendChild(card);
    attachEmojiHoverToCard(card);

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

function openKickConfirm(playerId, playerName) {
  if (!S.isHost || playerId === S.playerId) return;
  S.pendingKickTargetId = playerId;
  S.pendingKickTargetName = playerName || 'este jugador';
  const text = document.getElementById('kick-confirm-text');
  if (text) text.textContent = `¿Seguro que deseas expulsar a ${S.pendingKickTargetName}?`;
  const modal = document.getElementById('kick-confirm-modal');
  if (modal) modal.style.display = 'flex';
}

function closeKickConfirm() {
  S.pendingKickTargetId = null;
  S.pendingKickTargetName = '';
  const modal = document.getElementById('kick-confirm-modal');
  if (modal) modal.style.display = 'none';
}

function confirmKickPlayer() {
  if (!S.isHost || !S.pendingKickTargetId) return;
  send({ type: 'kick_player', target_id: S.pendingKickTargetId });
  closeKickConfirm();
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
  saveBidSelection();
  refreshBidInputUI();
}

function adjBid(which, delta) {
  if (which === 'q') {
    const min = minQtyForFace(S.bidFace);
    S.bidQty = Math.max(min, S.bidQty + delta);
  }
  saveBidSelection();
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

/**
 * Probabilidad de que haya AL MENOS `qty` dados mostrando `face` en la mesa,
 * dado lo que el jugador local ya sabe (sus propios dados).
 * Usa distribución binomial acumulada sobre los dados desconocidos.
 * face=1 (ases) es wildcard: p=1/3 por dado desconocido.
 * Para caras regulares (2-6): un dado desconocido lo muestra con p=1/6+1/6=2/6=1/3
 * cuando los ases también son comodines, o 1/6 cuando la ronda es "palilos" sin ases.
 * Simplificación: asumimos ases como wildcard siempre (regla estándar).
 */
function bidProbability(qty, face, totalDice, myDice) {
  if (!myDice || myDice.length === 0 || totalDice <= 0) return null;
  // Dados propios que cuentan para esta cara
  const myCount = myDice.filter(d => d === face || (face !== 1 && d === 1)).length;
  const unknown = totalDice - myDice.length;
  const need    = Math.max(0, qty - myCount);

  // Si ya tengo suficientes con los propios, es certeza
  if (need <= 0) return 1.0;
  // Si necesito más dados de los que existen como desconocidos, imposible
  if (need > unknown) return 0.0;

  // p por dado desconocido: ases=1/3 (1 cara), regular=2/6=1/3 (cara+ases)
  const p = face === 1 ? 1/6 : 2/6;

  // P(X >= need) = 1 - P(X <= need-1), X~Binomial(unknown, p)
  // Calcular P(X <= need-1) sumando pmf
  let cdf = 0;
  let logP = Math.log(p), log1P = Math.log(1 - p);
  // Precompute log binomial coefficients via log-gamma approximation
  function logFactorial(n) {
    if (n <= 1) return 0;
    let s = 0;
    for (let i = 2; i <= n; i++) s += Math.log(i);
    return s;
  }
  const logN = logFactorial(unknown);
  for (let k = 0; k < need; k++) {
    const logBinom = logN - logFactorial(k) - logFactorial(unknown - k);
    const logPmf   = logBinom + k * logP + (unknown - k) * log1P;
    cdf += Math.exp(logPmf);
  }
  return Math.max(0, Math.min(1, 1 - cdf));
}

function updateBidProb() {
  const el = document.getElementById('bid-prob');
  if (!el) return;
  const isMyTurn = S.currentPid === S.playerId && S.phase === 'playing';
  if (!isMyTurn || !S.myDice || S.myDice.length === 0) {
    el.style.display = 'none';
    return;
  }
  const prob = bidProbability(S.bidQty, S.bidFace, S.totalDice, S.myDice);
  if (prob === null) { el.style.display = 'none'; return; }
  const pct = Math.round(prob * 100);
  // Color: verde >60%, amarillo 30-60%, rojo <30%
  el.className = 'bid-prob ' + (pct >= 60 ? 'bid-prob-high' : pct >= 30 ? 'bid-prob-mid' : 'bid-prob-low');
  el.textContent = `~${pct}%`;
  el.style.display = 'inline-block';
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

  updateBidProb();
}

// ══════════════════════════════════  ACTIONS  ════════════════════════════════
function saveBidSelection() {
  if (S.isSpectator || !S.currentPid || S.currentPid !== S.playerId) return;
  send({ type: 'select_bid', quantity: S.bidQty, face: S.bidFace });
}

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

function applyEliminatedMode(eliminated) {
  const bidPanel  = document.getElementById('bid-panel');
  const elimPanel = document.getElementById('eliminated-panel');
  if (bidPanel)  bidPanel.style.display  = eliminated ? 'none' : '';
  if (elimPanel) elimPanel.style.display = eliminated ? 'flex' : 'none';
}

// ══════════════════════════════════  LOBBY ACTIONS  ════════════════════════════
function joinRoom() {
  const name = document.getElementById('inp-name').value.trim();
  const room = document.getElementById('inp-room').value.trim();
  if (!name) { showToast('Ingresa tu nombre', true); return; }
  if (!room) { showToast('Ingresa el código de sala', true); return; }
  S.playerName = name;
  S.playerAvatar = AVATAR_OPTIONS.includes(S.playerAvatar) ? S.playerAvatar : '🎲';
  S.roomId = room;
  // Guardar nombre inmediatamente, antes de conectar
  persistLobbyIdentity(name);
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
    allow_throwable_emojis: !!(src.allow_throwable_emojis ?? DEFAULT_RULES.allow_throwable_emojis),
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
    {
      label: `Emojis lanzables: ${rules.allow_throwable_emojis ? 'Si' : 'No'}`,
      detail: rules.allow_throwable_emojis
        ? 'Los jugadores pueden lanzar emojis a otros durante la partida.'
        : 'Los emojis lanzables estan desactivados en esta sala.',
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
  const emojiEl = document.getElementById('rule-allow-throwable-emojis');
  const timeoutInputs = document.querySelectorAll('#rule-turn-timeout input[name="turn-timeout"]');
  if (modeEl)    { modeEl.checked = rules.elimination_mode === 'loser'; modeEl.disabled = !hostCanEdit; }
  if (gavilanEl) { gavilanEl.checked = rules.allow_gavilan;             gavilanEl.disabled = !hostCanEdit; }
  if (calzoEl)   { calzoEl.checked = rules.calzo_recovers_on_turn;     calzoEl.disabled = !hostCanEdit; }
  if (emojiEl)   { emojiEl.checked = rules.allow_throwable_emojis;     emojiEl.disabled = !hostCanEdit; }
  timeoutInputs.forEach((input) => {
    input.checked = Number(input.value) === rules.turn_timeout_seconds;
    input.disabled = !hostCanEdit;
  });

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
  const timeoutSelected = document.querySelector('#rule-turn-timeout input[name="turn-timeout"]:checked');
  const next = {
    elimination_mode: document.getElementById('rule-elimination-loser')?.checked ? 'loser' : 'winner',
    allow_gavilan: !!document.getElementById('rule-allow-gavilan')?.checked,
    calzo_recovers_on_turn: !!document.getElementById('rule-calzo-on-turn')?.checked,
    turn_timeout_seconds: Number(timeoutSelected?.value || 0),
    allow_throwable_emojis: !!document.getElementById('rule-allow-throwable-emojis')?.checked,
  };
  S.rules = normalizeRules(next);
  saveRulesToStorage(S.rules);
  renderLobbyRules();
  send({ type: 'set_rules', rules: S.rules });
}

function copyRoomCode() {
  playSfx('click');
  const shareUrl = `${location.origin}/?sala=${encodeURIComponent(S.roomId)}`;
  const btn = document.getElementById('btn-copy-room');
  const doCheck = () => {
    if (btn) {
      btn.innerHTML = '<i class="fa-solid fa-check" aria-hidden="true"></i>Copiado';
      setTimeout(() => {
        btn.innerHTML = '<i class="fa-regular fa-copy" aria-hidden="true"></i>Copiar';
      }, 1500);
    }
  };
  navigator.clipboard.writeText(shareUrl)
    .then(() => { showToast('Enlace de sala copiado'); doCheck(); })
    .catch(() => showToast(shareUrl));
}

// ══════════════════════════════════  UTILS  ══════════════════════════════════
function showScreen(name) {
  if (name !== 'game') resetEmojiPopup();
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
window.openStatsModal = openStatsModal;
window.closeStatsModal = closeStatsModal;
window.openNotificationModal = openNotificationModal;
window.acceptNotificationPrompt = acceptNotificationPrompt;
window.rejectNotificationPrompt = rejectNotificationPrompt;
window.toggleAvatarPicker = toggleAvatarPicker;
window.closeKickConfirm = closeKickConfirm;
window.confirmKickPlayer = confirmKickPlayer;

// Pre-rellenar formulario con la sesión guardada y guardar nombre en tiempo real
(function () {
  const session = loadSession();
  const roomFromUrl = new URLSearchParams(window.location.search).get('sala');
  const nameEl = document.getElementById('inp-name');
  const roomEl = document.getElementById('inp-room');
  if (nameEl && session?.name) nameEl.value = session.name;
  if (roomEl) {
    roomEl.value = roomFromUrl || session?.room || '';
  }
  if (session?.avatar && AVATAR_OPTIONS.includes(session.avatar)) {
    // Ensure saved avatar is still unlocked; if not, reset to 🎲
    S.playerAvatar = isAvatarUnlocked(session.avatar) ? session.avatar : '🎲';
  }
  renderAvatarPicker();
  renderLevelBadge();

  // Guardar nombre en tiempo real al escribir
  if (nameEl) {
    nameEl.addEventListener('input', () => {
      const name = nameEl.value.trim();
      if (!name) return;
      persistLobbyIdentity(name);
    });
  }
})();

// Desbloquea audio en la primera interacción del usuario (requisito del navegador).
['pointerdown', 'keydown'].forEach(evt => {
  window.addEventListener(evt, unlockAudio, { once: true });
});

// Inicializar hover de emojis una sola vez al cargar (cubre reconexiones y espectadores)
maybeInitEmojiHover();

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    stopTurnTitleBlink();
    if (_activeNotification) { _activeNotification.close(); _activeNotification = null; }
  }
});

window.addEventListener('focus', stopTurnTitleBlink);

window.addEventListener('beforeunload', () => {
  stopTurnTitleBlink();
  S.manualClose = true;
  if (S.ws && S.ws.readyState === WebSocket.OPEN) {
    S.ws.close();
  }
});

