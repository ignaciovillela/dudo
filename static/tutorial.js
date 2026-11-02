'use strict';

// ════════════════════════════  MANUAL INTERACTIVO  ════════════════════════════
// Tutorial paso a paso con mini-ejercicios. Usa makeDie() de app.js.
(() => {
  const SEEN_KEY = 'dudo_tutorial_seen';
  const FACE = { 1: 'As', 2: 'Tonto', 3: 'Tren', 4: 'Cuadra', 5: 'Quina', 6: 'Cena' };
  const FACE_PL = { 1: 'ases', 2: 'tontos', 3: 'trenes', 4: 'cuadras', 5: 'quinas', 6: 'cenas' };

  let stepIdx = 0;
  let lastFocus = null;

  // ── Helpers ────────────────────────────────────────────────────────────────
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v; // solo texto estático del tutorial
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c != null) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return el;
  }

  function diceRow(values, opts = {}) {
    return h('div', { class: 'tut-dice' + (opts.small ? ' tut-dice--sm' : '') },
      values.map(v => makeDie(v, { size: 'sm', matchFace: opts.matchFace ?? null })));
  }

  function bidChip(q, f) {
    return h('span', { class: 'tut-bid' }, `${q} ×`, makeDie(f, { size: 'sm' }), FACE[f]);
  }

  function feedback(ok, html) {
    return h('div', { class: `tut-feedback ${ok ? 'tut-feedback--ok' : 'tut-feedback--bad'}`, role: 'status', html });
  }

  function countFace(dice, face) {
    return dice.filter(d => d === face || (face !== 1 && d === 1)).length;
  }

  function sfx() { if (typeof playSfx === 'function') playSfx('click'); }

  // Misma lógica que Game.is_valid_bid en game/models.py
  function checkBid(old, bid) {
    if (bid.q < 1) return [false, 'La cantidad mínima es 1.'];
    if (old.f !== 1 && bid.f === 1) {
      const min = Math.ceil(old.q / 2);
      return bid.q >= min
        ? [true, `Pasar a ases: basta la mitad redondeada hacia arriba (${old.q} ÷ 2 → <strong>${min}</strong>).`]
        : [false, `Para pasar a ases necesitas al menos <strong>${min}</strong> (la mitad de ${old.q}, redondeada hacia arriba).`];
    }
    if (old.f === 1 && bid.f !== 1) {
      const min = old.q * 2 + 1;
      return bid.q >= min
        ? [true, `Salir de ases: el doble más uno (${old.q} × 2 + 1 = <strong>${min}</strong>).`]
        : [false, `Para salir de ases necesitas al menos <strong>${min}</strong> (${old.q} × 2 + 1).`];
    }
    if (bid.q > old.q) return [true, 'Subiste la cantidad: con eso vale cualquier pinta.'];
    if (bid.q === old.q && bid.f > old.f) return [true, 'Misma cantidad con una pinta mayor.'];
    if (bid.q === old.q && bid.f === old.f) return [false, 'Es la misma apuesta: tienes que subir algo.'];
    if (bid.q === old.q) return [false, `Con la misma cantidad, la pinta debe ser mayor que ${FACE[old.f]}.`];
    return [false, 'No puedes bajar la cantidad (salvo al pasar a ases).'];
  }

  // ── Componentes interactivos ───────────────────────────────────────────────
  function rollDemo() {
    const wrap = h('div', { class: 'tut-demo' });
    const dice = h('div', { class: 'tut-dice' }, [0, 0, 0, 0, 0].map(() => makeDie(null, { size: 'sm' })));
    const note = h('p', { class: 'tut-note' }, 'Tus dados están tapados por el cacho (el vaso). Solo tú los ves.');
    const btn = h('button', {
      class: 'btn btn-gold tut-btn', type: 'button', onclick: () => {
        sfx();
        dice.replaceChildren(...Array.from({ length: 5 }, () => {
          const d = makeDie(1 + Math.floor(Math.random() * 6), { size: 'sm' });
          d.classList.add('rolling');
          return d;
        }));
        btn.innerHTML = '<i class="fa-solid fa-dice" aria-hidden="true"></i> Lanzar otra vez';
        note.textContent = 'Así ves tus dados durante la ronda. Los de los demás siguen ocultos.';
      },
    });
    btn.innerHTML = '<i class="fa-solid fa-dice" aria-hidden="true"></i> Lanzar dados';
    wrap.append(dice, btn, note);
    return wrap;
  }

  function countQuiz() {
    const table = [5, 1, 3, 6, 2, 5, 1, 4, 5, 2];
    const answer = countFace(table, 5);
    const wrap = h('div', { class: 'tut-demo' });
    const diceBox = h('div', {}, diceRow(table));
    const out = h('div');
    const opts = h('div', { class: 'tut-options' });
    [3, 4, 5, 6].forEach(n => {
      opts.appendChild(h('button', {
        class: 'btn tut-opt', type: 'button', onclick: () => {
          sfx();
          diceBox.replaceChildren(diceRow(table, { matchFace: 5 }));
          opts.querySelectorAll('button').forEach(b => { b.disabled = true; });
          out.replaceChildren(n === answer
            ? feedback(true, `¡Correcto! Hay 3 quinas y 2 ases que valen como quina: <strong>${answer}</strong>.`)
            : feedback(false, `Son <strong>${answer}</strong>: 3 quinas + 2 ases (los ases son comodines). Mira los dados destacados.`));
        },
      }, String(n)));
    });
    wrap.append(h('p', { class: 'tut-q' }, 'Al final de la ronda estos son todos los dados de la mesa. ¿Cuántas quinas hay?'),
      diceBox, opts, out);
    return wrap;
  }

  function bidPractice() {
    const challenges = [
      { cur: { q: 3, f: 3 }, prompt: 'La apuesta es 3 × Tren. Sube la apuesta.' },
      { cur: { q: 4, f: 6 }, prompt: 'Ahora es 4 × Cena: ya no hay pinta mayor. ¿Qué puedes decir?' },
      { cur: { q: 5, f: 4 }, prompt: 'Es 5 × Cuadra. Prueba pasar a ases.', need: 'ases' },
      { cur: { q: 2, f: 1 }, prompt: 'Es 2 × As. Vuelve a una pinta normal.', need: 'normal' },
    ];
    let ci = 0;
    let pick;
    const wrap = h('div', { class: 'tut-demo' });

    function render() {
      const ch = challenges[ci];
      pick = pick || { ...ch.cur };
      const qtyVal = h('span', { class: 'tut-qty-val', 'aria-live': 'polite' }, String(pick.q));
      const step = d => () => { pick.q = Math.max(1, Math.min(20, pick.q + d)); qtyVal.textContent = String(pick.q); };
      const faces = h('div', { class: 'tut-faces', role: 'group', 'aria-label': 'Pinta' });
      for (let f = 1; f <= 6; f++) {
        const b = h('button', {
          class: 'tut-face' + (pick.f === f ? ' is-on' : ''), type: 'button',
          'aria-pressed': String(pick.f === f), title: FACE[f], 'aria-label': FACE[f],
          onclick: () => {
            pick.f = f;
            faces.querySelectorAll('.tut-face').forEach((el, i) => {
              el.classList.toggle('is-on', i + 1 === f);
              el.setAttribute('aria-pressed', String(i + 1 === f));
            });
          },
        }, makeDie(f, { size: 'sm' }));
        faces.appendChild(b);
      }
      const out = h('div');
      const send = h('button', {
        class: 'btn btn-gold tut-btn', type: 'button', onclick: () => {
          sfx();
          const [ok, msg] = checkBid(ch.cur, pick);
          if (!ok) { out.replaceChildren(feedback(false, msg)); return; }
          if (ch.need === 'ases' && pick.f !== 1) {
            out.replaceChildren(feedback(false, 'Esa apuesta vale, pero el reto es pasar a ases: elige el <strong>As</strong>.'));
            return;
          }
          if (ch.need === 'normal' && pick.f === 1) {
            out.replaceChildren(feedback(false, 'Esa apuesta vale, pero el reto es volver a una pinta normal (Tonto a Cena).'));
            return;
          }
          const last = ci === challenges.length - 1;
          out.replaceChildren(feedback(true, msg + (last ? ' <br>¡Ya dominas las apuestas!' : '')));
          send.disabled = true;
          if (!last) {
            out.appendChild(h('button', {
              class: 'btn tut-opt tut-next-challenge', type: 'button',
              onclick: () => { ci++; pick = null; render(); },
            }, 'Siguiente reto →'));
          }
        },
      }, 'Apostar');

      wrap.replaceChildren(
        h('p', { class: 'tut-q' }, h('span', { class: 'tut-pill' }, `Reto ${ci + 1}/${challenges.length}`), ' ', ch.prompt),
        h('div', { class: 'tut-current' }, 'Apuesta actual: ', bidChip(ch.cur.q, ch.cur.f)),
        h('div', { class: 'tut-builder' },
          h('div', { class: 'tut-qty' },
            h('button', { class: 'btn tut-step', type: 'button', 'aria-label': 'Menos', onclick: step(-1) }, '−'),
            qtyVal,
            h('button', { class: 'btn tut-step', type: 'button', 'aria-label': 'Más', onclick: step(1) }, '+')),
          h('span', { class: 'tut-x' }, '×'),
          faces),
        send, out);
    }
    render();
    return wrap;
  }

  function scenario({ bidder, bid, mine, others }) {
    const all = mine.concat(others);
    const total = countFace(all, bid.f);
    const wrap = h('div', { class: 'tut-demo' });
    const othersBox = h('div', {}, diceRow(others.map(() => null)));
    const mineBox = h('div', {}, diceRow(mine));
    const out = h('div');
    const choose = kind => () => {
      sfx();
      btns.querySelectorAll('button').forEach(b => { b.disabled = true; });
      othersBox.replaceChildren(diceRow(others, { matchFace: bid.f }));
      mineBox.replaceChildren(diceRow(mine, { matchFace: bid.f }));
      const pl = FACE_PL[bid.f];
      const extra = bid.f !== 1 ? ' (contando los ases)' : '';
      let fb;
      if (kind === 'dudo') {
        fb = total < bid.q
          ? feedback(true, `¡Bien dudado! Hay <strong>${total}</strong> ${pl}${extra}, menos de ${bid.q}. <strong>${bidder}</strong> pierde un dado.`)
          : feedback(false, `Había <strong>${total}</strong> ${pl}${extra}: la apuesta se cumplía. Al dudar mal, <strong>tú</strong> pierdes un dado.`);
      } else {
        fb = total === bid.q
          ? feedback(true, `¡Calzo exacto! Hay justo <strong>${total}</strong> ${pl}${extra}. No pierdes nada y puedes recuperar un dado (según las reglas de la sala).`)
          : feedback(false, `Había <strong>${total}</strong> ${pl}${extra}, no exactamente ${bid.q}. Al fallar un calzo, <strong>tú</strong> pierdes un dado.`);
      }
      out.replaceChildren(fb);
    };
    const btns = h('div', { class: 'tut-options' },
      h('button', { class: 'btn tut-opt tut-opt--dudo', type: 'button', onclick: choose('dudo') }, '¡Dudo!'),
      h('button', { class: 'btn tut-opt tut-opt--calzo', type: 'button', onclick: choose('calzo') }, '¡Calzo!'));
    wrap.append(
      h('div', { class: 'tut-current' }, `${bidder} apuesta: `, bidChip(bid.q, bid.f)),
      h('p', { class: 'tut-label' }, 'Dados de los demás (ocultos)'), othersBox,
      h('p', { class: 'tut-label' }, 'Tus dados'), mineBox,
      h('p', { class: 'tut-q' }, '¿Qué haces?'), btns, out);
    return wrap;
  }

  function pasoQuiz() {
    const hands = [
      { dice: [1, 2, 3, 4, 5], ok: true,  why: 'Todos distintos.' },
      { dice: [3, 3, 3, 6, 6], ok: true,  why: 'Full: tres de un valor y dos de otro.' },
      { dice: [2, 2, 4, 5, 6], ok: false, why: 'Un par suelto no es ninguna combinación.' },
      { dice: [1, 6, 6, 6, 6], ok: false, why: 'Para el paso el as <strong>no</strong> es comodín: son cuatro cenas y un as.' },
    ];
    const wrap = h('div', { class: 'tut-demo tut-hands' });
    hands.forEach(hand => {
      const out = h('div', { class: 'tut-hand-out' });
      const row = h('div', { class: 'tut-hand' }, diceRow(hand.dice, { small: true }));
      const answer = said => () => {
        sfx();
        row.querySelectorAll('button').forEach(b => { b.disabled = true; });
        out.replaceChildren(feedback(said === hand.ok,
          `${said === hand.ok ? '¡Bien!' : 'No.'} ${hand.ok ? 'Puede pasar' : 'No puede pasar'}: ${hand.why}`));
      };
      row.appendChild(h('div', { class: 'tut-hand-btns' },
        h('button', { class: 'btn tut-opt', type: 'button', onclick: answer(true) }, 'Puede pasar'),
        h('button', { class: 'btn tut-opt', type: 'button', onclick: answer(false) }, 'No')));
      wrap.append(row, out);
    });
    return wrap;
  }

  function cards(items) {
    return h('div', { class: 'tut-cards' }, items.map(([icon, title, text]) =>
      h('div', { class: 'tut-card' },
        h('i', { class: `fa-solid ${icon}`, 'aria-hidden': 'true' }),
        h('strong', {}, title),
        h('span', { html: text }))));
  }

  // ── Pasos ──────────────────────────────────────────────────────────────────
  const STEPS = [
    {
      title: 'El objetivo',
      render: () => [
        h('p', { html: 'Cada jugador empieza con <strong>5 dados</strong>. Quien se equivoca pierde un dado. <strong>Gana el último que conserve dados.</strong>' }),
        rollDemo(),
      ],
    },
    {
      title: 'Las pintas',
      render: () => [
        h('p', {}, 'Cada cara del dado tiene un nombre. Los vas a escuchar todo el rato:'),
        h('div', { class: 'tut-faces-grid' }, [1, 2, 3, 4, 5, 6].map(f =>
          h('div', { class: 'tut-face-name' }, makeDie(f, { size: 'sm' }), h('span', {}, FACE[f])))),
      ],
    },
    {
      title: 'Los ases son comodines',
      render: () => [
        h('p', { html: 'Se apuesta sobre <strong>todos los dados de la mesa</strong>, no solo los tuyos. Los <strong>ases</strong> cuentan como cualquier otra pinta. Si la apuesta es de ases, solo cuentan los ases.' }),
        countQuiz(),
      ],
    },
    {
      title: 'Tu turno',
      render: () => [
        h('p', {}, 'En tu turno haces exactamente una de estas cuatro cosas:'),
        cards([
          ['fa-arrow-trend-up', 'Apostar', 'Dices cuántos dados de una pinta crees que hay en la mesa, por ejemplo <em>4 × Quina</em>.'],
          ['fa-hand', 'Dudar', 'Crees que la última apuesta es mentira. Se revelan los dados.'],
          ['fa-bullseye', 'Calzar', 'Crees que la cantidad es <em>exacta</em>. Arriesgado, pero puedes recuperar un dado.'],
          ['fa-forward', 'Pasar', 'Una vez por ronda, si tu mano es especial. Lo vemos más adelante.'],
        ]),
        h('p', { class: 'tut-note' }, 'El primer jugador de cada ronda elige el sentido de los turnos (↻ o ↺).'),
      ],
    },
    {
      title: 'Subir la apuesta',
      render: () => [
        h('p', { html: 'Cada apuesta debe ser <strong>mayor</strong> que la anterior: <strong>más cantidad</strong> (con cualquier pinta) o <strong>la misma cantidad con una pinta mayor</strong>. Para los ases hay atajos: entrar cuesta la mitad y salir cuesta el doble más uno.' }),
        bidPractice(),
      ],
    },
    {
      title: '¡Dudo!',
      render: () => [
        h('p', { html: 'Si dudas, se revelan todos los dados. Si hay <strong>menos</strong> de lo apostado, pierde quien apostó. Si hay <strong>igual o más</strong>, pierdes tú.' }),
        scenario({ bidder: 'Ana', bid: { q: 5, f: 4 }, mine: [4, 1, 2, 6, 6], others: [4, 3, 1, 5, 2] }),
      ],
    },
    {
      title: '¡Calzo!',
      render: () => [
        h('p', { html: 'Calzar es apostar a que hay <strong>exactamente</strong> esa cantidad. Si aciertas no pierdes nada y puedes recuperar un dado (máximo 5). Si fallas, pierdes uno. Quien apostó nunca pierde en un calzo.' }),
        scenario({ bidder: 'Beto', bid: { q: 3, f: 5 }, mine: [5, 5, 2, 3, 6], others: [1, 4, 4, 2, 6] }),
      ],
    },
    {
      title: 'El paso',
      render: () => [
        h('p', { html: 'Una vez por ronda puedes <strong>pasar</strong> en vez de apostar, pero solo si tienes los 5 dados y tu mano es <strong>toda distinta</strong>, <strong>toda igual</strong> o un <strong>full</strong> (3 + 2). Nadie lo revisa… salvo que alguien dude tu paso. ¿Quién puede pasar?' }),
        pasoQuiz(),
      ],
    },
    {
      title: 'Reglas de la sala',
      render: () => [
        h('p', {}, 'Antes de empezar, el anfitrión puede ajustar algunas reglas:'),
        cards([
          ['fa-feather-pointed', 'Gavilán', 'Permite dudar o calzar <em>fuera de tu turno</em>. ¡Atento a la mesa!'],
          ['fa-trophy', 'Modo ganador o perdedor', 'Gana el último con dados, o la partida termina con el primer eliminado.'],
          ['fa-stopwatch', 'Tiempo por turno', 'Sin límite, 30, 60 o 90 segundos.'],
          ['fa-ghost', 'Gavilán fantasma', 'Los eliminados pueden intentar volver con un dudo o calzo fuera de turno.'],
        ]),
        h('p', { class: 'tut-note', html: 'Dentro de la sala, toca <i class="fa-regular fa-circle-question" aria-hidden="true"></i> en cada regla para ver el detalle.' }),
      ],
    },
    {
      title: '¡Listo para jugar!',
      render: () => [
        h('div', { class: 'tut-final' },
          diceRow([6, 6, 1]),
          h('p', { html: '<strong>Resumen:</strong> apuesta sobre todos los dados de la mesa, recuerda que los ases son comodines, y duda cuando algo no te cuadre.' }),
          ...practiceCta()),
      ],
    },
  ];

  // Botón "Practicar contra bots": solo desde la pantalla inicial (sin sala aún).
  function practiceCta() {
    const form = document.getElementById('lobby-form');
    const canPractice = typeof window.startPracticeGame === 'function'
      && form && form.style.display !== 'none'
      && document.getElementById('lobby-screen')?.classList.contains('active');
    if (!canPractice) {
      return [h('p', { class: 'tut-note' }, 'Consejo: practica en una sala con bots fáciles antes de jugar con amigos.')];
    }
    return [
      h('button', {
        class: 'btn btn-gold tut-practice', type: 'button',
        html: '<i class="fa-solid fa-robot" aria-hidden="true"></i> Practicar contra 2 bots fáciles',
        onclick: () => {
          closeTutorial();
          window.startPracticeGame(2);
        },
      }),
      h('p', { class: 'tut-note' }, 'Crea una sala privada solo para ti y empieza la partida al tiro.'),
    ];
  }

  // ── Modal ──────────────────────────────────────────────────────────────────
  function renderStep() {
    const step = STEPS[stepIdx];
    const total = STEPS.length;
    document.getElementById('tut-title').textContent = step.title;
    document.getElementById('tut-count').textContent = `${stepIdx + 1} / ${total}`;
    document.getElementById('tut-progress-bar').style.width = `${((stepIdx + 1) / total) * 100}%`;
    const body = document.getElementById('tut-body');
    body.replaceChildren(...step.render());
    body.scrollTop = 0;

    const prev = document.getElementById('tut-prev');
    const next = document.getElementById('tut-next');
    prev.disabled = stepIdx === 0;
    const last = stepIdx === total - 1;
    next.innerHTML = last
      ? '<i class="fa-solid fa-dice" aria-hidden="true"></i> ¡A jugar!'
      : 'Siguiente <i class="fa-solid fa-arrow-right" aria-hidden="true"></i>';

    const dots = document.getElementById('tut-dots');
    dots.replaceChildren(...STEPS.map((s, i) => h('button', {
      class: 'tut-dot' + (i === stepIdx ? ' is-on' : '') + (i < stepIdx ? ' is-done' : ''),
      type: 'button', 'aria-label': `Ir a: ${s.title}`,
      ...(i === stepIdx ? { 'aria-current': 'step' } : {}),
      onclick: () => { stepIdx = i; renderStep(); },
    })));

    if (last) markSeen();
  }

  function markSeen() {
    try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* sin storage */ }
    document.querySelectorAll('.tut-new-badge').forEach(b => b.remove());
  }

  function onKey(e) {
    const modal = document.getElementById('tutorial-modal');
    if (!modal || modal.style.display === 'none') return;
    if (e.key === 'Escape') { e.preventDefault(); closeTutorial(); }
    else if (e.key === 'ArrowRight' && !isTyping(e)) { e.preventDefault(); go(1); }
    else if (e.key === 'ArrowLeft' && !isTyping(e)) { e.preventDefault(); go(-1); }
    else if (e.key === 'Tab') trapFocus(e, modal);
  }

  function isTyping(e) {
    const t = e.target;
    return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA');
  }

  function trapFocus(e, modal) {
    const items = [...modal.querySelectorAll('button:not([disabled]), [href], input, [tabindex]:not([tabindex="-1"])')];
    if (!items.length) return;
    const first = items[0];
    const lastEl = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
    else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
  }

  function go(delta) {
    const nextIdx = stepIdx + delta;
    if (nextIdx >= STEPS.length) { closeTutorial(); return; }
    if (nextIdx < 0) return;
    stepIdx = nextIdx;
    sfx();
    renderStep();
  }

  function openTutorial() {
    const modal = document.getElementById('tutorial-modal');
    if (!modal) return;
    lastFocus = document.activeElement;
    stepIdx = 0;
    renderStep();
    modal.style.display = 'flex';
    document.addEventListener('keydown', onKey);
    document.getElementById('tut-next').focus();
  }

  function closeTutorial() {
    const modal = document.getElementById('tutorial-modal');
    if (modal) modal.style.display = 'none';
    document.removeEventListener('keydown', onKey);
    if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
  }

  // Cerrar al hacer clic fuera de la caja
  document.addEventListener('click', e => {
    if (e.target && e.target.id === 'tutorial-modal') closeTutorial();
  });

  // Insignia "Nuevo" en los botones del manual para quien nunca lo vio
  (function showNewBadge() {
    let seen = false;
    try { seen = localStorage.getItem(SEEN_KEY) === '1'; } catch { /* sin storage */ }
    if (seen) return;
    document.querySelectorAll('[data-tutorial-badge]').forEach(btn => {
      btn.appendChild(h('span', { class: 'tut-new-badge' }, 'Nuevo'));
    });
  })();

  window.openTutorial = openTutorial;
  window.closeTutorial = closeTutorial;
  window.tutorialGo = go;
  // Para pruebas
  window.__tutorial = { checkBid, countFace, STEPS };
})();
