/* Leaflet basemaps only: never fetch stations/routes or alter GPS/voice state.
 * OSM France is for this public, non-commercial, low-volume research demo only:
 * https://www.openstreetmap.fr/usage/ . No SLA; review hosting before production.
 * Esri legacy/undocumented Google tiles are deliberately not used. Licensed
 * Esri services require a configured access token and full provider attribution.
 */
(function (root) {
  'use strict';
  const PROVIDERS = Object.freeze({
    hot: {
      name: 'OSM France / HOT',
      url: 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> / ODbL · Tiles: <a href="https://www.hotosm.org/">HOT</a>, hosted by <a href="https://www.openstreetmap.fr/">OSM France</a> · <a href="https://creativecommons.org/licenses/by-sa/2.0/">CC BY-SA</a>'
    },
    osm: {
      name: 'OpenStreetMap Standard',
      // OSMF asks clients to use this exact hostname, not legacy {s} aliases.
      url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    }
  });
  const instances = new WeakMap();
  let controlSequence = 0;
  const ERROR_THRESHOLD = 3, STALL_MS = 12000, RETRY_DELAY_MS = 5000, MAX_RETRIES = 2;

  function attach(map, options = {}) {
    if (instances.has(map)) return instances.get(map);
    const leaflet = options.leaflet || root.L;
    const win = options.window || root;
    const doc = options.document || root.document;
    const layers = {}, handlers = {}, diagnostics = [];
    let current = null, status, retry, control, observer, frame, stall, noticeTimer;
    let container, toggle, popover, notification, notificationRetry;
    const choices = {};
    const debug = options.debug === true;
    let opened = false, tileFailure = false;
    let destroyed = false, errors = 0, loaded = 0, started = 0, retries = 0, lastRetry = -Infinity;
    let warned = false;
    const record = (event, extra = {}) => {
      // Bounded, in-memory diagnostics: no GPS, cookies or tile query strings.
      diagnostics.push({event, provider: current, at: new Date().toISOString(), ...extra});
      if (diagnostics.length > 50) diagnostics.shift();
    };
    const notify = (message, show = false) => {
      if (status) {status.textContent = message; status.hidden = !debug && !tileFailure;}
      if (notification) {
        notification.hidden = !show || opened;
        notification.firstChild.textContent = message;
        clearTimeout(noticeTimer);
        if (show) noticeTimer = setTimeout(() => {notification.hidden = true;}, 8000);
      }
      if (options.onNotice) options.onNotice(message);
    };
    function updateChoices() {
      for (const [id, button] of Object.entries(choices)) {
        button.setAttribute('aria-pressed', String(id === current));
        button.lastChild.textContent = id === current ? '✓' : '';
      }
      if (toggle) toggle.title = 'Nền bản đồ: ' + PROVIDERS[current].name;
      if (retry) retry.hidden = !tileFailure;
      if (notificationRetry) notificationRetry.hidden = !tileFailure;
    }
    function closePopover(restoreFocus = false) {
      opened = false;
      if (popover) popover.hidden = true;
      if (toggle) {toggle.setAttribute('aria-expanded', 'false'); if (restoreFocus) toggle.focus({preventScroll: true});}
    }
    function togglePopover() {
      if (!popover || destroyed) return;
      if (opened) return closePopover(true);
      opened = true; popover.hidden = false;
      if (notification) notification.hidden = true;
      toggle.setAttribute('aria-expanded', 'true');
      choices[current]?.focus({preventScroll: true});
    }
    const outside = event => {
      if (!opened || container.contains(event.target)) return;
      closePopover();
      // A dismiss tap on the map must not also select a simulated GPS location.
      if (map.getContainer().contains(event.target)) event.stopPropagation();
    };
    const escape = event => {
      if (event.key === 'Escape' && opened) {event.preventDefault(); event.stopPropagation(); closePopover(true);}
    };
    function fail(message) {
      if (warned) return;
      warned = true; tileFailure = true; updateChoices();
      notify(message + ' Đổi nền hoặc thử lại.', !opened);
      console.warn('[Petro basemap]', {provider: current, started, loaded, errors,
        online: win.navigator?.onLine, note: 'Tile image events do not expose HTTP status; inspect Network on the affected device.'});
    }
    function armStall() {
      clearTimeout(stall);
      stall = setTimeout(() => {
        if (!destroyed && !loaded && started) fail('Chưa tải được ảnh nền bản đồ.');
      }, STALL_MS);
    }
    function switchTo(id) {
      if (destroyed || !PROVIDERS[id] || id === current) return false;
      if (current) map.removeLayer(layers[current]);
      current = id; errors = loaded = started = retries = 0; warned = false; lastRetry = -Infinity;
      tileFailure = false; updateChoices(); closePopover();
      notify('Đang tải nền ' + PROVIDERS[id].name + '…');
      record('switch');
      layers[id].addTo(map);
      armStall();
      return true;
    }
    function retryCurrent() {
      if (destroyed || !tileFailure || win.navigator?.onLine === false) return false;
      if (retries >= MAX_RETRIES || Date.now() - lastRetry < RETRY_DELAY_MS) {
        notify('Đã giới hạn thử lại. Vui lòng chọn nền khác hoặc kiểm tra kết nối.', true);
        return false;
      }
      lastRetry = Date.now(); retries++; errors = loaded = started = 0; warned = false;
      record('retry'); notify('Đang thử tải lại nền…'); layers[current].redraw(); armStall();
      return true;
    }
    function scheduleSize() {
      if (destroyed || frame) return;
      frame = win.requestAnimationFrame(() => {
        frame = null;
        const bounds = map.getContainer().getBoundingClientRect();
        if (!destroyed && bounds.width > 0 && bounds.height > 0) {
          map.invalidateSize({pan: false, debounceMoveend: true});
          record('resize');
        }
      });
    }
    const offline = () => {record('offline'); notify('Thiết bị đang ngoại tuyến; ảnh nền có thể thiếu.', true);};
    const online = () => {record('online'); notify('Đã có kết nối. Đổi nền hoặc thử lại nếu ảnh nền còn thiếu.', tileFailure);};
    function destroy() {
      if (destroyed) return;
      destroyed = true; clearTimeout(stall); clearTimeout(noticeTimer);
      if (frame) win.cancelAnimationFrame(frame);
      observer?.disconnect();
      for (const event of ['resize', 'orientationchange', 'pageshow']) win.removeEventListener(event, scheduleSize);
      win.visualViewport?.removeEventListener('resize', scheduleSize);
      win.removeEventListener('offline', offline); win.removeEventListener('online', online);
      doc.removeEventListener('click', outside, true); doc.removeEventListener('keydown', escape, true);
      map.off('unload', destroy);
      for (const id of Object.keys(layers)) {
        layers[id].off(handlers[id]);
        if (map.hasLayer(layers[id])) map.removeLayer(layers[id]);
      }
      if (control) control.remove();
      instances.delete(map);
    }
    for (const [id, provider] of Object.entries(PROVIDERS)) {
      layers[id] = leaflet.tileLayer(provider.url, {
        maxZoom: 19, minZoom: 1, attribution: provider.attribution,
        // Send origin only, not user location/filter query parameters in Referer.
        referrerPolicy: 'strict-origin-when-cross-origin',
        updateWhenIdle: true, keepBuffer: 1, detectRetina: false
      });
      handlers[id] = {
        tileloadstart: () => {
          if (id !== current) return;
          started++; record('tileloadstart');
        },
        tileload: () => {
          if (id !== current) return;
          loaded++; record('tileload'); clearTimeout(stall);
          if (!errors) {tileFailure = false; updateChoices();}
          if (!warned) notify('Nền: ' + provider.name);
        },
        tileerror: () => {
          if (id !== current) return;
          errors++; record('tileerror');
          if (errors >= ERROR_THRESHOLD) fail('Một số ảnh nền không tải được.');
        }
      };
      layers[id].on(handlers[id]);
    }
    if (!map.attributionControl) map.attributionControl = leaflet.control.attribution({position: 'bottomright'}).addTo(map);
    if (options.control !== false) {
      control = leaflet.control({position: options.position || 'bottomleft'});
      control.onAdd = () => {
        container = doc.createElement('div'); container.className = 'petro-basemap-control';
        toggle = doc.createElement('button'); toggle.type = 'button'; toggle.className = 'petro-basemap-toggle';
        toggle.setAttribute('aria-label', 'Chọn nền bản đồ'); toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-haspopup', 'dialog');
        const icon = doc.createElement('span'); icon.className = 'material-symbols-outlined';
        icon.setAttribute('aria-hidden', 'true'); icon.textContent = 'layers'; toggle.append(icon);
        popover = doc.createElement('div'); popover.id = 'petro-basemap-popover-' + (++controlSequence);
        popover.className = 'petro-basemap-popover'; popover.hidden = true;
        popover.setAttribute('role', 'dialog'); popover.setAttribute('aria-label', 'Nền bản đồ');
        toggle.setAttribute('aria-controls', popover.id); toggle.addEventListener('click', togglePopover);
        const heading = doc.createElement('p'); heading.textContent = 'Nền bản đồ'; heading.className = 'petro-basemap-heading';
        popover.append(heading);
        for (const [id, provider] of Object.entries(PROVIDERS)) {
          const choice = doc.createElement('button'); choice.type = 'button'; choice.className = 'petro-basemap-choice';
          const name = doc.createElement('span'); name.textContent = provider.name;
          const check = doc.createElement('span'); check.setAttribute('aria-hidden', 'true');
          choice.append(name, check); choice.setAttribute('aria-pressed', 'false');
          choice.addEventListener('click', () => {switchTo(id); closePopover(true);});
          choices[id] = choice; popover.append(choice);
        }
        status = doc.createElement('p'); status.className = 'petro-basemap-debug'; status.hidden = !debug;
        retry = doc.createElement('button'); retry.type = 'button'; retry.textContent = 'Thử lại nền';
        retry.hidden = true;
        retry.addEventListener('click', retryCurrent);
        popover.append(status, retry);
        notification = doc.createElement('div'); notification.className = 'petro-basemap-notice'; notification.hidden = true;
        notification.setAttribute('role', 'status'); notification.setAttribute('aria-live', 'polite');
        notification.append(doc.createElement('span'));
        notificationRetry = doc.createElement('button'); notificationRetry.type = 'button'; notificationRetry.textContent = 'Thử lại nền';
        notificationRetry.hidden = true; notificationRetry.addEventListener('click', retryCurrent);
        notification.append(notificationRetry);
        container.append(toggle, popover, notification);
        doc.addEventListener('click', outside, true); doc.addEventListener('keydown', escape, true);
        leaflet.DomEvent.disableClickPropagation(container);
        leaflet.DomEvent.disableScrollPropagation(container);
        return container;
      };
      control.addTo(map);
    }
    const api = {
      switchTo, retry: retryCurrent, destroy, invalidateSize: scheduleSize, togglePopover,
      cycle: () => switchTo(current === 'hot' ? 'osm' : 'hot'),
      get current() {return current;},
      getDiagnostics: () => ({provider: current, started, loaded, errors, retries,
        online: win.navigator?.onLine, events: diagnostics.slice()})
    };
    instances.set(map, api);
    if (win.ResizeObserver) {observer = new win.ResizeObserver(scheduleSize); observer.observe(map.getContainer());}
    for (const event of ['resize', 'orientationchange', 'pageshow']) win.addEventListener(event, scheduleSize);
    win.visualViewport?.addEventListener('resize', scheduleSize);
    win.addEventListener('offline', offline); win.addEventListener('online', online);
    map.on('unload', destroy);
    switchTo(options.defaultProvider === 'osm' ? 'osm' : 'hot');
    scheduleSize();
    return api;
  }
  root.PetroBasemaps = {attach, PROVIDERS};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PetroBasemaps;
})(typeof window !== 'undefined' ? window : globalThis);
