/* DOM/Leaflet presentation only. No GPS generation, route matching or requests. */
(function(root) {
  'use strict';
  const FOLLOW_RESUME_DELAY_MS = 2500;
  const distanceText = meters => Number.isFinite(meters) && meters >= 0 ?
    (meters < 1000 ? `${Math.round(meters).toLocaleString('vi-VN')} m` :
      `${(meters / 1000).toLocaleString('vi-VN', {maximumFractionDigits: 1})} km`) : '—';
  class NavigationUI {
    constructor({map, marker, document = root.document, onStart, onStop, onRepeat, onMute, onTestVoice,
      stationName = '', onArrived = () => {},
      followResumeDelayMs = FOLLOW_RESUME_DELAY_MS,
      setTimer = (fn, ms) => root.setTimeout(fn, ms), clearTimer = id => root.clearTimeout(id)}) {
      Object.assign(this, {map, marker, document, followResumeDelayMs, setTimer, clearTimer});
      this.follow = false; this.lastFix = null; this.active = false; this.destroyed = false;
      this.gestures = new Set(); this.resumeTimer = null; this.cameraUpdate = false;
      const get = id => document.getElementById(id);
      this.starts = [get('btn-start-nav'), get('map-start-nav')].filter(Boolean);
      this.stops = [get('nav-stop'), get('map-stop-nav'), get('nav-stop-fab')].filter(Boolean);
      this.followBox = get('nav-follow-user'); this.recenterButton = get('nav-recenter');
      this.recenterFab = get('nav-recenter-fab'); this.stopFab = get('nav-stop-fab');
      this.layout = document.querySelector('.petro-navigation-layout');
      this.panel = get('map-nav-panel'); this.details = get('map-nav-details');
      this.expandButton = get('nav-panel-toggle'); this.warning = get('map-nav-warning');
      this.arrivalDialog = get('nav-arrival-dialog'); this.arrivalShown = false;
      Object.assign(this, {stationName, onArrived});
      this.listeners = [];
      const listen = (el, event, fn) => {if (el) {el.addEventListener(event, fn); this.listeners.push([el,event,fn]);}};
      this.infoHidden = false; this.resizeTimer = null;
      const hideInfo = get('nav-hide-info'), showInfo = get('nav-show-info');
      const toggleInfo = hidden => {
        this.infoHidden = hidden;
        this.layout?.classList.toggle('petro-info-hidden', hidden);
        [hideInfo, showInfo].filter(Boolean).forEach(button => button.setAttribute('aria-expanded', String(!hidden)));
        (hidden ? showInfo : hideInfo)?.focus?.({preventScroll:true});
        this.resizeMap();
      };
      listen(hideInfo, 'click', () => toggleInfo(true));
      listen(showInfo, 'click', () => toggleInfo(false));
      if (root.addEventListener) listen(root, 'resize', () => this.resizeMap());
      if (root.ResizeObserver && this.layout) {
        this.sizeObserver = new root.ResizeObserver(() => this.resizeMap());
        this.sizeObserver.observe(this.layout);
        const mapElement = map.getContainer?.();
        if (mapElement) this.sizeObserver.observe(mapElement);
      }
      this.starts.forEach(button => listen(button, 'click', onStart));
      this.stops.forEach(button => listen(button, 'click', onStop));
      listen(get('nav-repeat'), 'click', onRepeat);
      // Keep this synchronous all the way to speechSynthesis.speak() on iOS.
      [get('nav-voice-test'), get('map-voice-test')].filter(Boolean).forEach(button => listen(button, 'click', onTestVoice));
      const voiceSwitches = [get('nav-voice-enabled'), get('nav-voice-enabled-map')].filter(Boolean);
      voiceSwitches.forEach(element => listen(element, 'change', event => {
        voiceSwitches.forEach(other => {other.checked = event.target.checked;});
        onMute(!event.target.checked);
      }));
      listen(get('nav-arrival-done'), 'click', () => this.closeArrival());
      listen(this.arrivalDialog, 'close', () => this.restoreArrivalFocus());
      listen(this.arrivalDialog, 'keydown', event => {
        // Native dialog provides focus containment; this also covers older WebViews' open fallback.
        if (event.key === 'Escape') {event.preventDefault(); this.closeArrival();}
        if (event.key === 'Tab') {event.preventDefault(); get('nav-arrival-done')?.focus?.();}
      });
      listen(this.expandButton, 'click', () => this.setExpanded(!this.expanded));
      listen(this.followBox, 'change', () => {
        this.follow = this.followBox.checked; this.cancelResume();
        if (this.follow && !this.gestures.size) this.recenter();
        this.renderCameraStatus();
      });
      const doRecenter = () => {
        this.follow = true; if (this.followBox) this.followBox.checked = true;
        this.cancelResume();
        if (!this.gestures.size) this.recenter({zoom: true});
        this.renderCameraStatus();
      };
      listen(this.recenterButton, 'click', doRecenter);
      listen(this.recenterFab, 'click', doRecenter);
      // Camera gestures pause following; they never change the user's follow preference.
      // No click/tap handler: a map tap cannot turn Follow GPS off.
      this.mapListeners = [];
      for (const gesture of ['drag', 'zoom']) {
        const start = () => {
          if (this.cameraUpdate || this.destroyed) return;
          this.cancelResume(); this.gestures.add(gesture); this.renderCameraStatus();
        };
        const end = () => {
          if (this.cameraUpdate || this.destroyed) return;
          this.gestures.delete(gesture);
          if (!this.gestures.size && this.follow && this.active) {
            this.cancelResume();
            this.resumeTimer = this.setTimer(() => {
              this.resumeTimer = null;
              if (!this.destroyed && this.active && this.follow && !this.gestures.size) this.recenter();
              this.renderCameraStatus();
            }, this.followResumeDelayMs);
          }
          this.renderCameraStatus();
        };
        for (const [event, fn] of [[gesture + 'start', start], [gesture + 'end', end]]) {
          map.on(event, fn); this.mapListeners.push([event, fn]);
        }
      }
      this.setExpanded(true);
    }
    resizeMap() {
      if (this.resizeTimer !== null) this.clearTimer(this.resizeTimer);
      this.resizeTimer = this.setTimer(() => {
        this.resizeTimer = null;
        if (!this.destroyed) this.map.invalidateSize?.({pan:false});
      }, 80);
    }
    openArrival() {
      if (this.arrivalShown) return;
      this.arrivalShown = true; this.onArrived();
      if (!this.arrivalDialog) return;
      const name = this.document.getElementById('nav-arrival-station');
      if (name) name.textContent = this.stationName;
      this.arrivalFocus = this.document.activeElement;
      if (this.arrivalDialog.showModal) this.arrivalDialog.showModal();
      else this.arrivalDialog.setAttribute('open', '');
      this.document.getElementById('nav-arrival-done')?.focus?.({preventScroll: true});
    }
    restoreArrivalFocus() {
      const target = this.arrivalFocus?.isConnected ? this.arrivalFocus : this.expandButton;
      target?.focus?.({preventScroll: true}); this.arrivalFocus = null;
    }
    closeArrival() {
      if (!this.arrivalDialog) return;
      if (this.arrivalDialog.close) this.arrivalDialog.close();
      else {this.arrivalDialog.removeAttribute('open'); this.restoreArrivalFocus();}
      // No Start/Stop, payment, request creation or navigation on dismissal.
    }
    cancelResume() {
      if (this.resumeTimer !== null) this.clearTimer(this.resumeTimer);
      this.resumeTimer = null;
    }
    setExpanded(expanded) {
      this.expanded = expanded;
      if (!expanded && this.details?.contains?.(this.document.activeElement)) {
        this.expandButton?.focus?.({preventScroll: true});
      }
      if (this.details) this.details.hidden = !expanded;
      if (this.panel) this.panel.setAttribute('data-expanded', String(expanded));
      if (this.expandButton) {
        this.expandButton.setAttribute('aria-expanded', String(expanded));
        this.expandButton.setAttribute('aria-label', expanded ? 'Thu gọn điều khiển dẫn đường' : 'Mở rộng điều khiển dẫn đường');
        this.expandButton.textContent = expanded ? 'Thu gọn' : 'Mở rộng';
      }
    }
    renderCameraStatus() {
      if (this.destroyed) return;
      const el = this.document.getElementById('nav-camera-status');
      const status = !this.active ? 'GPS liên tục đã tắt' : !this.follow ? 'Theo GPS: tắt' :
        this.gestures.size || this.resumeTimer !== null ? 'Theo GPS: tạm nhường thao tác bản đồ' : 'Theo GPS: bật';
      if (el && el.textContent !== status) el.textContent = status;
      const hint = this.document.getElementById('nav-follow-hint');
      const help = `Kéo/zoom để xem bản đồ; tự theo lại sau ${this.followResumeDelayMs / 1000} giây nghỉ. Chỉ tắt hẳn khi bỏ chọn Theo GPS.`;
      if (hint && hint.textContent !== help) hint.textContent = help;
    }
    recenter({zoom = false} = {}) {
      if (!this.lastFix || this.destroyed) return;
      // Do not fabricate fixes, snap to geometry or follow when user pans.
      this.cameraUpdate = true;
      try {
        const center = [this.lastFix.latitude, this.lastFix.longitude];
        if (zoom && this.map.setView) this.map.setView(center, Math.max(16, this.map.getZoom()), {animate: false});
        else this.map.panTo(center, {animate: false});
      } finally {this.cameraUpdate = false;}
    }
    renderFix(fix) {
      if (this.destroyed) return;
      this.lastFix = fix;
      this.marker.setLatLng([fix.latitude, fix.longitude]).bindTooltip(
        fix.coarse ? `Vị trí GPS ước lượng ±${Math.round(fix.accuracy)} m` : 'Vị trí GPS thực');
      if (this.recenterButton) this.recenterButton.disabled = false;
      if (this.recenterFab) this.recenterFab.disabled = false;
      this.document.getElementById('start-point-label').textContent = fix.coarse ?
        `GPS ước lượng ±${Math.round(fix.accuracy)} m (chưa dẫn đường)` : 'Vị trí GPS thực';
      if (this.active && this.follow && !fix.coarse && !this.gestures.size && this.resumeTimer === null) this.recenter();
    }
    render(state) {
      if (this.destroyed) return;
      const wasActive = this.active; this.active = state.active;
      // Presentation only: never call start/stop, speech, fetchRoute or watchPosition here.
      if (this.active && !wasActive) {
        this.arrivalShown = false;
        if (this.arrivalDialog?.open) this.closeArrival();
        this.setExpanded(false);
        this.follow = true;
        if (this.followBox) this.followBox.checked = true;
        if (this.lastFix && !this.lastFix.coarse) this.recenter({zoom: true});
      }
      if (!this.active) {this.cancelResume(); this.gestures.clear();}
      this.layout?.classList.toggle('petro-driving', this.active);
      // Leaflet needs a size refresh when the sidebar changes width/height.
      if (this.active !== wasActive) this.setTimer(() => {
        if (!this.destroyed) this.map.invalidateSize?.({pan: false});
      }, 50);
      if (state.phase === 'error' && this.lastPhase !== 'error') this.setExpanded(true);
      this.lastPhase = state.phase;
      const text = (id, value) => {
        const el = this.document.getElementById(id);
        if (el && value !== undefined && el.textContent !== value) el.textContent = value;
      };
      const label = state.phase === 'starting' ? 'Đang khởi động GPS…' :
        state.active && state.phase === 'waiting' ? 'Đang chờ GPS…' :
        state.active && state.routeStatus === 'loading' ? 'Đang tính lại tuyến…' : state.active ? 'Đang dẫn đường' :
        state.phase === 'arrived' ? 'Bắt đầu lại' : 'Bắt đầu đi';
      this.starts.forEach(button => {
        button.disabled = state.active;
        button.textContent = label;
        button.setAttribute('aria-busy', String(state.active && state.phase === 'starting'));
      });
      this.stops.forEach(button => {button.disabled = !state.active && !state.speaking && !state.speechDiagnostics?.requested;});
      const repeat = this.document.getElementById('nav-repeat'); if (repeat) repeat.disabled = !state.active || !state.guidanceValid;
      text('nav-gps-status', state.gpsStatus); text('map-nav-status', state.gpsStatus);
      text('map-nav-state', state.phase === 'error' ? 'Dẫn đường đã dừng — có thể thử lại' :
        state.phase === 'arrived' ? 'Đã đến nơi' : this.active ? 'Đang dẫn đường' : label);
      if (this.panel) this.panel.setAttribute('data-active', String(this.active));
      if (this.panel) this.panel.setAttribute('data-phase', state.phase);
      text('map-nav-icon', state.phase === 'arrived' ? 'flag' : 'navigation');
      const healthy = this.active && state.gpsQuality === 'valid';
      text('map-nav-short-status', healthy && this.lastFix ? `GPS đang bật · ±${Math.round(this.lastFix.accuracy)} m` :
        this.active ? 'GPS đang bật · chờ vị trí hợp lệ' : 'GPS liên tục đã tắt');
      // Full permission/accuracy/stale/route errors stay OUTSIDE collapsible details.
      if (this.warning) {
        this.warning.hidden = !(state.phase === 'error' || (this.active && (!healthy || state.phase === 'waiting' || state.routeStatus !== 'ready')));
        text('map-nav-warning', state.gpsStatus || 'Đang chờ vị trí GPS hợp lệ.');
      }
      text('nav-voice-status', state.voiceStatus);
      const navReady = this.active && state.phase === 'navigating' && state.routeStatus === 'ready' &&
        state.gpsQuality === 'valid' && state.guidanceValid === true;
      const m = state.maneuver || {};
      const modifier = typeof m.modifier === 'string' ? m.modifier : '';
      const icon = state.atDeparture ? 'straight' : m.type === 'arrive' ? 'flag' :
        ['roundabout','rotary'].includes(m.type) ?
          modifier.includes('right') ? 'roundabout_right' : modifier.includes('left') ? 'roundabout_left' : 'route' :
        modifier === 'uturn' ? 'u_turn_left' :
        modifier.includes('right') ? 'turn_right' : modifier.includes('left') ? 'turn_left' :
        modifier === 'straight' || ['depart','continue','new name'].includes(m.type) ? 'straight' : 'navigation';
      text('nav-turn-icon', navReady ? icon : 'navigation');
      const inactiveInstruction = state.phase === 'error' ? 'Dẫn đường đã dừng. Kiểm tra cảnh báo GPS hoặc thử lại.' :
        this.active ? state.routeStatus === 'loading' ? 'Đang lấy tuyến đường từ GPS hiện tại…' :
          'Chờ vị trí hợp lệ trên tuyến để cập nhật chỉ dẫn' : state.phase === 'stopped' ?
          'Dẫn đường đã dừng. Bấm Bắt đầu đi để thử lại.' : 'Bấm Bắt đầu đi để bật hướng dẫn';
      text('nav-turn-distance', navReady ? distanceText(state.distance) :
        this.active ? state.routeStatus === 'loading' ? 'Đang tính tuyến…' : 'Đang chờ GPS chính xác' : 'Xem trước lộ trình');
      text('nav-turn-instruction', navReady ? state.instruction : inactiveInstruction);
      text('nav-next-step', navReady ? state.instruction : inactiveInstruction);
      const roads = [];
      if (navReady) {
        if (state.currentRoad) roads.push(`Đang đi: ${state.currentRoad}`);
        if (state.nextRoad && state.nextRoad !== state.currentRoad) roads.push(`Sắp vào: ${state.nextRoad}`);
        if (Number.isFinite(state.bearing)) roads.push('Hướng: ' +
          ['Bắc','Đông Bắc','Đông','Đông Nam','Nam','Tây Nam','Tây','Tây Bắc'][Math.round(state.bearing / 45) % 8]);
      }
      text('nav-turn-road', roads.join(' • ')); text('nav-road-name', roads.join(' • '));
      text('nav-turn-following', navReady ? state.followingInstruction || '' : '');
      if (navReady) {
        const eta = Number.isFinite(state.remainingDuration) ? root.PetroTravelFormat?.duration(state.remainingDuration / 60) : null;
        const remaining = `Còn ${distanceText(state.remainingDistance)}` + (eta ? ` • ${eta}` : '');
        text('overlay-dist-head', remaining); text('map-nav-route-summary', remaining);
      } else if (state.phase !== 'idle') {
        text('overlay-dist-head', 'Chưa có tiến độ GPS hợp lệ trên tuyến');
        text('map-nav-route-summary', 'Chưa có tiến độ GPS hợp lệ trên tuyến');
      }
      text('map-voice-status', state.voiceStatus);
      const diagnostics = state.speechDiagnostics;
      if (diagnostics) {
        text('nav-voice-diagnostics', `Giọng: ${diagnostics.voiceName || 'chưa có'} (${diagnostics.voiceLang || '—'}); ` +
          `số giọng: ${diagnostics.voiceCount}; trạng thái: ${state.voicePhase}; ` +
          `requested=${diagnostics.requested}, started=${diagnostics.started}, pending=${diagnostics.pending}, ` +
          `speaking=${diagnostics.speaking}, paused=${diagnostics.paused}; lỗi: ${diagnostics.error || 'không'}. ` +
          'Sự kiện trình duyệt không xác minh được âm thanh có nghe thấy trên loa hay không.');
        for (const id of ['nav-voice-test', 'map-voice-test']) {
          const button = this.document.getElementById(id);
          if (button) {button.disabled = diagnostics.requested; button.setAttribute('aria-busy', String(diagnostics.requested));}
        }
      }
      if (navReady && Number.isFinite(state.distance) && state.distance >= 0) {
        text('nav-distance', `Còn ${Math.round(state.distance).toLocaleString('vi-VN')} m đến thao tác tiếp theo`);
      } else text('nav-distance', 'Chưa có khoảng cách đến thao tác tiếp theo');
      if (state.phase === 'arrived') {
        text('nav-turn-icon', 'flag'); text('nav-turn-distance', 'Đã đến nơi');
        text('nav-turn-instruction', 'Bạn đã đến trạm xăng!'); text('nav-turn-road', ''); text('nav-turn-following', '');
        text('map-nav-route-summary', 'Đã hoàn tất lộ trình dẫn đường');
        text('nav-distance', 'Đã hoàn tất dẫn đường.'); text('nav-road-name', '');
        text('nav-next-step', 'Bạn đã đến trạm xăng!'); text('overlay-dist-head', 'Đã đến nơi · Đã hoàn tất lộ trình dẫn đường');
        if (!this.arrivalShown) this.setExpanded(false);
        this.openArrival();
      }
      this.renderCameraStatus();
    }
    destroy() {
      this.destroyed = true; this.cancelResume(); this.gestures.clear();
      this.sizeObserver?.disconnect();
      if (this.resizeTimer !== null) this.clearTimer(this.resizeTimer);
      if (this.arrivalDialog?.open) this.closeArrival();
      this.listeners.forEach(([el,event,fn]) => el.removeEventListener(event,fn));
      this.mapListeners.forEach(([event,fn]) => this.map.off(event,fn));
    }
  }
  root.PetroNavigationUI = {NavigationUI, FOLLOW_RESUME_DELAY_MS};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PetroNavigationUI;
})(typeof window !== 'undefined' ? window : globalThis);
