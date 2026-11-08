'use strict';
(() => {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const copy = value => JSON.parse(JSON.stringify(value));
  const fields = ['condition', 'shortcoming', 'consequence', 'measure', 'justification'];
  const labels = ['Условие воздействия', 'Конструктивный недостаток', 'Последствие', 'Мероприятие', 'Обоснование'];
  const mainFields = ['title', 'purpose', 'construction', 'placement', 'conclusion', 'limitations'];
  const selectors = ['#project-title', '#purpose', '#construction', '#placement', '#conclusion', '#limitations'];
  const limits = [120, 4000, 6000, 4000, 6000, 6000];
  const row = id => ({id, condition: '', shortcoming: '', consequence: '', measure: '', justification: ''});
  const fresh = () => ({analysis: {title: '', purpose: '', construction: '', placement: '', materials: [], rows: [row('R1')], conclusion: '', limitations: ''}, review: null});
  let state = fresh(), stage = 0, busy = false, enabled = false, db, revision = 0, timer, queue = Promise.resolve();
  function el(tag, text, className) {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n;}
  function button(text, action, cls) {const n = el('button', text, cls); n.type = 'button'; n.addEventListener('click', action); return n;}
  function error(value) {NadegErrors.show(value);}
  function dirty(analysisChanged = true) {
    revision++; NadegErrors.clear();
    if (analysisChanged && state.review) state.review.stale = true;
    $('#review-stale').hidden = !state.review?.stale;
    clearTimeout(timer); $('#save-state').textContent = 'Сохранение…'; timer = setTimeout(() => persist(copy(state)), 350);
  }
  function persist(value) {
    queue = queue.then(() => new Promise(resolve => {
      if (!db) {$('#save-state').textContent = 'Автосохранение недоступно · скачайте JSON'; resolve(); return;}
      try {
        const tx = db.transaction('projects', 'readwrite'); tx.objectStore('projects').put({version: 1, lab: 3, state: value}, 'lab3-draft');
        tx.oncomplete = () => {$('#save-state').textContent = 'Сохранено на устройстве'; resolve();};
        tx.onerror = tx.onabort = () => {$('#save-state').textContent = 'Не удалось сохранить · скачайте JSON'; resolve();};
      } catch (_) {$('#save-state').textContent = 'Не удалось сохранить · скачайте JSON'; resolve();}
    })); return queue;
  }
  function string(value, max) {if (typeof value !== 'string' || value.length > max) throw new Error('Некорректное или слишком длинное поле проекта.'); return value;}
  function grounding(s) {
    let basis = null;
    if (s.basis) {
      if (!['source', 'physical_principle', 'insufficient_data'].includes(s.basis.kind) || !Array.isArray(s.basis.assumptions) || s.basis.assumptions.length > 6) throw new Error('Некорректное обоснование замечания.');
      basis = {kind: s.basis.kind, explanation: string(s.basis.explanation, 1600), check: string(s.basis.check, 1000), assumptions: s.basis.assumptions.map(x => string(x, 400))};
    }
    const verdicts = ['consistent', 'uncertain', 'contradictory', 'unsupported'];
    const verification = s.verification && verdicts.includes(s.verification.verdict) ? {verdict: s.verification.verdict, reason: string(s.verification.reason, 1200)} : {verdict: 'uncertain', reason: 'Этот результат сохранён без проверки технических оснований. Повторите проверку или внесите собственную правку вручную.'};
    return {basis, verification, apply_allowed: s.apply_allowed === true && Boolean(basis) && verification.verdict === 'consistent'};
  }
  function validateProject(project) {
    if (project?.lab !== 3 || project.version !== 1 || !project.state?.analysis) throw new Error('Откройте проект ЛР №3 в формате JSON.');
    const a = project.state.analysis, clean = {};
    mainFields.forEach((field, i) => clean[field] = string(a[field], limits[i]));
    if (!Array.isArray(a.rows) || !a.rows.length || a.rows.length > 20 || !Array.isArray(a.materials) || a.materials.length > 8) throw new Error('Некорректный состав проекта.');
    clean.rows = a.rows.map(r => {if (!/^R[1-9][0-9]{0,2}$/.test(r.id)) throw new Error('Некорректный ID строки.'); const c = {id: r.id}; fields.forEach(f => c[f] = string(r[f], 2000)); return c;});
    clean.materials = a.materials.map(m => {
      if (!/^S[1-9][0-9]{0,2}$/.test(m.id)) throw new Error('Некорректный ID материала.');
      const c = {id: m.id, name: string(m.name, 160), text: string(m.text, 10000), image: string(m.image, 2800000)};
      if (c.image && !/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/]+=*$/.test(c.image)) throw new Error('Некорректное изображение в проекте.');
      return c;
    });
    for (const items of [clean.rows, clean.materials]) if (new Set(items.map(x => x.id)).size !== items.length) throw new Error('Повторяются ID в проекте.');
    if (clean.materials.filter(m => m.image).length > 4 || clean.materials.reduce((sum, m) => sum + m.image.length, 0) > 8400000) throw new Error('Слишком много изображений.');
    let review = null;
    const r = project.state.review;
    if (r) {
      if (!Array.isArray(r.suggestions) || r.suggestions.length > 25 || !Array.isArray(r.missing_information) || r.missing_information.length > 12) throw new Error('Некорректные данные проверки.');
      review = {summary: string(r.summary, 3000), date: string(r.date, 60), stale: Boolean(r.stale), missing_information: r.missing_information.map(v => string(v, 800)), suggestions: r.suggestions.map(s => {
        if (!fields.includes(s.field) || !['supported', 'hypothesis', 'missing_data'].includes(s.status) || !['pending', 'accepted', 'rejected'].includes(s.decision) || (s.row_id !== null && !clean.rows.some(row => row.id === s.row_id)) || !Array.isArray(s.evidence) || s.evidence.length > 4) throw new Error('Некорректное замечание в проекте.');
        return {...grounding(s), row_id: s.row_id, field: s.field, status: s.status, decision: s.decision, comment: string(s.comment, 1600), replacement: string(s.replacement, 2000), original: string(s.original, 2000), evidence: s.evidence.map(e => ({source_id: string(e.source_id, 4), quote: string(e.quote, 600)}))};
      })};
    }
    return {analysis: clean, review};
  }
  async function initStorage() {
    const initial = revision;
    try {
      db = await new Promise((resolve, reject) => {const r = indexedDB.open('nadeg', 1); r.onupgradeneeded = () => r.result.createObjectStore('projects'); r.onsuccess = () => resolve(r.result); r.onerror = r.onblocked = reject;});
      const saved = await new Promise((resolve, reject) => {const r = db.transaction('projects').objectStore('projects').get('lab3-draft'); r.onsuccess = () => resolve(r.result); r.onerror = reject;});
      if (saved && initial === revision) {state = validateProject(saved); renderAll(); $('#save-state').textContent = 'Черновик ЛР №3 восстановлен';}
      else if (initial !== revision) persist(copy(state));
      else $('#save-state').textContent = 'Автосохранение ЛР №3 включено';
    } catch (_) {$('#save-state').textContent = 'Не удалось восстановить черновик · скачайте JSON';}
  }
  async function api(path, data) {
    let response;
    try {response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});}
    catch (_) {throw new Error('Сервер недоступен. Проверьте подключение; черновик остаётся в браузере.');}
    if (!response.ok) {let data; try {data = await response.json();} catch (_) {} throw NadegErrors.fromResponse(data, response.status);}
    return response;
  }
  function payload(requireWork = false) {
    const a = copy(state.analysis); a.title = a.title.trim();
    if (!a.title) throw NadegErrors.field('Укажите объект исследования', ['title'], 'Объект');
    a.materials.forEach((m, i) => {if (!m.name.trim()) throw NadegErrors.field('Укажите название материала', ['materials', i, 'name'], `Материал ${m.id}`); if (!m.text.trim() && !m.image) throw NadegErrors.field('Добавьте текст или изображение либо удалите пустой материал', ['materials', i, 'text'], `Материал ${m.id}`);});
    if (requireWork && !a.rows.some(r => fields.some(f => r[f].trim()))) throw new Error('Сначала заполните хотя бы одну строку собственного анализа.');
    return a;
  }
  function setBusy(value, kind = 'review') {
    busy = value; $$('button, input, textarea').forEach(n => n.disabled = value);
    $('#review-button').disabled = value || !enabled;
    $('#review-progress').hidden = !value || kind !== 'review'; $('#review-button').textContent = value && kind === 'review' ? 'Проверяем…' : 'Проверить анализ';
    if (!value) renderReview();
  }
  function showStage(value) {
    stage = value; $$('[data-panel]').forEach(n => n.hidden = Number(n.dataset.panel) !== stage);
    $$('[data-step]').forEach(n => {if (Number(n.dataset.step) === stage) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current');});
    $('#back').hidden = stage === 0; $('#next').hidden = stage === 2;
    $('#next').textContent = stage === 0 ? 'К анализу →' : 'К проверке и отчёту →';
    $('#step-caption').textContent = ['Опишите объект и добавьте материалы', 'Сформулируйте цепочки рассуждений', 'Примите правки и подготовьте вывод'][stage];
  }
  function nextId(prefix, items) {let n = 1; while (items.some(x => x.id === prefix + n)) n++; return prefix + n;}
  function renderMaterials() {
    $('#materials').replaceChildren();
    if (!state.analysis.materials.length) $('#materials').append(el('p', 'Материалы пока не добавлены.', 'field-note'));
    state.analysis.materials.forEach(m => {
      const card = el('article', undefined, 'material-card');
      const top = el('div', undefined, 'section-top'); top.append(el('h3', m.id), button('Удалить', async () => {
        if (await confirmAction('Удалить материал?', `Материал ${m.id} будет удалён из текущего проекта.`)) {state.analysis.materials = state.analysis.materials.filter(x => x !== m); state.review = null; dirty(); renderMaterials(); renderReview();}
      }, 'text-button'));
      const nameLabel = el('label', 'Название или источник'), name = el('input'); name.value = m.name; name.maxLength = 160; name.setAttribute('aria-label', `Название материала ${m.id}`); name.addEventListener('input', () => {m.name = name.value; dirty();}); nameLabel.append(name);
      const textLabel = el('label', m.image ? 'Подпись и пояснения к изображению' : 'Текст материала'), text = el('textarea'); text.rows = 4; text.maxLength = 10000; text.value = m.text; text.setAttribute('aria-label', `Текст материала ${m.id}`); text.addEventListener('input', () => {m.text = text.value; dirty();}); textLabel.append(text);
      card.append(top, nameLabel);
      if (m.image) {const img = el('img'); img.src = m.image; img.alt = `Исходный материал ${m.id}`; img.className = 'material-image'; card.append(img);}
      card.append(textLabel); $('#materials').append(card);
    });
  }
  function renderRows() {
    $('#analysis-rows').replaceChildren();
    state.analysis.rows.forEach(r => {
      const tr = el('tr'); tr.dataset.row = r.id;
      fields.forEach((field, i) => {const td = el('td'); td.dataset.label = labels[i]; const input = el('textarea'); input.rows = 4; input.maxLength = 2000; input.value = r[field]; input.dataset.field = field; input.setAttribute('aria-label', `${r.id}: ${labels[i]}`); input.addEventListener('input', () => {r[field] = input.value; dirty();}); td.append(input); tr.append(td);});
      const td = el('td'); td.append(el('span', r.id, 'row-id'), button('Удалить', async () => {
        if (state.analysis.rows.length === 1) {error('Оставьте хотя бы одну строку.'); return;}
        if (await confirmAction('Удалить строку?', `Строка ${r.id} и результаты её проверки будут удалены.`)) {state.analysis.rows = state.analysis.rows.filter(x => x !== r); state.review = null; dirty(); renderRows(); renderReview();}
      }, 'delete-analysis')); tr.append(td); $('#analysis-rows').append(tr);
    });
  }
  function renderReview() {
    const review = state.review; $('#review').hidden = !review; $('#review-empty').hidden = Boolean(review); $('#suggestions').replaceChildren();
    if (!review) return;
    $('#review-summary').textContent = review.summary; $('#review-stale').hidden = !review.stale;
    const date = new Date(review.date); $('#review-date').textContent = Number.isNaN(date.getTime()) ? '' : `Проверка: ${date.toLocaleString('ru-RU')}`;
    const statuses = {supported: 'Есть цитата из материала', hypothesis: 'Предположение · проверьте', missing_data: 'Нужны данные'};
    review.suggestions.forEach(s => {
      const card = el('article', undefined, 'suggestion-card'); card.dataset.decision = s.decision;
      card.append(el('p', `${s.row_id || 'Общее замечание'} · ${labels[fields.indexOf(s.field)]}`, 'field-note'), el('span', statuses[s.status], 'review-status'), el('p', s.comment));
      s.evidence.forEach(e => {const material = state.analysis.materials.find(m => m.id === e.source_id); if (material && e.quote && material.text.includes(e.quote)) card.append(el('blockquote', `${e.source_id} · ${material.name}: «${e.quote}»`));});
      const basis = el('div', undefined, 'suggestion-basis');
      if (s.basis) {
        const kinds = {source: 'Вывод из материалов', physical_principle: 'Общий физический принцип', insufficient_data: 'Недостаточно сведений'};
        basis.append(el('p', kinds[s.basis.kind]), el('p', s.basis.explanation));
        if (s.basis.assumptions.length) {basis.append(el('p', 'Допущения:')); const ul = el('ul'); ul.append(...s.basis.assumptions.map(v => el('li', v))); basis.append(ul);}
        basis.append(el('p', 'Как проверить: ' + s.basis.check));
      } else basis.append(el('p', 'Техническое основание в старой проверке не указано.'));
      card.append(basis);
      const verdicts = {consistent: 'Проверка согласованности пройдена', uncertain: 'Требуется самостоятельная проверка', contradictory: 'Найдено противоречие', unsupported: 'Основание не подтверждает совет'};
      const note = el('p', `${verdicts[s.verification?.verdict || 'uncertain']}. ${s.verification?.reason || ''}`, 'verification-note'); note.dataset.verdict = s.verification?.verdict || 'uncertain'; card.append(note);
      if (s.row_id) {const comparison = el('details', undefined, 'review-comparison'); comparison.append(el('summary', 'Сравнить с текстом, отправленным на проверку'), el('pre', s.original || 'Поле не было заполнено')); card.append(comparison);}
      if (s.replacement) {const label = el('label', 'Предлагаемая редакция — можно изменить'), input = el('textarea'); input.value = s.replacement; input.rows = 3; input.maxLength = 2000; input.disabled = s.decision !== 'pending'; input.addEventListener('input', () => {s.replacement = input.value; s.apply_allowed = false; s.verification = {verdict: 'uncertain', reason: 'Предлагаемый текст изменён после проверки. Внесите собственную редакцию в анализ вручную.'}; note.textContent = s.verification.reason; note.dataset.verdict = 'uncertain'; const accept = card.querySelector('[data-accept]'); if (accept) accept.disabled = true; dirty(false);}); label.append(input); card.append(label);}
      if (s.decision === 'pending') {
        const actions = el('div', undefined, 'suggestion-actions');
        if (s.row_id && s.replacement) {const accept = button('Принять правку', () => {
          if (!s.apply_allowed || s.verification?.verdict !== 'consistent') {error('Основание совета требует проверки. Внесите собственную редакцию вручную.'); return;}
          const target = state.analysis.rows.find(r => r.id === s.row_id);
          if (!target || target[s.field] !== s.original) {error('Это поле уже изменено. Сравните тексты и внесите правку вручную или повторите проверку.'); return;}
          if (!s.replacement.trim()) {error('Предлагаемая редакция пуста.'); return;}
          target[s.field] = s.replacement; s.decision = 'accepted'; dirty(); renderRows(); renderReview();
        }, 'text-button'); accept.dataset.accept = 'true'; accept.disabled = !s.apply_allowed; actions.append(accept);}
        if (s.row_id) actions.append(button('Открыть строку анализа', () => {showStage(1); const row = [...document.querySelectorAll('#analysis-rows tr')].find(n => n.dataset.row === s.row_id); row?.querySelector('textarea')?.focus();}, 'text-button'));
        actions.append(button(s.replacement && s.row_id ? 'Отклонить' : 'Отметить прочитанным', () => {s.decision = 'rejected'; dirty(false); renderReview();})); card.append(actions);
      } else card.append(el('p', s.decision === 'accepted' ? 'Правка принята' : 'Замечание просмотрено', 'field-note'));
      $('#suggestions').append(card);
    });
    $('#missing-block').hidden = !review.missing_information.length; $('#missing-information').replaceChildren(...review.missing_information.map(q => el('li', q)));
  }
  function renderAll() {mainFields.forEach((field, i) => $(selectors[i]).value = state.analysis[field]); renderMaterials(); renderRows(); renderReview(); showStage(stage);}
  async function confirmAction(title, text) {$('#confirm-title').textContent = title; $('#confirm-text').textContent = text; $('#confirm-dialog').showModal(); return new Promise(resolve => $('#confirm-dialog').addEventListener('close', () => resolve($('#confirm-dialog').returnValue === 'confirm'), {once: true}));}
  async function reviewAnalysis() {
    if (busy || !enabled) return;
    try {
      const data = payload(true);
      if (state.review && !await confirmAction('Повторить проверку?', 'Предыдущие замечания будут заменены после успешного ответа. Принятые правки и ваш текст сохранятся.')) return;
      setBusy(true); $('#error').hidden = true; clearTimeout(timer); await persist(copy(state));
      const result = await (await api('/api/lab3/analyze', data)).json();
      state.review = {...result, date: new Date().toISOString(), stale: false, suggestions: result.suggestions.map(s => ({...s, ...grounding(s), decision: 'pending', original: data.rows.find(r => r.id === s.row_id)?.[s.field] || ''}))};
      dirty(false); renderReview();
    } catch (e) {error(e);} finally {setBusy(false);}
  }
  function download(data, name, type) {const blob = data instanceof Blob ? data : new Blob([data], {type}); const url = URL.createObjectURL(blob); const a = el('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);}
  async function exportReport(format) {if (busy) return; try {const data = payload(true); const response = await api('/api/lab3/export/' + format, data); download(await response.blob(), 'nadeg-lab3.' + format);} catch (e) {error(e);}}
  async function resizeImage(file) {
    if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 10 * 1024 * 1024) throw new Error('Выберите PNG или JPEG размером до 10 МБ.');
    const bitmap = await createImageBitmap(file);
    try {
      if (bitmap.width * bitmap.height > 40_000_000) throw new Error('Изображение слишком большое. Уменьшите его до загрузки.');
      const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas'); canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height); ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const image = canvas.toDataURL('image/jpeg', 0.86); if (image.length > 2800000) throw new Error('После уменьшения изображение больше 2 МБ. Уменьшите его вручную.'); return image;
    } finally {bitmap.close();}
  }
  mainFields.forEach((field, i) => $(selectors[i]).addEventListener('input', () => {state.analysis[field] = $(selectors[i]).value; dirty();}));
  $$('[data-step]').forEach(n => n.addEventListener('click', () => {if (!busy) showStage(Number(n.dataset.step));}));
  $('#next').addEventListener('click', () => {if (!busy) showStage(Math.min(2, stage + 1));}); $('#back').addEventListener('click', () => {if (!busy) showStage(Math.max(0, stage - 1));});
  $('#add-row').addEventListener('click', () => {if (state.analysis.rows.length >= 20) {error('Не более 20 строк.'); return;} state.analysis.rows.push(row(nextId('R', state.analysis.rows))); dirty(); renderRows(); $('#analysis-rows tr:last-child textarea').focus();});
  $('#add-text').addEventListener('click', () => {if (state.analysis.materials.length >= 8) {error('Не более 8 материалов.'); return;} state.analysis.materials.push({id: nextId('S', state.analysis.materials), name: '', text: '', image: ''}); dirty(); renderMaterials(); $('#materials article:last-child input').focus();});
  $('#add-image').addEventListener('click', () => $('#image-file').click());
  $('#image-file').addEventListener('change', async event => {
    const file = event.target.files[0]; event.target.value = ''; if (!file) return;
    try {if (state.analysis.materials.length >= 8 || state.analysis.materials.filter(m => m.image).length >= 4) throw new Error('Не более 8 материалов и 4 изображений.');
      setBusy(true, 'image');
      const image = await resizeImage(file); if (state.analysis.materials.reduce((sum, m) => sum + m.image.length, image.length) > 8400000) throw new Error('Суммарный размер изображений больше 6 МБ.');
      state.analysis.materials.push({id: nextId('S', state.analysis.materials), name: file.name.slice(0, 160), text: '', image}); dirty(); renderMaterials();
    } catch (e) {error(e);} finally {setBusy(false);}
  });
  $('#review-button').addEventListener('click', reviewAnalysis);
  $('#copy-questions').addEventListener('click', () => {
    const questions = state.review.missing_information.filter(q => !state.analysis.limitations.includes(q));
    const value = [state.analysis.limitations, ...questions].filter(Boolean).join('\n'); if (value.length > 6000) {error('Поле ограничений заполнено. Перенесите нужные вопросы вручную.'); return;}
    state.analysis.limitations = value; $('#limitations').value = value; dirty();
  });
  ['pdf', 'csv'].forEach(format => $('#export-' + format).addEventListener('click', () => exportReport(format)));
  $('#save-project').addEventListener('click', () => {download(JSON.stringify({version: 1, lab: 3, state}), 'nadeg-lab3-project.json', 'application/json'); $('.project-menu').open = false;});
  $('#load-project').addEventListener('click', () => {$('#project-file').click(); $('.project-menu').open = false;});
  $('#project-file').addEventListener('change', async event => {const file = event.target.files[0]; event.target.value = ''; if (!file) return; try {
    if (file.size > 10 * 1024 * 1024) throw new Error('Проект должен быть не больше 10 МБ.'); const imported = validateProject(NadegErrors.parseProject(await file.text()));
    if (!await confirmAction('Открыть проект ЛР №3?', 'Текущий черновик ЛР №3 будет заменён. При необходимости сначала скачайте его JSON.')) return;
    state = imported; dirty(false); renderAll();
  } catch (e) {error(e);}});
  $('#new-project').addEventListener('click', async () => {if (await confirmAction('Новый проект ЛР №3?', 'Скачайте текущий JSON, если хотите сохранить его отдельно.')) {state = fresh(); dirty(false); showStage(0); renderAll();} $('.project-menu').open = false;});
  document.addEventListener('visibilitychange', () => {if (document.hidden) {clearTimeout(timer); persist(copy(state));}});
  window.addEventListener('beforeunload', event => {if (busy) {event.preventDefault(); event.returnValue = '';}});
  NadegErrors.configure(path => {
    if (path[0] === 'materials') {const card = $$('#materials article')[path[1] || 0]; return {stage: 0, node: card?.querySelector(path[2] === 'text' ? 'textarea' : 'input')};}
    if (path[0] === 'rows') {const row = $$('#analysis-rows tr')[path[1] || 0]; return {stage: 1, node: row && [...row.querySelectorAll('textarea')].find(n => n.dataset.field === (path[2] || 'condition'))};}
    const index = mainFields.indexOf(path[0]); return {stage: index >= 4 ? 2 : 0, node: index >= 0 ? $(selectors[index]) : null};
  }, showStage);
  renderAll(); initStorage();
  fetch('/api/lab3/status').then(r => {if (!r.ok) throw new Error(); return r.json();}).then(data => {enabled = data.enabled === true; $('#review-button').disabled = !enabled || busy; $('#ai-status').textContent = enabled ? 'Проверка по вашим материалам и тексту анализа.' : 'ИИ пока не подключён. Ручной анализ и экспорт доступны.';}).catch(() => {$('#review-button').disabled = true; $('#ai-status').textContent = 'Не удалось проверить доступность ИИ. Обновите страницу; ручной анализ доступен.';});
})();
