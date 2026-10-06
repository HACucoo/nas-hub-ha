/**
 * NAS Hub Lovelace card — one module, one resource:
 *   URL:  /nas_hub_frontend/nas-hub-card.js
 *   Type: JavaScript module
 *
 * custom:nas-hub-card
 *   entities:              <- one or more NAS Hub sensors; their lists are merged
 *     - sensor.jellyfin_neu
 *   title: "Neu"           <- card heading (omit to hide)
 *   layout: tiles          <- tiles (large, like Homarr) or rows (slim, like the
 *                             Meal Planner card — fits a swipe card on the start page)
 *   max_items: 8
 *   image_style: auto      <- auto (upcoming lists muted, others bright), bright or muted
 *   show_genres: true      <- genre chips (tiles only)
 *   relative: true         <- "Heute", "Morgen", "vor 2 Tagen" on the right
 *   open_links: false      <- tapping an item opens it in Jellyfin, Sonarr, …
 *   empty_text: "…"        <- shown when every list is empty
 *   lang: "de"             <- "de" or "en" (default: Home Assistant's language)
 * Everything except lang can be set in the visual card editor.
 *
 * The data comes from the sensors' "items" attribute, so the card keeps
 * showing the last state (and the cached artwork) while the NAS sleeps.
 */

const STRINGS = {
  de: {
    kind: { movie: 'Film', series: 'Serie', episode: 'Serie', audiobook: 'Hörbuch', ebook: 'Buch' },
    dateType: { digital: 'Digital', physical: 'Disc', cinema: 'Kino' },
    today: 'Heute', tomorrow: 'Morgen', yesterday: 'Gestern',
    inDays: n => `in ${n} Tagen`, daysAgo: n => `vor ${n} Tagen`,
    newEpisodes: n => `${n} neue Folgen`, episodes: n => `${n} Folgen`,
    newSeries: n => (n ? `Neue Serie · ${n} ${n === 1 ? 'Staffel' : 'Staffeln'}` : 'Neue Serie'),
    left: t => `noch ${t}`,
    status: { downloading: 'lädt', queued: 'wartet', paused: 'pausiert', importpending: 'Import wartet', importing: 'importiert', imported: 'fertig', completed: 'fertig', delay: 'verzögert', warning: 'Warnung', failed: 'fehlgeschlagen', failedpending: 'fehlgeschlagen' },
    play: { direct: 'Direkt', audio: 'Ton umgewandelt', transcode: 'Transkodiert' },
    paused: 'Pause',
    sentTo: r => `an ${r}`,
    readBy: n => `gelesen von ${n}`,
    empty: { upcoming: 'Nichts angekündigt', now_playing: 'Gerade läuft nichts', queue: 'Keine Downloads', in_progress: 'Nichts angefangen', sent: 'Noch nichts verschickt', requests: 'Keine Wünsche', other: 'Noch nichts da' },
    request: { available: 'Verfügbar', partial: 'Teilweise da', processing: 'Wird besorgt', pending: 'Wartet auf Freigabe', declined: 'Abgelehnt' },
    stand: t => `Stand ${t}`, asleep: 'NAS schläft', unreachable: 'nicht erreichbar',
    noEntities: 'Bitte im Karteneditor mindestens einen NAS-Hub-Sensor wählen.',
  },
  en: {
    kind: { movie: 'Movie', series: 'TV', episode: 'TV', audiobook: 'Audiobook', ebook: 'Book' },
    dateType: { digital: 'Digital', physical: 'Disc', cinema: 'Cinema' },
    today: 'Today', tomorrow: 'Tomorrow', yesterday: 'Yesterday',
    inDays: n => `in ${n} days`, daysAgo: n => `${n} days ago`,
    newEpisodes: n => `${n} new episodes`, episodes: n => `${n} episodes`,
    newSeries: n => (n ? `New series · ${n} ${n === 1 ? 'season' : 'seasons'}` : 'New series'),
    left: t => `${t} left`,
    status: { downloading: 'downloading', queued: 'queued', paused: 'paused', importpending: 'import pending', importing: 'importing', imported: 'done', completed: 'done', delay: 'delayed', warning: 'warning', failed: 'failed', failedpending: 'failed' },
    play: { direct: 'Direct', audio: 'Audio converted', transcode: 'Transcoding' },
    paused: 'Paused',
    sentTo: r => `to ${r}`,
    readBy: n => `read by ${n}`,
    empty: { upcoming: 'Nothing announced', now_playing: 'Nothing playing', queue: 'No downloads', in_progress: 'Nothing started', sent: 'Nothing sent yet', requests: 'No requests', other: 'Nothing here yet' },
    request: { available: 'Available', partial: 'Partly here', processing: 'Processing', pending: 'Awaiting approval', declined: 'Declined' },
    stand: t => `as of ${t}`, asleep: 'NAS asleep', unreachable: 'unreachable',
    noEntities: 'Pick at least one NAS Hub sensor in the card editor.',
  },
};

