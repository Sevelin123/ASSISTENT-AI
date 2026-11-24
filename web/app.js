/* ══════════════════════════════════════════════════════════════════
   J.A.R.V.I.S. HUD — voice input/output, telemetry, settings, agent link
   Vanilla JS. No build step, no dependencies.
   ══════════════════════════════════════════════════════════════════ */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const app = $('app');

  const state = {
    config: null, status: null, catalogue: null,
    enabled: false, listening: false, speaking: false, thinking: false,
    muted: false, mode: 'push', armed: false, srAvailable: false,
    rec: null, shouldRestart: false, finalBuf: '', interim: '',
    finalizeTimer: null, level: 0, analyser: null, audioCtx: null, micStream: null,
    voices: [], voiceList: [], voiceWarned: false, lastReply: '', keyHeld: false,
  };

  const QUICK = [
    { label: 'Что ты умеешь?', text: 'что ты умеешь' },
    { label: 'Который час?', text: 'который час' },
    { label: 'Статус системы', text: 'статус системы' },
    { label: 'Открой YouTube', text: 'открой youtube.com' },
    { label: 'Найди файлы', text: 'найди файл отчёт' },
    { label: 'Список дел', text: 'список дел' },
    { label: 'Посчитай 15% от 240', text: 'посчитай 15 процентов от 240' },
    { label: 'Напомни через 5 мин', text: 'напомни через 5 минут размяться' },
    { label: 'Запомни имя', text: 'запомни, что меня зовут Тони' },
    { label: 'Скриншот', text: 'сделай скриншот' },
    { label: 'Расскажи анекдот', text: 'расскажи анекдот' },
    { label: 'Громкость 40', text: 'громкость 40' },
  ];

  const EXAMPLES = [
    'Джарвис, открой блокнот', 'Джарвис, какой сегодня день?', 'Загугли рецепт пасты',
    'Напомни через 10 минут про созвон', 'Добавь задачу позвонить маме',
    'Запомни, что я работаю ночами', 'Покажи заметки', 'Посчитай 2 в степени 10',
    'Найди файл презентация', 'Выключи озвучивание', 'Включи постоянное прослушивание',
    'Сделай тише', 'Скопируй в буфер текст привет', 'Что ты помнишь?',
    'Найди на YouTube лекции по физике', 'Объясни, что такое нейросеть',
  ];

  // ───────────────────────────────────────────── API & helpers
  function hideServerAlert() {
    const el = $('serverAlert');
    if (el) el.hidden = true;
  }

  function serverDiagnosis(err) {
    const why = err?.message || 'сеть недоступна';
    if (location.protocol === 'file:') {
      return `HUD открыт как файл (${why}). Так нельзя: браузер ищет /api/… на диске. `
        + 'Закройте вкладку и откройте http://127.0.0.1:8080 после INSTALL_WINDOWS.bat. '
        + 'Если сервер не поднялся — двойной клик по FIX-SERVER.bat.';
    }
    if (/e2b\.app/.test(location.hostname)) {
      return `Облачный предпросмотр выключен (${why}). Откройте локальный http://127.0.0.1:8080 `
        + 'или скачайте архив с GitHub и запустите INSTALL_WINDOWS.bat.';
    }
    if (/^(localhost|::1)$/i.test(location.hostname)) {
      return `Вы открыли localhost (${why}), а сервер слушает 127.0.0.1. `
        + 'Замените адрес в строке браузера на http://127.0.0.1:8080 — на Windows localhost часто уходит в IPv6 ::1.';
    }
    return `Локальный сервер не отвечает (${why}). Откройте именно http://127.0.0.1:8080, `
      + 'запустите FIX-SERVER.bat двойным кликом (он проверит порт, Python и перезапустит сервисы), '
      + 'при занятом порту используйте FIX-SERVER.bat -Port 9000. Не используйте file:// и старые ссылки *.e2b.app.';
  }

  function showServerAlert(err) {
    const el = $('serverAlert');
    if (!el) return;
    const text = $('serverAlertText');
    if (text) text.textContent = serverDiagnosis(err);
    el.hidden = false;
  }

  async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
      const r = await fetch(path, opts);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      hideServerAlert();
      return data;
    } catch (err) {
      showServerAlert(err);
      throw err;
    }
  }

  const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function toast(text, kind = '') {
    const el = document.createElement('div');
    el.className = 'toast ' + kind;
    el.textContent = text;
    $('toasts').appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateX(20px)'; el.style.transition = '.3s'; }, 3600);
    setTimeout(() => el.remove(), 4100);
  }

  function setClass(name, on) { app.classList.toggle(name, !!on); }

  function setStage(text) { $('stageLabel').textContent = text; }
  function setCore(text) { $('coreSub').textContent = text; }

  function setTranscript(text, cls = '') {
    const el = $('transcript');
    el.textContent = text;
    el.className = 'transcript ' + cls;
  }

  // ───────────────────────────────────────────── chat rendering
  function addMsg(role, text, ts = '') {
    const chat = $('chat');
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + role;
    const who = role === 'user' ? 'ВЫ' : role === 'assistant' ? 'J.A.R.V.I.S.' : 'СИСТЕМА';
    wrap.innerHTML = `<span class="who">${who}${ts ? ' · ' + escapeHtml(ts) : ''}</span>
                      <div class="bubble">${escapeHtml(text)}</div>`;
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  function renderActions(actions) {
    const box = $('actionCards');
    box.innerHTML = '';
    (actions || []).slice(0, 5).forEach((a) => {
      const el = document.createElement('div');
      el.className = 'action-card' + (a.ok ? '' : ' fail');
      const target = a.target === 'pc' ? 'ПК' : a.target === 'demo' ? 'ДЕМО' : 'СЕРВЕР';
      el.innerHTML = `<i class="badge"></i><b>${escapeHtml(a.name)}</b>
                      <span>${escapeHtml(a.message || '')}</span>
                      <em style="opacity:.5;margin-left:auto;font-size:8px">${target}</em>`;
      box.appendChild(el);
    });
  }

  async function loadHistory() {
    try {
      const data = await api('/api/history?limit=60');
      $('chat').innerHTML = '';
      (data.history || []).forEach((m) => addMsg(m.role, m.text));
      if (!data.history || !data.history.length) {
        addMsg('system', 'Система инициализирована. Говорите или введите команду.');
      }
    } catch (e) { /* offline server shows its own error */ }
  }

  // ───────────────────────────────────────────── main send
  async function send(text, source = 'text') {
    text = (text || '').trim();
    if (!text) return;
    addMsg('user', text);
    $('userInput').value = '';
    state.lastReply = '';
    setThinking(true);
    setTranscript(text, 'active');
    setStage('ОБРАБОТКА ЗАПРОСА');
    try {
      const res = await api('/api/chat', 'POST', { text, source });
      state.lastReply = res.reply;
      addMsg('assistant', res.reply);
      renderActions(res.actions);
      setTranscript(res.reply.replace(/\s+/g, ' ').slice(0, 220), 'active');
      setStage(res.pending ? 'ОЖИДАЮ ПОДТВЕРЖДЕНИЯ' : 'ГОТОВ К КОМАНДАМ');
      if (res.pending) toast('Скажите «подтверждаю» для опасного действия', 'warn');
      if (res.agent) updateAgent(res.agent);
      speak(res.reply);
      refreshStatus();
    } catch (err) {
      addMsg('system', serverDiagnosis(err));
      toast('Нет связи с сервером — см. подсказку', 'bad');
    } finally {
      setThinking(false);
    }
  }

  function setThinking(on) {
    state.thinking = on;
    setClass('thinking', on);
    if (on) setCore('PROCESSING');
    else if (!state.speaking && !state.listening) setCore(state.enabled ? 'STANDBY' : 'OFFLINE');
  }

  // ───────────────────────────────────────────── speech OUTPUT
  const isRuVoice = (v) =>
    /^ru/i.test(v.lang || '') ||
    /russian|рус|irina|pavel|svetlana|dmitry|google рус/i.test(v.name || '');

  function refreshVoices() {
    const el = $('voiceDiag');
    if (!('speechSynthesis' in window)) {
      if (el) {
        el.className = 'voice-diag bad';
        el.innerHTML = '<b>Синтез речи не поддерживается этим браузером.</b> Откройте HUD в Chrome или Edge.';
      }
      return;
    }
    const list = window.speechSynthesis.getVoices() || [];
    if (list.length) state.voices = list;
    // Russian first, then by language — and mark network voices explicitly.
    state.voiceList = state.voices.slice().sort((a, b) =>
      (isRuVoice(a) ? 0 : 1) - (isRuVoice(b) ? 0 : 1) ||
      String(a.lang).localeCompare(String(b.lang)) ||
      String(a.name).localeCompare(String(b.name)));

    const sel = $('setVoice');
    const cur = sel.value;
    sel.innerHTML = '<option value="">Автоматически (лучший доступный)</option>';
    state.voiceList.forEach((v, i) => {
      const o = document.createElement('option');
      o.value = String(i);
      o.textContent = `${v.name} · ${v.lang}${v.localService ? '' : ' · онлайн'}`;
      sel.appendChild(o);
    });
    sel.value = cur;

    if (!el) return;
    const ru = state.voiceList.filter(isRuVoice);
    if (!state.voiceList.length) {
      el.className = 'voice-diag bad';
      el.innerHTML = '<b>Голосов не найдено (0).</b> Это движок браузера/ОС, а не Джарвис. '
        + 'Откройте HUD в <b>Microsoft Edge</b> — у него есть облачные голоса «Microsoft … Online (Natural)» '
        + 'даже без русского языкового пакета Windows. После установки голосов <b>полностью перезапустите браузер</b>. '
        + '<a href="ms-settings:speech">Открыть параметры речи Windows ↗</a>';
    } else if (!ru.length) {
      el.className = 'voice-diag warn';
      el.innerHTML = `<b>Русского голоса нет</b> — всего голосов: ${state.voiceList.length}. `
        + 'Выберите любой в списке или откройте HUD в Edge / Chrome: у них есть сетевые русские голоса '
        + 'независимо от настроек Windows. <a href="ms-settings:speech">Параметры речи ↗</a> · '
        + '<a href="ms-settings:regionlanguage">Язык и регион ↗</a>';
    } else {
      el.className = 'voice-diag good';
      el.innerHTML = `<b>Русский голос найден</b> — ${ru.length} из ${state.voiceList.length}: `
        + `${escapeHtml(ru.slice(0, 3).map((v) => v.name).join(', '))}. `
        + 'Выберите его выше и нажмите «Тест речи».';
    }
  }

  function initVoices() {
    refreshVoices();
    // Chrome/Edge populate getVoices() asynchronously; the event plus retries
    // cover both the normal case and browsers that never fire voiceschanged.
    window.speechSynthesis?.addEventListener?.('voiceschanged', refreshVoices);
    [700, 2000, 4000].forEach((t) => setTimeout(refreshVoices, t));
  }

  function pickVoice() {
    const list = state.voiceList.length ? state.voiceList : state.voices;
    if (!list.length) return null;
    const sel = $('setVoice').value;
    if (sel !== '' && list[Number(sel)]) return list[Number(sel)];
    const ru = (state.config?.lang || 'ru-RU').toLowerCase().startsWith('ru');
    return (ru ? list.find(isRuVoice) : list.find((v) => /^en/i.test(v.lang))) || null;
  }

  function testVoice() {
    if (!('speechSynthesis' in window)) { toast('Синтез речи недоступен', 'bad'); return; }
    refreshVoices();
    const v = pickVoice();
    const u = new SpeechSynthesisUtterance('Проверка связи. Все системы в норме, сэр.');
    u.lang = state.config?.lang || 'ru-RU';
    u.rate = Number(state.config?.voice_rate) || 1;
    u.pitch = Number(state.config?.voice_pitch) || 1;
    if (v) u.voice = v;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    toast(v ? `Тест голоса: ${v.name}` : 'Тест: голос браузера по умолчанию');
  }

  function setSpeaking(on) {
    state.speaking = on;
    setClass('speaking', on);
    if (on) { setCore('SPEAKING'); setStage('ОТВЕЧАЮ'); }
    else if (!state.thinking) setStage('ГОТОВ К КОМАНДАМ');
  }

  function speak(text) {
    if (!state.config?.speak_replies || state.muted || !('speechSynthesis' in window)) {
      setSpeaking(false);
      return;
    }
    const clean = String(text).replace(/[*_`#>[•]/g, '').replace(/\s+/g, ' ').trim().slice(0, 700);
    if (!clean) { setSpeaking(false); return; }
    try {
      window.speechSynthesis.cancel();
      // Don't listen to ourselves.
      pauseForSpeech();
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = state.config.lang || 'ru-RU';
      u.rate = Number(state.config.voice_rate) || 1;
      u.pitch = Number(state.config.voice_pitch) || 1;
      const v = pickVoice();
      if (v) u.voice = v;
      if (!state.voices.length && !state.voiceWarned) {
        // Language alone often makes Chrome/Edge pull a network voice, but warn once.
        state.voiceWarned = true;
        toast('Системных голосов нет — откройте HUD в Edge или проверьте Настройки → Голос и речь', 'warn');
      }
      u.onend = u.onerror = () => { setSpeaking(false); resumeAfterSpeech(); };
      setSpeaking(true);
      window.speechSynthesis.speak(u);
      // Safety net: some engines never fire onend.
      setTimeout(() => { if (state.speaking && !window.speechSynthesis.speaking) { setSpeaking(false); resumeAfterSpeech(); } }, Math.min(30000, clean.length * 90 + 3000));
    } catch (e) { setSpeaking(false); resumeAfterSpeech(); }
  }

  function stopSpeech() {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    setSpeaking(false);
  }

  // ───────────────────────────────────────────── speech INPUT
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  function initRecognition() {
    if (!SR) {
      state.srAvailable = false;
      return null;
    }
    state.srAvailable = true;
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    rec.lang = state.config?.lang || 'ru-RU';

    rec.onstart = () => { setListening(true); };
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const txt = (r[0]?.transcript || '').trim();
        if (r.isFinal) state.finalBuf += (state.finalBuf ? ' ' : '') + txt;
        else interim += txt + ' ';
      }
      state.interim = interim.trim();
      setTranscript(state.finalBuf || state.interim || 'Слушаю…', state.finalBuf ? 'active' : 'interim');
      if (state.interim || state.finalBuf) setStage('РАСПОЗНАЮ РЕЧЬ');
      // In push mode, send shortly after the user stops talking.
      if (state.finalBuf && state.mode === 'push') {
        clearTimeout(state.finalizeTimer);
        state.finalizeTimer = setTimeout(() => finalize(), 850);
      }
      if (state.finalBuf && state.mode !== 'push') {
        clearTimeout(state.finalizeTimer);
        state.finalizeTimer = setTimeout(() => finalize(), 500);
      }
    };
    rec.onerror = (e) => {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        toast('Доступ к микрофону запрещён — проверьте разрешения браузера', 'bad');
        state.shouldRestart = false;
      } else if (e.error === 'network') {
        toast('Распознавание речи требует интернет-соединения (Chrome Speech API)', 'warn');
      } else {
        toast('Ошибка распознавания: ' + e.error, 'warn');
      }
    };
    rec.onend = () => {
      setListening(false);
      if (state.shouldRestart && !state.speaking && state.enabled) {
        setTimeout(() => safeStart(), 300);
      }
    };
    return rec;
  }

  function safeStart() {
    if (!state.rec) state.rec = initRecognition();
    if (!state.rec) { toast('Распознавание речи недоступно в этом браузере — используйте Chrome или Edge', 'bad'); return; }
    try { state.rec.start(); } catch (e) { /* already started */ }
  }

  function startListening(restart = false) {
    if (!state.enabled) { toast('Сначала активируйте систему'); return; }
    state.finalBuf = '';
    state.interim = '';
    state.armed = false;
    state.shouldRestart = restart;
    if (!state.rec || state.rec.lang !== (state.config.lang || 'ru-RU')) {
      state.rec = initRecognition();
    }
    safeStart();
    setCore('LISTENING');
    setStage(state.mode === 'wake' ? 'ЖДУ «ДЖАРВИС»' : 'СЛУШАЮ');
  }

  function setListening(on) {
    state.listening = on;
    setClass('listening', on);
    $('btnMic').classList.toggle('active', on);
    const p = $('pillMic');
    p.className = 'pill ' + (on ? 'on' : state.muted ? 'warn' : '');
    p.querySelector('span').textContent = on ? 'МИКРОФОН АКТИВЕН' : state.muted ? 'ОЗВУЧКА ВЫКЛ' : 'МИКРОФОН ВЫКЛ';
    if (!on && !state.speaking && !state.thinking) setCore(state.enabled ? 'STANDBY' : 'OFFLINE');
  }

  function finalize() {
    clearTimeout(state.finalizeTimer);
    const phrase = (state.finalBuf + ' ' + state.interim).trim();
    state.finalBuf = ''; state.interim = '';
    if (!phrase) { setStage(state.mode === 'wake' ? 'ЖДУ «ДЖАРВИС»' : 'ГОТОВ К КОМАНДАМ'); return; }

    if (state.mode === 'wake') {
      const wake = (state.config.wake_word || 'джарвис').toLowerCase().trim();
      const lower = phrase.toLowerCase().replace(/ё/g, 'е');
      const idx = lower.indexOf(wake);
      if (idx >= 0) {
        const rest = phrase.slice(idx + wake.length).replace(/^[\s,:;.\-]+/, '').trim();
        if (rest.length > 1) { send(rest, 'voice'); state.armed = false; return; }
        state.armed = true;
        setStage('ДА, СЛУШАЮ ВАС');
        setTranscript('Слушаю команду…', 'interim');
        return;
      }
      if (state.armed) { state.armed = false; send(phrase, 'voice'); return; }
      setStage('ЖДУ «ДЖАРВИС»');
      setTranscript('Скажите «' + (state.config.wake_word || 'Джарвис') + '» перед командой');
      return;
    }
    if (state.mode === 'push') stopListening();
    send(phrase, 'voice');
  }

  function stopListening() {
    state.shouldRestart = false;
    clearTimeout(state.finalizeTimer);
    try { state.rec?.stop(); } catch (e) { /* not started */ }
    setListening(false);
  }

  function pauseForSpeech() {
    if (!state.listening) return;
    try { state.rec?.stop(); } catch (e) { /* noop */ }
    setListening(false);
  }

  function resumeAfterSpeech() {
    if (!state.enabled || state.muted) return;
    if (state.mode === 'wake' || state.mode === 'live') startListening(true);
  }

  function toggleMic() {
    if (!state.enabled) { $('onboarding').classList.remove('hidden'); return; }
    if (state.listening) {
      if (state.mode === 'push') finalize();
      stopListening();
    } else {
      startListening(state.mode !== 'push');
    }
  }

  function setMode(mode) {
    state.mode = mode;
    ['Push', 'Wake', 'Cont'].forEach((k, i) =>
      $('btnMode' + k).classList.toggle('active', ['push', 'wake', 'live'][i] === mode));
    const map = { push: 'PTT', wake: 'Слово «Джарвис»', live: 'Непрерывно' };
    toast('Режим прослушивания: ' + map[mode]);
    stopListening();
    if (state.config) {
      state.config.listen_mode = mode === 'live' ? 'continuous' : mode;
      api('/api/config', 'POST', { listen_mode: state.config.listen_mode }).catch(() => {});
      $('setWake').value = state.config.wake_word || 'джарвис';
    }
    if (mode !== 'push' && state.enabled) startListening(true);
    setStage(mode === 'wake' ? 'ЖДУ «ДЖАРВИС»' : 'ГОТОВ К КОМАНДАМ');
  }

  // ───────────────────────────────────────────── microphone visualizer
  async function setupMicStream() {
    if (!navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.micStream = stream;
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      state.audioCtx = new Ctx();
      const src = state.audioCtx.createMediaStreamSource(stream);
      state.analyser = state.audioCtx.createAnalyser();
      state.analyser.fftSize = 256;
      state.analyser.smoothingTimeConstant = 0.75;
      src.connect(state.analyser);
      toast('Микрофон подключён', '');
    } catch (e) {
      toast('Нет доступа к микрофону — распознавание попробует запросить его сам', 'warn');
    }
  }

  function initVisualizer() {
    const canvas = $('visualizer');
    const ctx = canvas.getContext('2d');
    const size = 520;
    const freq = new Uint8Array(128);
    let phase = 0;

    function resize() {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = size * dpr; canvas.height = size * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener('resize', resize);

    function frame() {
      const cx = size / 2, cy = size / 2;
      ctx.clearRect(0, 0, size, size);
      let target = 0.06;
      if (state.analyser) {
        state.analyser.getByteFrequencyData(freq);
        let sum = 0;
        for (let i = 0; i < 80; i++) sum += freq[i];
        target = Math.min(1, (sum / 80) / 90);
      } else if (state.listening) target = 0.25 + Math.sin(phase * 2) * 0.08;
      else if (state.speaking) target = 0.34 + Math.sin(phase * 3) * 0.12;
      else if (state.thinking) target = 0.18 + Math.sin(phase * 5) * 0.08;
      state.level += (target - state.level) * 0.14;
      phase += 0.02;

      const speaking = state.speaking;
      const color = speaking ? [75, 227, 192] : state.thinking ? [255, 196, 107] : [86, 225, 245];
      const rgb = (a) => `rgba(${color[0]},${color[1]},${color[2]},${a})`;
      const base = 150;

      // outer ticks
      const N = 96;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(phase * 0.25);
      for (let i = 0; i < N; i++) {
        const ang = (i / N) * Math.PI * 2;
        const wave = state.analyser
          ? (freq[i % 80] / 255) * 42
          : 8 + Math.sin(phase * 3 + i * 0.35) * 5;
        const len = 5 + wave + state.level * 34;
        const r0 = base + 26;
        ctx.beginPath();
        ctx.moveTo(Math.cos(ang) * r0, Math.sin(ang) * r0);
        ctx.lineTo(Math.cos(ang) * (r0 + len), Math.sin(ang) * (r0 + len));
        ctx.strokeStyle = rgb(0.14 + (i % 4 === 0 ? 0.3 : 0) + state.level * 0.35);
        ctx.lineWidth = i % 8 === 0 ? 2 : 1.2;
        ctx.stroke();
      }
      ctx.restore();

      // pulsing halo
      ctx.beginPath();
      ctx.arc(cx, cy, base + 12 + state.level * 12, 0, Math.PI * 2);
      ctx.strokeStyle = rgb(0.16 + state.level * 0.35);
      ctx.lineWidth = 1;
      ctx.shadowBlur = 22; ctx.shadowColor = rgb(0.6);
      ctx.stroke();
      ctx.shadowBlur = 0;

      // rotating arcs
      for (let k = 0; k < 3; k++) {
        const r = base - 8 - k * 13;
        const start = phase * (k % 2 ? -1 : 1) * (0.6 + k * 0.25) + k * 2;
        ctx.beginPath();
        ctx.arc(cx, cy, r, start, start + 0.7 + state.level * 0.6);
        ctx.strokeStyle = rgb(0.35 + state.level * 0.4);
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // orbit dots
      for (let i = 0; i < 6; i++) {
        const ang = phase * 0.6 + (i / 6) * Math.PI * 2;
        const r = base + 56 + Math.sin(phase + i) * 4;
        ctx.beginPath();
        ctx.arc(cx + Math.cos(ang) * r, cy + Math.sin(ang) * r, 2 + state.level * 1.5, 0, Math.PI * 2);
        ctx.fillStyle = rgb(0.5);
        ctx.fill();
      }
      requestAnimationFrame(frame);
    }
    frame();
  }

  // ───────────────────────────────────────────── status & telemetry
  function updateAgent(a) {
    const pill = $('pillAgent');
    const connected = !!a?.connected;
    pill.className = 'pill ' + (connected ? 'on' : 'warn');
    pill.querySelector('span').textContent = connected
      ? 'ПК: ' + (a.name || 'ПОДКЛЮЧЁН')
      : 'ДЕМО-РЕЖИМ';
    $('chatAgent').textContent = connected ? 'ПК · ' + (a.platform || '').slice(0, 12) : 'СЕРВЕР';
    const box = $('agentStatusBox');
    box.className = 'agent-status' + (connected ? ' on' : '');
    box.querySelector('span').textContent = connected
      ? `Агент «${a.name}» подключён · выполнено действий: ${a.completed || 0}`
      : 'Агент не подключён — команды выполняются в демо-режиме';
    $('telemetrySource').textContent = connected ? 'ВАШ ПК' : 'СЕРВЕР';
  }

  async function refreshStatus() {
    try {
      const s = await api('/api/status');
      state.status = s;
      const br = $('pillBrain');
      br.className = 'pill ' + (s.brain === 'llm' ? 'on' : 'warn');
      br.querySelector('span').textContent = 'МОЗГ: ' + (s.brain === 'llm' ? 'LLM' : 'OFFLINE NLU');
      $('chatMode').textContent = s.brain === 'llm' ? 'LLM' : 'ОФФЛАЙН-NLU';
      updateAgent(s.agent);
      $('roActions').textContent = String(s.actions || 0) + ' доступно';
      const st = s.stats || {};
      $('roMemory').textContent = `${st.notes || 0} зам. / ${st.tasks || 0} дел`;
      $('roPlatform').textContent = (s.platform?.system || '—') + ' ' + (s.platform?.machine || '').slice(0, 8);
      $('roUptime').textContent = s.uptime || '—';
    } catch (e) { /* keep last */ }
  }

  async function refreshTelemetry() {
    try {
      const t = await api('/api/telemetry');
      if (t.cpu == null && !t.memory) return;
      const set = (id, val, barId) => {
        const v = Math.max(0, Math.min(100, Number(val) || 0));
        $(id).textContent = Number.isFinite(Number(val)) ? Math.round(v) + '%' : '—';
        const bar = $(barId);
        bar.style.width = v + '%';
        bar.classList.toggle('hot', v > 80);
      };
      set('cpuVal', t.cpu, 'cpuBar');
      set('ramVal', t.memory?.percent, 'ramBar');
      set('diskVal', t.disk?.percent, 'diskBar');
      if (t.uptime) $('roUptime').textContent = t.uptime;
      $('telemetrySource').textContent = t.target === 'pc' ? 'ВАШ ПК' : 'СЕРВЕР';
    } catch (e) { /* no telemetry available */ }
  }

  async function refreshReminders() {
    try {
      const d = await api('/api/reminders');
      const box = $('reminderList');
      const items = d.reminders || [];
      if (!items.length) { box.innerHTML = '<p class="empty">Нет активных таймеров</p>'; return; }
      box.innerHTML = items.map((r) => {
        const date = new Date(r.fire_at * 1000);
        return `<div class="reminder-item"><b>${date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</b>${escapeHtml(r.text)}</div>`;
      }).join('');
    } catch (e) { /* noop */ }
  }

  function setupClock() {
    const tick = () => {
      const d = new Date();
      $('clockTime').textContent = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      $('clockDate').textContent = d.toLocaleDateString('ru-RU', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
    };
    tick(); setInterval(tick, 1000);
  }

  function setupSSE() {
    if (!window.EventSource) return;
    const es = new EventSource('/api/events');
    es.addEventListener('speak', (e) => {
      const d = JSON.parse(e.data).data || {};
      addMsg('system', d.text || 'Напоминание');
      toast(d.text || 'Напоминание', 'warn');
      speak(d.text || 'Напоминание');
    });
    es.addEventListener('agent', (e) => {
      const d = JSON.parse(e.data).data || {};
      if (d.connected) toast(`Агент «${d.name}» подключён к вашему ПК`, '');
      refreshStatus();
    });
    es.addEventListener('config', (e) => {
      const d = JSON.parse(e.data).data || {};
      state.config = { ...state.config, ...d };
    });
    es.onerror = () => { /* EventSource reconnects automatically */ };
  }

  // ───────────────────────────────────────────── settings
  function fillSettings() {
    const c = state.config || {};
    $('setLang').value = c.lang || 'ru-RU';
    $('setWake').value = c.wake_word || 'джарвис';
    $('setRate').value = c.voice_rate ?? 1; $('outRate').textContent = Number(c.voice_rate ?? 1).toFixed(2);
    $('setPitch').value = c.voice_pitch ?? 1; $('outPitch').textContent = Number(c.voice_pitch ?? 1).toFixed(2);
    $('setSpeak').checked = !!c.speak_replies;
    $('setPersona').value = c.persona || 'jarvis';
    $('setUserName').value = c.user_name || '';
    $('setLlmEnabled').checked = !!c.llm_enabled;
    $('setBaseUrl').value = c.llm_base_url || '';
    $('setModel').value = c.llm_model || '';
    $('setApiKey').placeholder = c.has_llm_key ? 'ключ сохранён · оставьте пустым, чтобы не менять' : 'оставьте пустым для Ollama';
    $('setApiKey').value = '';
    $('setConfirm').checked = !!c.require_confirm;
    $('setShell').checked = !!c.allow_shell;
    $('setPower').checked = !!c.allow_power;
    $('setRoot').value = c.sandbox_root || '';
    $('setAgentToken').value = '';
    $('setAgentToken').placeholder = 'по умолчанию: jarvis-local-agent';
    updateAgentCmd();
    state.muted = !c.speak_replies;
    $('btnMute').classList.toggle('muted', state.muted);
  }

  function updateAgentCmd() {
    const token = (document.getElementById('setAgentToken')?.value || '').trim();
    const tail = token ? ` --token ${token}` : '';
    $('agentCmd').textContent = `python jarvis_agent.py --server ${location.origin}${tail}`;
  }

  function openDrawer(open) {
    $('settingsDrawer').classList.toggle('open', open);
    $('settingsScrim').classList.toggle('hidden', !open);
    if (open) { fillSettings(); refreshStatus(); }
  }

  async function saveSettings() {
    const patch = {
      lang: $('setLang').value,
      wake_word: $('setWake').value.trim() || 'джарвис',
      voice_rate: Number($('setRate').value), voice_pitch: Number($('setPitch').value),
      speak_replies: $('setSpeak').checked,
      persona: $('setPersona').value, user_name: $('setUserName').value.trim(),
      llm_enabled: $('setLlmEnabled').checked,
      llm_base_url: $('setBaseUrl').value.trim(), llm_model: $('setModel').value.trim(),
      require_confirm: $('setConfirm').checked,
      allow_shell: $('setShell').checked, allow_power: $('setPower').checked,
      sandbox_root: $('setRoot').value.trim(),
    };
    const key = $('setApiKey').value.trim();
    if (key) patch.llm_api_key = key;
    const token = $('setAgentToken').value.trim();
    if (token) patch.agent_token = token;
    try {
      const out = await api('/api/config', 'POST', patch);
      state.config = { ...state.config, ...out.config };
      state.muted = !state.config.speak_replies;
      $('btnMute').classList.toggle('muted', state.muted);
      if (state.rec) { state.rec.lang = state.config.lang; }
      $('setApiKey').value = '';
      toast('Настройки сохранены');
      await refreshStatus();
      openDrawer(false);
    } catch (e) { toast('Не удалось сохранить настройки: ' + e.message, 'bad'); }
  }

  function applyPreset(name) {
    const presets = {
      openai: ['https://api.openai.com/v1', 'gpt-4o-mini'],
      ollama: ['http://localhost:11434/v1', 'llama3.1'],
      groq: ['https://api.groq.com/openai/v1', 'llama-3.1-8b-instant'],
    };
    const p = presets[name];
    if (!p) return;
    $('setBaseUrl').value = p[0]; $('setModel').value = p[1];
    $('setLlmEnabled').checked = true;
    toast(`Пресет «${name}» выбран — не забудьте сохранить`);
  }

  // ───────────────────────────────────────────── commands modal
  async function loadCatalogue() {
    try {
      const d = await api('/api/catalogue');
      state.catalogue = d;
      $('commandsGrid').innerHTML = (d.actions || []).map((a) =>
        `<div class="cmd-item"><b>${escapeHtml(a.name)} ${a.danger ? '<em>· подтверждение</em>' : ''}</b>
         <span>${escapeHtml(a.description)}</span></div>`).join('');
      $('examplesList').innerHTML = EXAMPLES.map((x) => `<span>${escapeHtml(x)}</span>`).join('');
      $('examplesList').querySelectorAll('span').forEach((el) =>
        el.addEventListener('click', () => { closeCommands(); send(el.textContent, 'text'); }));
    } catch (e) { /* noop */ }
  }

  function openCommands(open) {
    $('commandsModal').classList.toggle('open', open);
    $('commandsScrim').classList.toggle('hidden', !open);
  }
  const closeCommands = () => openCommands(false);

  // ───────────────────────────────────────────── bindings
  function bindUI() {
    $('btnSend').addEventListener('click', () => send($('userInput').value, 'text'));
    $('userInput').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); send($('userInput').value, 'text'); }
    });
    $('btnMic').addEventListener('click', toggleMic);
    $('btnModePush').addEventListener('click', () => setMode('push'));
    $('btnModeWake').addEventListener('click', () => setMode('wake'));
    $('btnModeCont').addEventListener('click', () => setMode('live'));
    $('btnMute').addEventListener('click', () => {
      state.muted = !state.muted;
      $('btnMute').classList.toggle('muted', state.muted);
      if (state.muted) stopSpeech();
      toast(state.muted ? 'Озвучивание ответов выключено' : 'Озвучивание включено');
      api('/api/config', 'POST', { speak_replies: !state.muted }).catch(() => {});
    });
    $('btnClear').addEventListener('click', async () => {
      await api('/api/history', 'DELETE');
      $('chat').innerHTML = ''; $('actionCards').innerHTML = '';
      addMsg('system', 'История диалога очищена.');
    });

    $('btnVoiceRefresh').addEventListener('click', () => {
      refreshVoices();
      toast(state.voices.length ? `Найдено голосов: ${state.voices.length}` : 'Голоса пока не загрузились — откройте HUD в Edge', 'warn');
    });
    $('btnVoiceTest').addEventListener('click', testVoice);
    $('serverAlertRetry').addEventListener('click', () => { hideServerAlert(); location.reload(); });
    $('btnSettings').addEventListener('click', () => { refreshVoices(); openDrawer(true); });
    $('btnCloseSettings').addEventListener('click', () => openDrawer(false));
    $('settingsScrim').addEventListener('click', () => openDrawer(false));
    $('btnSaveSettings').addEventListener('click', saveSettings);
    $('btnCommands').addEventListener('click', () => openCommands(true));
    $('btnCloseCommands').addEventListener('click', closeCommands);
    $('commandsScrim').addEventListener('click', closeCommands);
    $('btnCopyCmd').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText($('agentCmd').textContent); toast('Команда скопирована'); }
      catch (e) { toast('Скопируйте команду вручную', 'warn'); }
    });
    document.querySelectorAll('[data-preset]').forEach((b) =>
      b.addEventListener('click', () => applyPreset(b.dataset.preset)));
    $('setRate').addEventListener('input', (e) => $('outRate').textContent = Number(e.target.value).toFixed(2));
    $('setPitch').addEventListener('input', (e) => $('outPitch').textContent = Number(e.target.value).toFixed(2));
    $('setAgentToken').addEventListener('input', updateAgentCmd);

    $('quickChips').innerHTML = QUICK.map((q, i) => `<button class="chip" data-i="${i}">${escapeHtml(q.label)}</button>`).join('');
    $('quickChips').querySelectorAll('.chip').forEach((b) =>
      b.addEventListener('click', () => send(QUICK[Number(b.dataset.i)].text, 'text')));

    $('btnBoot').addEventListener('click', () => activate(true));
    $('btnBootSkip').addEventListener('click', () => activate(false));

    document.addEventListener('keydown', (e) => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
      if (e.key === 'Escape') {
        stopSpeech(); stopListening(); openDrawer(false); closeCommands();
        $('onboarding').classList.add('hidden');
        return;
      }
      if (e.key === '?' && !typing) { openCommands(true); return; }
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'j') {
        e.preventDefault();
        setMode(state.mode === 'live' ? 'push' : 'live');
        return;
      }
      if (e.code === 'Space' && !typing && !e.repeat && !state.keyHeld) {
        e.preventDefault();
        state.keyHeld = true;
        if (state.mode !== 'push') setMode('push');
        startListening(false);
      }
    });
    document.addEventListener('keyup', (e) => {
      if (e.code === 'Space' && state.keyHeld) {
        state.keyHeld = false;
        if (state.mode === 'push' && state.listening) { finalize(); stopListening(); }
      }
    });
  }

  async function activate(withMic) {
    $('onboarding').classList.add('hidden');
    localStorage.setItem('jarvis_booted', '1');
    state.enabled = true;
    setCore('STANDBY');
    setStage('СИСТЕМА АКТИВИРОВАНА');
    if (withMic) {
      await setupMicStream();
      if (!SR) toast('Этот браузер не поддерживает распознавание речи — используйте Chrome / Edge', 'warn');
    } else {
      toast('Текстовый режим. Микрофон можно включить кнопкой ниже.');
    }
    const mode = state.config?.listen_mode === 'continuous' ? 'live'
      : state.config?.listen_mode === 'wake' ? 'wake' : 'push';
    setMode(mode);
    setTimeout(() => setStage(mode === 'wake' ? 'ЖДУ «ДЖАРВИС»' : 'ГОТОВ К КОМАНДАМ'), 1200);
    refreshTelemetry(); refreshStatus();
  }

  // ───────────────────────────────────────────── boot
  async function init() {
    setupClock();
    initVisualizer();
    initVoices();
    bindUI();
    try { state.config = await api('/api/config'); }
    catch (e) { state.config = { lang: 'ru-RU', speak_replies: true, listen_mode: 'push' }; }
    fillSettings();
    await Promise.all([loadHistory(), loadCatalogue(), refreshStatus(), refreshReminders(), refreshTelemetry()]);
    setupSSE();
    setInterval(refreshStatus, 6000);
    setInterval(refreshTelemetry, 10000);
    setInterval(refreshReminders, 15000);
    if (localStorage.getItem('jarvis_booted')) activate(false);
    else { setCore('OFFLINE'); setStage('ОЖИДАНИЕ АКТИВАЦИИ'); }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
