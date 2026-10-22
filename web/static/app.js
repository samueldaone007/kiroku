/* Kiroku — plain JavaScript, no frameworks.
   Flow: 1 Input -> 2 Settings -> 3 Release notes. */
'use strict';

(function () {
  var state = {
    text: '',
    lastOptions: null,
    payload: null,
    markdown: '',
    edits: {},       // hash -> { description?, section? }
    merged: null     // combined changelog, once built
  };

  var el = function (id) { return document.getElementById(id); };

  var input = el('paste-input');
  var statusEl = el('input-status');
  var errorBox = el('error-box');
  var summaryEl = el('result-summary');
  var previewPanel = el('panel-preview');
  var mdOutput = el('md-output');
  var emptyState = el('empty-state');

  /* ------------------------------------------------------------ */
  /* Theme                                                         */
  /* ------------------------------------------------------------ */
  var themeToggle = el('theme-toggle');
  function currentTheme() {
    var t = document.documentElement.getAttribute('data-theme');
    return t === 'paper' ? 'paper' : 'ink';
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme;
    themeToggle.setAttribute('aria-pressed', String(theme === 'paper'));
  }
  themeToggle.addEventListener('click', function () {
    applyTheme(currentTheme() === 'ink' ? 'paper' : 'ink');
    localStorage.setItem('kiroku-theme', currentTheme());
  });

  /* ------------------------------------------------------------ */
  /* Steps                                                         */
  /* ------------------------------------------------------------ */
  var stepButtons = Array.prototype.slice.call(document.querySelectorAll('.step'));
  var panels = ['step-1', 'step-2', 'step-3'];

  function showStep(n) {
    panels.forEach(function (id, i) {
      el(id).hidden = i !== n - 1;
    });
    stepButtons.forEach(function (btn, i) {
      btn.classList.toggle('is-current', i === n - 1);
      if (i === n - 1) {
        btn.setAttribute('aria-current', 'step');
      } else {
        btn.removeAttribute('aria-current');
      }
    });
    window.scrollTo({ top: 0, behavior: 'auto' });
  }
  stepButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var n = Number(btn.getAttribute('data-step'));
      if (n === 3 && !state.payload) {
        showError('No release notes yet. Generate them from the settings step first.');
        showStep(2);
        return;
      }
      showStep(n);
    });
  });

  /* ------------------------------------------------------------ */
  /* Errors and status                                             */
  /* ------------------------------------------------------------ */
  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }
  function clearError() { errorBox.hidden = true; errorBox.textContent = ''; }
  function setStatus(text) {
    statusEl.textContent = text;
    emptyState.hidden = text !== '';
  }

  /* ------------------------------------------------------------ */
  /* Clipboard / download helpers                                  */
  /* ------------------------------------------------------------ */
  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* ignore */ }
    document.body.removeChild(ta);
  }
  function copyText(text, btn) {
    if (!text) { return; }
    function done() {
      var old = btn.getAttribute('data-label') || btn.textContent;
      btn.textContent = 'Copied';
      setTimeout(function () {
        btn.textContent = old;
        btn.setAttribute('data-label', old);
      }, 1600);
    }
    btnsSetLabel(btn);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    } else {
      fallbackCopy(text); done();
    }
  }
  function btnsSetLabel(btn) {
    if (!btn.getAttribute('data-label')) { btn.setAttribute('data-label', btn.textContent); }
  }
  function downloadText(text, filename) {
    if (!text) { return; }
    var blob = new Blob([text], { type: 'text/markdown' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  /* Copy the suggested git command on step 1 */
  var gitCommand = el('git-command').textContent;
  el('copy-command').addEventListener('click', function () { copyText(gitCommand, this); });

  /* ------------------------------------------------------------ */
  /* Fetch from a public GitHub repository (step 1)                */
  /* ------------------------------------------------------------ */
  el('fetch-repo').addEventListener('click', function () {
    var btn = this;
    var owner = el('repo-owner').value.trim();
    var repo = el('repo-name').value.trim();
    var base = el('repo-from').value.trim();
    var head = el('repo-to').value.trim();
    var status = el('repo-status');
    clearError();
    status.textContent = '';
    if (!owner || !repo || !base || !head) {
      status.textContent = 'Fill in the owner, repository, from and to refs first.';
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Fetching…';
    fetch('/api/repo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ owner: owner, repo: repo, base: base, head: head })
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var error = new Error((data && data.error) || 'Could not fetch that repository.');
          error.status = res.status;
          throw error;
        }
        return data;
      });
    }).then(function (data) {
      btn.textContent = 'Fetch commits';
      if (data.count === 0) {
        status.textContent = data.message || 'No commits in that range.';
        return;
      }
      status.textContent = 'Fetched ' + data.count + ' commits from ' + owner + '/' + repo + ' — analyzed below.';
      input.value = data.text;
      setStatus('');
      el('analyze').click();
    }).catch(function (error) {
      btn.textContent = 'Fetch commits';
      showError(error.message || "Couldn't reach GitHub for that repository.");
    }).finally(function () { btn.disabled = false; });
  });

  /* ------------------------------------------------------------ */
  /* Options                                                       */
  /* ------------------------------------------------------------ */
  var SECTION_LIST = [
    { key: 'breaking', label: 'Breaking changes' },
    { key: 'added', label: 'Added' },
    { key: 'changed', label: 'Changed' },
    { key: 'deprecated', label: 'Deprecated' },
    { key: 'removed', label: 'Removed' },
    { key: 'fixed', label: 'Fixed' },
    { key: 'security', label: 'Security' },
    { key: 'maintenance', label: 'Maintenance' },
    { key: 'other', label: 'Other changes' }
  ];
  function availableSections(audience) {
    return SECTION_LIST.filter(function (s) {
      return audience !== 'users' || s.key !== 'maintenance';
    });
  }

  function collectOptions() {
    return {
      version: el('ver').value.trim(),
      date: el('release-date').value || '',
      compare_url: el('compare-url').value.trim() || null,
      audience: (document.querySelector('input[name="audience"]:checked') || {}).value || 'developers',
      format: (document.querySelector('input[name="format"]:checked') || {}).value || 'keep-a-changelog',
      hide_noise: el('hide-noise').checked,
      credit_contributors: el('credit').checked,
      show_hashes: el('show-hashes').checked,
      group_by_scope: el('group-scope').checked,
      ai_polish: el('ai-polish').checked,
      repo_url: el('repo-url').value.trim() || null
    };
  }

  /* Toggle the AI setup hint so no one is surprised mid-generate. */
  var aiPolisher = el('ai-polish');
  var aiSetupNote = el('ai-setup-note');
  function updateAiSetupNote() {
    aiSetupNote.hidden = !aiPolisher.checked;
  }
  aiPolisher.addEventListener('change', updateAiSetupNote);

  /* Dynamic audience hint so the choice is clear before generating. */
  var audienceHint = el('audience-hint');
  function updateAudienceHint() {
    var pick = document.querySelector('input[name="audience"]:checked');
    var value = pick ? pick.value : 'developers';
    audienceHint.textContent = value === 'users'
      ? 'Users: only user-facing changes. No scopes, no hashes, and housekeeping (docs, tests, chores) is left out — reads like a release announcement.'
      : 'Developers: every change, with scopes and short hashes so the team can find the exact commit.';
  }
  Array.prototype.slice.call(document.querySelectorAll('input[name="audience"]'))
    .forEach(function (radio) { radio.addEventListener('change', updateAudienceHint); });

  function postGenerate(text, options, edits) {
    return fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, options: options, edits: edits || {} })
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          var error = new Error((data && data.error) || 'Something went wrong.');
          error.status = res.status;
          throw error;
        }
        return data;
      });
    });
  }

  /* ------------------------------------------------------------ */
  /* Step 1: analyze                                               */
  /* ------------------------------------------------------------ */
  el('analyze').addEventListener('click', function () {
    var btn = this;
    var text = input.value;
    clearError();
    setStatus('');
    if (!text.trim()) {
      setStatus('Nothing to analyze yet. Paste a git log first.');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Analyzing…';
    postGenerate(text, collectOptions(), {})
      .then(function (data) {
        state.text = text;
        state.lastOptions = null;
        state.payload = null;
        state.markdown = '';
        state.edits = {};
        resetMergeBox();
        btn.textContent = 'Analyze';
        setStatus('Found ' + data.stats.summary + '. Now pick your settings.');
        showStep(2);
      })
      .catch(function (error) {
        btn.textContent = 'Analyze';
        showError(error.message || "I couldn't read that. Did you use the command above?");
      })
      .finally(function () { btn.disabled = false; });
  });

  /* ------------------------------------------------------------ */
  /* Step 2: generate                                              */
  /* ------------------------------------------------------------ */
  var generateBtn = el('generate');
  var generateLabel = generateBtn.textContent;

  function refreshResult() {
    var text = input.value;
    clearError();
    if (!text.trim()) {
      showError('Nothing to work with. Go back to step 1 and paste a git log.');
      showStep(1);
      return Promise.resolve();
    }
    generateBtn.disabled = true;
    generateBtn.textContent = 'Working…';
    return postGenerate(text, collectOptions(), state.edits)
      .then(function (data) {
        state.payload = data;
        state.lastOptions = collectOptions();
        state.markdown = data.markdown;
        pruneEdits(data);
        renderResults(data);
        return data;
      })
      .catch(function (error) {
        showError(error.message || "I couldn't read that. Did you use the command above?");
      })
      .finally(function () {
        generateBtn.disabled = false;
        generateBtn.textContent = generateLabel;
      });
  }

  generateBtn.addEventListener('click', function () {
    resetMergeBox();
    refreshResult().then(function () {
      if (state.payload) { showStep(3); }
    });
  });

  el('back-to-settings').addEventListener('click', function () { showStep(2); });

  /* ------------------------------------------------------------ */
  /* Step 3: results                                               */
  /* ------------------------------------------------------------ */
  var ICONS = {
    alert: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    plus: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    arrows: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 2v6h-6"/><path d="m7 6 4-4 4 4"/><path d="M7 22v-6h6"/><path d="m17 18-4 4-4-4"/></svg>',
    clock: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></svg>',
    minus: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    wrench: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    shield: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-3 8-10V6l-8-3-8 3v6c0 7 8 10 8 10z"/></svg>',
    tools: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
    help: '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
  };
  var PENCIL = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>';

  function renderResults(payload) {
    summaryEl.textContent = payload.stats.summary + '.';
    if (payload.stats.needs_review > 0) {
      summaryEl.textContent +=
        ' ' + payload.stats.needs_review + ' entr' + (payload.stats.needs_review === 1 ? 'y' : 'ies') +
        ' need a closer look and are marked for review.';
    }
    if (payload.audience === 'users' && payload.stats.hidden > 0) {
      summaryEl.textContent +=
        ' For the Users audience, hidden commits can include housekeeping (docs, tests, chores). Switch to Developers to include them.';
    }
    if (payload.ai && payload.ai.applied) {
      summaryEl.textContent += ' AI polish rewrote wording and added a drafted summary — hover the AI chip to see original text.';
    }
    renderPreview(payload);
    mdOutput.textContent = payload.markdown;
    activateTab(activeTab());
  }

  function renderPreview(payload) {
    previewPanel.textContent = '';
    if (payload.ai && payload.ai.error) {
      var errorNote = document.createElement('p');
      errorNote.className = 'ai-note';
      errorNote.textContent = payload.ai.error;
      previewPanel.appendChild(errorNote);
    }
    if (payload.intro) {
      var intro = document.createElement('aside');
      intro.className = 'ai-intro';
      var chip = document.createElement('span');
      chip.className = 'ai-chip';
      chip.textContent = 'AI';
      var label = document.createElement('span');
      label.className = 'ai-intro-label';
      label.textContent = 'Drafted summary';
      var text = document.createElement('div');
      text.className = 'ai-intro-text';
      text.textContent = payload.intro;
      intro.appendChild(chip);
      intro.appendChild(label);
      intro.appendChild(text);
      previewPanel.appendChild(intro);
    }
    if (!payload.sections.length) {
      var none = document.createElement('p');
      none.className = 'empty-state';
      none.style.margin = '0';
      none.textContent = 'Nothing to show';
      previewPanel.appendChild(none);
      return;
    }
    payload.sections.forEach(function (section) {
      var card = document.createElement('section');
      card.className = 'section-card';

      var head = document.createElement('header');
      head.className = 'section-head';

      var badge = document.createElement('span');
      badge.className = 'badge ' + section.color;
      var icon = document.createElement('span');
      icon.innerHTML = ICONS[section.icon] || '';
      icon.setAttribute('aria-hidden', 'true');
      var label = document.createElement('span');
      label.textContent = section.label;
      badge.appendChild(icon);
      badge.appendChild(label);

      var count = document.createElement('span');
      count.className = 'count';
      count.textContent = String(section.count);

      head.appendChild(badge);
      head.appendChild(count);
      card.appendChild(head);

      var list = document.createElement('ul');
      list.className = 'entry-list';
      section.entries.forEach(function (entry) {
        list.appendChild(buildEntry(entry));
      });
      card.appendChild(list);
      previewPanel.appendChild(card);
    });
  }

  function buildEntry(entry) {
    var li = document.createElement('li');
    li.className = 'entry' + (entry.needs_review ? ' entry-review' : '');

    var text = document.createElement('div');
    text.className = 'entry-text';
    text.textContent = entry.description;
    li.appendChild(text);

    var tools = document.createElement('div');
    tools.className = 'entry-tools';

    var select = document.createElement('select');
    select.className = 'assign-select';
    select.setAttribute('aria-label', 'Move this entry to another section');
    buildSectionOptions(select, entry.section);
    select.addEventListener('change', function () {
      setEdit(entry.id, { section: select.value });
      refreshResult();
    });
    tools.appendChild(select);

    var editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'icon-button';
    editBtn.title = 'Edit description';
    editBtn.innerHTML = PENCIL;
    tools.appendChild(editBtn);
    editBtn.addEventListener('click', function () { startEdit(li, entry, text); });

    li.appendChild(tools);

    if (entry.needs_review) {
      var flag = document.createElement('span');
      flag.className = 'review-flag';
      flag.textContent = 'Needs review';
      li.appendChild(flag);
    }
    if (entry.polished) {
      var chip = document.createElement('span');
      chip.className = 'ai-chip';
      chip.textContent = 'AI';
      chip.title = 'Reworded by AI. Original: ' + (entry.original_description || entry.description);
      li.appendChild(chip);
    }
    return li;
  }

  function buildSectionOptions(select, current) {
    select.textContent = '';
    var audience = (state.lastOptions || {}).audience;
    var options = availableSections(audience);
    var hasCurrent = false;
    options.forEach(function (s) {
      var opt = document.createElement('option');
      opt.value = s.key;
      opt.textContent = s.label;
      if (s.key === current) {
        opt.selected = true;
        hasCurrent = true;
      }
      select.appendChild(opt);
    });
    if (!hasCurrent) {
      var placeholder = document.createElement('option');
      placeholder.value = current || 'other';
      placeholder.textContent = current || 'Other changes';
      placeholder.selected = true;
      select.appendChild(placeholder);
    }
  }

  function startEdit(li, entry, textEl) {
    if (li.querySelector('.entry-edit-input')) { return; }
    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'entry-edit-input';
    input.value = entry.description;
    var original = entry.description;
    textEl.replaceWith(input);
    input.focus();
    input.select();

    var finished = false;
    function commit() {
      if (finished) { return; }
      finished = true;
      var value = input.value.trim();
      if (value && value !== original) {
        setEdit(entry.id, { description: value });
      }
      refreshResult();
    }
    function cancel() {
      if (finished) { return; }
      finished = true;
      refreshResult();
    }
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      else if (e.key === 'Escape') { cancel(); }
    });
    input.addEventListener('blur', commit);
  }

  function setEdit(id, changes) {
    var edit = state.edits[id] || {};
    Object.keys(changes).forEach(function (k) { edit[k] = changes[k]; });
    state.edits[id] = edit;
  }

  function pruneEdits(payload) {
    var seen = {};
    payload.sections.forEach(function (section) {
      section.entries.forEach(function (entry) { seen[entry.id] = entry; });
    });
    Object.keys(state.edits).forEach(function (id) {
      var edit = state.edits[id];
      var entry = seen[id];
      if (!entry) { delete state.edits[id]; return; }
      if (edit.description !== undefined && edit.description === entry.description) {
        delete edit.description;
      }
      if (edit.section !== undefined && edit.section === entry.section) {
        delete edit.section;
      }
      if (!Object.keys(edit).length) { delete state.edits[id]; }
    });
  }

  /* ------------------------------------------------------------ */
  /* Result tabs                                                   */
  /* ------------------------------------------------------------ */
  var tabButtons = [el('tab-preview'), el('tab-markdown')];
  function activeTab() {
    for (var i = 0; i < tabButtons.length; i++) {
      if (tabButtons[i].getAttribute('aria-selected') === 'true') { return tabButtons[i].id; }
    }
    return 'tab-preview';
  }
  function activateTab(id) {
    tabButtons.forEach(function (btn) {
      var selected = btn.id === id;
      btn.setAttribute('aria-selected', String(selected));
      btn.tabIndex = selected ? 0 : -1;
      var panel = el(btn.getAttribute('aria-controls'));
      panel.hidden = !selected;
    });
  }
  tabButtons.forEach(function (btn) {
    btn.addEventListener('click', function () { activateTab(btn.id); });
  });

  function handleTabKeys(event, current) {
    var index = tabButtons.indexOf(current);
    var next = null;
    if (event.key === 'ArrowRight') { next = tabButtons[(index + 1) % tabButtons.length]; }
    else if (event.key === 'ArrowLeft') { next = tabButtons[(index - 1 + tabButtons.length) % tabButtons.length]; }
    if (next) {
      event.preventDefault();
      next.focus();
      activateTab(next.id);
    }
  }
  tabButtons.forEach(function (btn) {
    btn.addEventListener('keydown', function (e) { handleTabKeys(e, btn); });
  });

  /* ------------------------------------------------------------ */
  /* Copy / download the result Markdown                           */
  /* ------------------------------------------------------------ */
  el('copy-notes').addEventListener('click', function () { copyText(state.markdown, this); });
  el('download-notes').addEventListener('click', function () {
    downloadText(state.markdown, 'CHANGELOG.md');
  });

  /* ------------------------------------------------------------ */
  /* Add to an existing changelog                                  */
  /* ------------------------------------------------------------ */
  function resetMergeBox() {
    state.merged = null;
    el('merge-result').hidden = true;
    el('merge-note').textContent = '';
    el('merged-output').value = '';
  }

  function escapeRegExp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /* Insert the new release block into an existing changelog.
     Returns { text, alreadyPresent }.
     - Duplicate version headings are detected and left untouched.
     - A leading "Unreleased" section keeps its spot at the top.
     - Otherwise, no section headings: the new block is appended. */
  function insertRelease(existing, block) {
    var text = existing.trim();
    var body = block.trim();
    if (!text) { return { text: body + '\n', alreadyPresent: false }; }

    var version = /^##\s*\[([^\]]+)\]/.exec(body);
    if (version) {
      var re = new RegExp('^##\\s*\\[' + escapeRegExp(version[1]) + '\\]', 'm');
      if (re.test(text)) {
        return { text: text + '\n', alreadyPresent: true };
      }
    }

    var lines = text.split('\n');
    var headings = [];
    for (var i = 0; i < lines.length; i++) {
      if (/^##\s/.test(lines[i])) { headings.push(i); }
    }
    if (!headings.length) {
      return { text: text + '\n\n' + body + '\n', alreadyPresent: false };
    }

    var insertAt = headings[0];
    var firstLine = lines[insertAt];
    var nextLine = lines[insertAt + 1] || '';
    if (/unreleased/i.test(firstLine) || /unreleased/i.test(nextLine)) {
      insertAt = headings[1];
    }
    var merged;
    if (insertAt === undefined) {
      merged = text + '\n\n' + body + '\n';
    } else {
      lines.splice(insertAt, 0, '', body, '');
      merged = lines.join('\n').replace(/\n{3,}/g, '\n\n') + '\n';
    }
    return { text: merged, alreadyPresent: false };
  }

  el('merge-notes').addEventListener('click', function () {
    var note = el('merge-note');
    var existing = el('existing-input').value;
    note.textContent = '';
    if (!state.markdown) {
      note.textContent = 'Generate release notes first.';
      return;
    }
    if (!existing.trim()) {
      note.textContent = 'Nothing on record yet. Paste your current changelog first.';
      return;
    }
    var result = insertRelease(existing, state.markdown);
    state.merged = result.text;
    el('merged-output').value = result.text;
    el('merge-result').hidden = false;
    note.textContent = result.alreadyPresent
      ? "That version is already in the changelog — nothing was added."
      : 'New release added above the previous entries.';
  });

  el('copy-merged').addEventListener('click', function () { copyText(state.merged, this); });
  el('download-merged').addEventListener('click', function () {
    downloadText(state.merged, 'CHANGELOG.md');
  });

  /* ------------------------------------------------------------ */
  /* Initialisation                                                */
  /* ------------------------------------------------------------ */
  (function init() {
    el('release-date').value = new Date().toISOString().slice(0, 10);
    updateAudienceHint();
    updateAiSetupNote();
    activateTab('tab-preview');
    showStep(1);
    setStatus('');
  })();
})();