// Solid badges read the same on a photo and in either theme
const KIND_STYLE = {
  movie:     { color: '#1565c0', icon: 'mdi:filmstrip' },
  series:    { color: '#6a1b9a', icon: 'mdi:television-classic' },
  episode:   { color: '#6a1b9a', icon: 'mdi:television-classic' },
  audiobook: { color: '#00796b', icon: 'mdi:headphones' },
  ebook:     { color: '#795548', icon: 'mdi:book-open-page-variant' },
};

function esc(value) {
  const el = document.createElement('span');
  el.textContent = value == null ? '' : String(value);
  return el.innerHTML;
}

function parseDate(value) {
  if (!value) return null;
  // A bare date is a calendar day, not UTC midnight
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(value);
  return isNaN(d) ? null : d;
}

function dayDiff(date) {
  const a = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const now = new Date();
  const b = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((a - b) / 86400000);
}

function hasTime(value) {
  return typeof value === 'string' && value.length > 10;
}

/** "02:15:30" (Sonarr/Radarr timeleft) → "2 h 15 min" */
function formatTimeleft(value) {
  if (!value) return '';
  const m = /^(?:(\d+)\.)?(\d+):(\d+):(\d+)/.exec(value);
  if (!m) return value;
  const hours = (+(m[1] || 0)) * 24 + +m[2];
  const minutes = +m[3];
  if (hours > 0) return `${hours} h${minutes ? ` ${minutes} min` : ''}`;
  return `${Math.max(1, minutes)} min`;
}

class NasHubCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.shadowRoot.addEventListener('click', ev => this._onClick(ev));
  }

  static getConfigElement() {
    return document.createElement('nas-hub-card-editor');
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(id =>
      id.startsWith('sensor.') && Array.isArray(hass.states[id].attributes.items)
      && hass.states[id].attributes.service);
    return { entities: entity ? [entity] : [] };
  }

  setConfig(config) {
    if (!config) throw new Error('Invalid configuration');
    const entities = config.entities || (config.entity ? [config.entity] : []);
    this._config = { ...config, entities: Array.isArray(entities) ? entities : [entities] };
    this._lastStates = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Re-render only when one of our sensors changed
    const states = (this._config?.entities || []).map(id => hass.states[id]);
    if (this._lastStates && states.every((s, i) => s === this._lastStates[i])) return;
    this._lastStates = states;
    this._render();
  }

  _lang() {
    const lang = this._config.lang || this._hass?.language || navigator.language || 'de';
    return lang.startsWith('de') ? 'de' : 'en';
  }

  _onClick(ev) {
    if (!this._config.open_links || this.editMode || this.preview) return;
    const el = ev.target.closest('[data-link]');
    if (el && el.dataset.link) window.open(el.dataset.link, '_blank', 'noopener');
  }

  _collect() {
    const states = this._config.entities.map(id => this._hass.states[id]).filter(Boolean);
    let items = [];
    for (const st of states) {
      for (const item of st.attributes.items || []) items.push({ ...item, _list: st.attributes.list });
    }
    const order = states.length ? states[0].attributes.order : 'desc';
    if (states.length > 1 && order !== 'none') {
      const key = i => (i.date ? String(i.date) : '');
      items.sort((a, b) => (order === 'asc' ? key(a).localeCompare(key(b)) : key(b).localeCompare(key(a))));
    }
    const max = Math.max(1, Math.min(30, Number(this._config.max_items) || 8));
    return { states, items: items.slice(0, max), list: states[0]?.attributes.list };
  }

  _relative(item, S) {
    if (this._config.relative === false) return '';
    if (item.kind === 'download' || item.kind === 'session') return '';
    const d = parseDate(item.date);
    if (!d) return '';
    const n = dayDiff(d);
    if (n === 0) return S.today;
    if (n === 1) return S.tomorrow;
    if (n === -1) return S.yesterday;
    return n > 1 ? S.inDays(n) : S.daysAgo(-n);
  }

  _dateLabel(item, lang) {
    // Newly added movies and series show their release, like Homarr does
    const value = item.date_type === 'added' && item.released ? item.released : item.date;
    const d = parseDate(value);
    if (!d) return '';
    const opts = { day: '2-digit', month: '2-digit' };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
    if (item.date_type === 'air') opts.weekday = 'short';
    let text = new Intl.DateTimeFormat(lang, opts).format(d);
    if (item.date_type === 'air' && hasTime(value)) {
      text += `, ${new Intl.DateTimeFormat(lang, { hour: '2-digit', minute: '2-digit' }).format(d)}`;
    }
    return text;
  }

  /** Everything a row or tile shows, already as plain strings. */
  _view(item, S, lang) {
    const media = item.media || item.kind;
    const style = KIND_STYLE[media] || KIND_STYLE[item.kind] || { color: '#546e7a', icon: 'mdi:nas' };
    const view = {
      title: item.title || '—',
      subtitle: item.subtitle || '',
      badge: S.kind[media] || '',
      color: style.color,
      icon: style.icon,
      chips: [],
      meta: [],
      progress: typeof item.progress === 'number' ? Math.max(0, Math.min(1, item.progress)) : null,
      rel: this._relative(item, S),
      image: item.image || '',
      link: item.link || '',
    };

    if (item.new_series) view.chips.push({ text: S.newSeries(item.season_count), accent: true });
    else if (item.episode) view.chips.push({ text: item.episode, accent: true });
    else if (item.new_count > 1) {
      view.chips.push({ text: item.kind === 'series' ? S.newEpisodes(item.new_count) : S.episodes(item.new_count), accent: true });
    }

    if (item.kind === 'download') {
      const pct = view.progress != null ? `${Math.round(view.progress * 100)} %` : '';
      const status = S.status[(item.status || '').replace(/[^a-z]/g, '')] || item.status || '';
      const left = item.timeleft && item.status === 'downloading' ? S.left(formatTimeleft(item.timeleft)) : '';
      view.meta.push(...[pct, left || status].filter(Boolean));
    } else if (item.kind === 'session') {
      if (item.meta) view.meta.push(item.meta);
      if (item.paused) view.chips.push({ text: S.paused });
      if (item.play_method) view.chips.push({ text: S.play[item.play_method] || item.play_method, warn: item.play_method === 'transcode' });
      // Paused shows as a chip only — a dimmed row is hard to read on a wall tablet
    } else {
      const date = this._dateLabel(item, lang);
      if (date) view.meta.push({ icon: 'mdi:calendar-blank', text: date });
      if (S.dateType[item.date_type]) view.chips.unshift({ text: S.dateType[item.date_type] });
      if (item.request_status) view.chips.unshift({ text: S.request[item.request_status] || item.request_status, accent: item.request_status === 'available', warn: item.request_status === 'declined' });
      if (item.kind === 'ebook' && item.recipient) view.meta.push(S.sentTo(item.recipient));
      else if (item.meta) view.meta.push(item.meta);
      if (item.kind === 'audiobook' && item.narrator && !item.series) view.meta.push(S.readBy(item.narrator));
      if (item.rating) view.meta.push({ icon: 'mdi:star', text: item.rating.toFixed(1) });
      if (item.date_type === 'progress' && view.progress != null) view.meta.push(`${Math.round(view.progress * 100)} %`);
    }

    if (this._config.show_genres !== false) {
      for (const g of item.genres || []) view.chips.push({ text: g, genre: true });
    }
    return view;
  }

  _metaHTML(meta) {
    return meta.map(m => (typeof m === 'string'
      ? `<span>${esc(m)}</span>`
      : `<span class="mi"><ha-icon icon="${m.icon}"></ha-icon>${esc(m.text)}</span>`)).join('<span class="dot">•</span>');
  }

  _chipsHTML(chips, limit) {
    const shown = chips.slice(0, limit);
    const more = chips.length - shown.length;
    return shown.map(c => `<span class="chip${c.accent ? ' accent' : ''}${c.warn ? ' warn' : ''}">${esc(c.text)}</span>`).join('')
      + (more > 0 ? `<span class="chip">+${more}</span>` : '');
  }

  /** Upcoming lists get muted artwork, so "new" and "next" differ at a glance. */
  _muted(list) {
    const style = this._config.image_style || 'auto';
    if (style === 'auto') return list === 'upcoming';
    return style === 'muted';
  }

  _tile(v) {
    return `
      <div class="tile${v.image ? ' has-photo' : ''}"${v.link ? ` data-link="${esc(v.link)}"` : ''}>
        ${v.image ? `<div class="bg" style="background-image:url('${esc(v.image)}')"></div>` : ''}
        <div class="body">
          <div class="head">
            <div class="name">${esc(v.title)}</div>
            ${v.badge ? `<span class="badge" style="background:${v.color}">${esc(v.badge)}</span>` : ''}
          </div>
          ${v.subtitle ? `<div class="sub">${esc(v.subtitle)}</div>` : ''}
          ${v.meta.length ? `<div class="meta">${this._metaHTML(v.meta)}</div>` : ''}
          ${v.chips.length ? `<div class="chips">${this._chipsHTML(v.chips, 4)}</div>` : ''}
          ${v.rel ? `<span class="rel corner">${esc(v.rel)}</span>` : ''}
        </div>
        ${v.progress != null ? `<div class="bar"><div style="width:${(v.progress * 100).toFixed(1)}%"></div></div>` : ''}
      </div>`;
  }

  _row(v) {
    const meta = v.meta.slice(0, 2);
    // One chip fits a slim row: the episode or status, never a genre
    const chip = v.chips.find(c => !c.genre);
    return `
      <div class="row${v.image ? ' has-photo' : ''}"${v.link ? ` data-link="${esc(v.link)}"` : ''}>
        ${v.image ? `<div class="bg" style="background-image:url('${esc(v.image)}')"></div>` : ''}
        <div class="thumb" style="background-color:${v.color}">
          <ha-icon icon="${v.icon}"></ha-icon>
        </div>
        <div class="text">
          <div class="meta">
            ${chip ? `<span class="chip${chip.accent ? ' accent' : ''}${chip.warn ? ' warn' : ''}">${esc(chip.text)}</span>` : ''}
            ${this._metaHTML(meta)}
          </div>
          <div class="name">${esc(v.title)}${v.subtitle ? `<span class="sub-inline"> · ${esc(v.subtitle)}</span>` : ''}</div>
        </div>
        ${v.rel ? `<span class="rel">${esc(v.rel)}</span>` : ''}
        ${v.progress != null ? `<div class="bar"><div style="width:${(v.progress * 100).toFixed(1)}%"></div></div>` : ''}
      </div>`;
  }

  _footer(states, S, lang) {
    const stale = states.filter(s => s.attributes.stale);
    if (!stale.length) return '';
    const times = stale.map(s => parseDate(s.attributes.updated)).filter(Boolean).sort((a, b) => a - b);
    const asleep = stale.some(s => s.attributes.asleep);
    const parts = [];
    if (times.length) {
      const fmt = new Intl.DateTimeFormat(lang, { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
      parts.push(S.stand(fmt.format(times[0])));
    }
    parts.push(asleep ? S.asleep : S.unreachable);
    return `<div class="footer"><ha-icon icon="${asleep ? 'mdi:sleep' : 'mdi:lan-disconnect'}"></ha-icon>${esc(parts.join(' · '))}</div>`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const lang = this._lang();
    const S = STRINGS[lang];
    const layout = this._config.layout === 'rows' ? 'rows' : 'tiles';

    let content;
    let footer = '';
    if (!this._config.entities.length) {
      content = `<div class="empty-note">${esc(S.noEntities)}</div>`;
    } else {
      const { states, items, list } = this._collect();
      this._isMuted = this._muted(list);
      const views = items.map(i => this._view(i, S, lang));
      content = views.length
        ? views.map(v => (layout === 'rows' ? this._row(v) : this._tile(v))).join('')
        : `<div class="empty-note">${esc(this._config.empty_text || S.empty[list] || S.empty.other)}</div>`;
      footer = this._footer(states, S, lang);
      this._count = views.length;
    }

    this.shadowRoot.innerHTML = `
      <style>${CARD_CSS}</style>
      <ha-card class="${layout}${this._config.open_links ? ' links' : ''}${this._isMuted ? ' muted' : ''}">
        ${this._config.title ? `<div class="title">${esc(this._config.title)}</div>` : ''}
        <div class="list">${content}</div>
        ${footer}
      </ha-card>`;
  }

  getCardSize() {
    const n = typeof this._count === 'number' ? this._count : 4;
    return 1 + Math.ceil(n * (this._config?.layout === 'rows' ? 0.9 : 1.8));
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: 'auto' };
  }
}

const CARD_CSS = `
  :host { display: block; }
  ha-card { padding: 12px; }
  .title { font-size: 0.95rem; font-weight: 600; color: var(--primary-text-color); margin: 2px 2px 10px; }
  .list { display: flex; flex-direction: column; gap: 8px; }
  .links [data-link] { cursor: pointer; }

  .tile, .row {
    position: relative;
    overflow: hidden;
    border-radius: 10px;
    border: 1px solid var(--divider-color);
    background: var(--secondary-background-color, rgba(127,127,127,0.12));
    color: var(--primary-text-color);
  }
  /* The artwork fills the item; a gradient keeps the text side readable.
     No blur or backdrop-filter: cheap enough for an old wall tablet. */
  .bg { position: absolute; inset: 0; background-size: cover; background-position: center; }
  /* Like the Meal Planner card: dark behind the text, the artwork at full
     brightness on the right edge */
  .has-photo::after {
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(90deg, rgba(0,0,0,0.86) 0%, rgba(0,0,0,0.55) 45%, rgba(0,0,0,0) 100%);
  }
  /* Upcoming: washed out and darker, so it never looks like it is already there */
  .muted .bg { filter: grayscale(0.8); opacity: 0.45; }
  .muted .has-photo::after {
    background: linear-gradient(90deg, rgba(0,0,0,0.80) 0%, rgba(0,0,0,0.55) 50%, rgba(0,0,0,0.30) 100%);
  }
  .has-photo { color: #fff; border-color: rgba(255,255,255,0.10); }
  .tile > :not(.bg), .row > :not(.bg) { position: relative; z-index: 1; }

  .name { font-weight: 700; line-height: 1.25; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .has-photo .name { text-shadow: 0 1px 2px rgba(0,0,0,0.6); }
  .meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; font-size: 0.75rem; line-height: 1.3; opacity: 0.85; }
  .meta .dot { opacity: 0.6; }
  .mi { display: inline-flex; align-items: center; gap: 3px; }
  .mi ha-icon { --mdc-icon-size: 13px; }

  .chip {
    display: inline-block;
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    padding: 2px 7px; border-radius: 5px; white-space: nowrap;
    background: rgba(127,127,127,0.25);
    border: 1px solid rgba(127,127,127,0.35);
  }
  .has-photo .chip { background: rgba(0,0,0,0.45); border-color: rgba(255,255,255,0.18); }
  .chip.accent { background: var(--primary-color); border-color: transparent; color: var(--text-primary-color, #fff); }
  .chip.warn { background: #c62828; border-color: transparent; color: #fff; }
  .badge {
    flex-shrink: 0;
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 2px 8px; border-radius: 999px; color: #fff;
  }
  .rel {
    flex-shrink: 0;
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 2px 7px; border-radius: 5px; white-space: nowrap;
    background: rgba(127,127,127,0.28);
  }
  .has-photo .rel { background: rgba(0,0,0,0.45); }

  .bar { position: absolute !important; left: 0; right: 0; bottom: 0; height: 3px; background: rgba(127,127,127,0.3); }
  .bar > div { height: 100%; background: var(--primary-color); }

  /* tiles: large, like Homarr */
  .tile .body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 5px; min-height: 64px; }
  .tile .head { display: flex; align-items: flex-start; gap: 8px; }
  .tile .name { flex: 1; min-width: 0; font-size: 1rem; }
  .tile .sub { font-size: 0.85rem; opacity: 0.9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tile .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; padding-right: 76px; }
  .tile .rel.corner { position: absolute; right: 10px; bottom: 10px; }

  /* rows: slim, like the Meal Planner card */
  .row { display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 6px 10px 6px 6px; }
  .row .thumb {
    width: 36px; height: 36px; flex-shrink: 0; border-radius: 7px;
    display: flex; align-items: center; justify-content: center; color: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.4);
  }
  .row .thumb ha-icon { --mdc-icon-size: 20px; }
  .row .text { flex: 1; min-width: 0; }
  .row .meta { flex-wrap: nowrap; overflow: hidden; white-space: nowrap; }
  .row .name { font-size: 0.95rem; }
  .row .sub-inline { font-weight: 400; opacity: 0.85; }

  .empty-note { color: var(--secondary-text-color); font-style: italic; font-size: 0.875rem; padding: 8px 4px; }
  .footer {
    display: flex; align-items: center; gap: 6px; margin: 10px 2px 0;
    font-size: 0.75rem; color: var(--secondary-text-color);
  }
  .footer ha-icon { --mdc-icon-size: 15px; }
`;

// ── Visual editor ───────────────────────────────────────────────────────────

const EDITOR_LABELS = {
  de: {
    entities: 'Listen (NAS-Hub-Sensoren, werden zusammengeführt)',
    title: 'Überschrift (leer = keine)',
    layout: 'Darstellung',
    layout_tiles: 'Kacheln (groß)',
    layout_rows: 'Zeilen (schmal)',
    max_items: 'Höchstens so viele Einträge',
    image_style: 'Bilder',
    image_style_auto: 'Automatisch (Kommendes gedämpft)',
    image_style_bright: 'Hell',
    image_style_muted: 'Gedämpft',
    show_genres: 'Genres als Chips zeigen',
    relative: 'Heute / Morgen / vor x Tagen rechts zeigen',
    open_links: 'Tippen öffnet den Eintrag im Dienst',
    empty_text: 'Text, wenn nichts da ist (leer = Standard)',
  },
  en: {
    entities: 'Lists (NAS Hub sensors, merged)',
    title: 'Heading (empty = none)',
    layout: 'Layout',
    layout_tiles: 'Tiles (large)',
    layout_rows: 'Rows (slim)',
    max_items: 'At most this many items',
    image_style: 'Artwork',
    image_style_auto: 'Automatic (upcoming muted)',
    image_style_bright: 'Bright',
    image_style_muted: 'Muted',
    show_genres: 'Show genres as chips',
    relative: 'Show today / tomorrow / x days ago on the right',
    open_links: 'Tapping opens the item in its service',
    empty_text: 'Text when there is nothing (empty = default)',
  },
};

function editorSchema(L) {
  return [
    { name: 'entities', selector: { entity: { multiple: true, filter: { integration: 'nas_hub', domain: 'sensor' } } } },
    { name: 'title', selector: { text: {} } },
    {
      name: 'layout',
      selector: { select: { mode: 'dropdown', options: ['tiles', 'rows'].map(value => ({ value, label: L[`layout_${value}`] })) } },
    },
    { name: 'max_items', selector: { number: { min: 1, max: 20, step: 1, mode: 'slider' } } },
    {
      name: 'image_style',
      selector: { select: { mode: 'dropdown', options: ['auto', 'bright', 'muted'].map(value => ({ value, label: L[`image_style_${value}`] })) } },
    },
    { name: 'show_genres', selector: { boolean: {} } },
    { name: 'relative', selector: { boolean: {} } },
    { name: 'open_links', selector: { boolean: {} } },
    { name: 'empty_text', selector: { text: {} } },
  ];
}

const EDITOR_DEFAULTS = { layout: 'tiles', image_style: 'auto', max_items: 8, show_genres: true, relative: true, open_links: false };

class NasHubCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  async _ensureHaForm() {
    if (customElements.get('ha-form')) return;
    // ha-form is lazy-loaded; building a built-in card editor pulls it in
    try {
      const helpers = await window.loadCardHelpers();
      const card = await helpers.createCardElement({ type: 'entities', entities: [] });
      await card.constructor.getConfigElement();
    } catch (e) {
      console.warn('[nas-hub-card] could not load ha-form', e);
    }
  }

  async _render() {
    if (!this._config || !this._hass) return;
    if (!this._form) {
      await this._ensureHaForm();
      if (this._form) return;  // another call finished first
      this._form = document.createElement('ha-form');
      this._form.addEventListener('value-changed', ev => {
        const config = { ...this._config, ...ev.detail.value };
        // Keep the YAML tidy: drop what is empty or at its default
        for (const [key, value] of Object.entries(EDITOR_DEFAULTS)) {
          if (config[key] === value) delete config[key];
        }
        if (!config.title) delete config.title;
        if (!config.empty_text) delete config.empty_text;
        this._config = config;
        this.dispatchEvent(new CustomEvent('config-changed', { detail: { config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const lang = (this._hass.language || navigator.language || 'de').startsWith('de') ? 'de' : 'en';
    const L = EDITOR_LABELS[lang];
    this._form.computeLabel = schema => L[schema.name] || schema.name;
    this._form.hass = this._hass;
    this._form.schema = editorSchema(L);
    this._form.data = { ...EDITOR_DEFAULTS, entities: [], ...this._config };
  }
}

customElements.define('nas-hub-card', NasHubCard);
customElements.define('nas-hub-card-editor', NasHubCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'nas-hub-card',
  name: 'NAS Hub',
  description: 'Neu, Nächste, Läuft gerade, Downloads, Hörbücher und Bücher aus NAS Hub',
  preview: false,
});
