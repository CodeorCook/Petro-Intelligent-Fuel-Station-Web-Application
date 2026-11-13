/* Experimental navigation. OSRM geometry/maneuvers only; no synthetic GPS or turns. */
(function (root) {
  'use strict';
  const CONFIG = Object.freeze({maxAccuracy: 50, maxDisplayAccuracy: 1000, maxFixAge: 15000, earlyMeters: 300,
    nearMeters: 80, offRouteMeters: 45, offRouteDebounce: 8000, rerouteCooldown: 30000,
    eligibilityInterval: 30000, arrivalMeters: 20, requestTimeout: 15000, gpsSilence: 20000,
    arrivalConfirmFixes: 3, arrivalConfirmMs: 3000, arrivalMaxGap: 10000,
    arrivalMaxAccuracy: 15, arrivalMaxSpeed: 2.5, speechStartTimeout: 5000, speechEndTimeout: 30000});
  const radians = n => n * Math.PI / 180;
  function meters(a, b) {
    const dlat = radians(b[1] - a[1]), dlon = radians(b[0] - a[0]);
    const h = Math.sin(dlat / 2) ** 2 + Math.cos(radians(a[1])) * Math.cos(radians(b[1])) * Math.sin(dlon / 2) ** 2;
    return 6371008.8 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
  }
  function instruction(step, distance = null) {
    const m = step.maneuver || {}, type = m.type, modifier = typeof m.modifier === 'string' ? m.modifier : '';
    const road = step.road_name ? ` vào ${step.road_name}` : '';
    const lead = Number.isFinite(distance) && distance > 20 ? `Còn ${Math.round(distance).toLocaleString('vi-VN')} m, ` : '';
    let text;
    if (type === 'arrive') return Number.isFinite(distance) ?
      distance > 0 ? `Còn ${Math.round(distance)} m đến trạm xăng.` : 'Đang xác nhận vị trí tại điểm cuối tuyến.' : 'Bạn đã đến trạm xăng.';
    if (type === 'roundabout' || type === 'rotary') {
      text = 'tại vòng xuyến' + (Number.isInteger(m.exit) && m.exit > 0 ? `, đi theo lối ra thứ ${m.exit}` : ', đi theo lộ trình');
    } else if (type === 'exit roundabout' || type === 'exit rotary') text = 'ra khỏi vòng xuyến' + road;
    else if (modifier === 'uturn' || type === 'uturn') text = 'quay đầu khi được phép';
    else if (type === 'merge') text = 'nhập làn theo lộ trình' + road;
    else if (type === 'fork') text = 'tại ngã rẽ, ' + (modifier.includes('left') ? 'đi bên trái' :
      modifier.includes('right') ? 'đi bên phải' : modifier === 'straight' ? 'đi thẳng' : 'đi theo lộ trình') + road;
    else if (modifier.includes('right')) text = 'rẽ phải' + road;
    else if (modifier.includes('left')) text = 'rẽ trái' + road;
    else if (['depart', 'continue', 'new name'].includes(type) || modifier === 'straight')
      text = 'tiếp tục đi thẳng' + (step.road_name ? ` trên ${step.road_name}` : ' theo tuyến đường');
    else text = 'theo dõi lộ trình trên bản đồ';
    return lead + (lead ? text : text.charAt(0).toUpperCase() + text.slice(1)) + '.';
  }

  const emptyGuidance = () => ({instruction: null, distance: null, maneuver: null, roadName: '',
    currentRoad: '', nextRoad: '', bearing: null, remainingDistance: null, remainingDuration: null,
    maneuverIndex: null, maneuverKey: null, guidanceValid: false, atDeparture: false, followingInstruction: ''});
  const guidanceFields = Object.keys(emptyGuidance());
  function guidanceAt(route, progress, next, destinationName = '') {
    const upcoming = route.maneuvers[next], distance = Math.max(0, upcoming.offset - progress);
    let current = 0;
    // The arrive step has no onward road; its bearing_after=0 is not a heading.
    while (current + 1 < route.maneuvers.length - 1 && route.maneuvers[current + 1].offset <= progress) current++;
    const currentStep = route.maneuvers[current].step, nextStep = upcoming.step;
    const bearing = currentStep.maneuver.bearing_after;
    const atDeparture = progress === 0 && currentStep.maneuver.type === 'depart' &&
      currentStep.maneuver.modifier === 'straight' && nextStep.maneuver.type !== 'arrive' && distance > 0;
    let text = instruction(nextStep, distance);
    if (atDeparture) text = `Đi thẳng ${Math.round(distance)} m` +
      (nextStep.road_name ? ` về phía ${nextStep.road_name}.` : ' theo tuyến đường.');
    if (nextStep.maneuver.type === 'arrive' && distance > 0 && destinationName)
      text = `Còn ${Math.round(distance)} m đến ${destinationName}.`;
    const side = nextStep.maneuver.type === 'arrive' && ['right','left'].includes(nextStep.maneuver.modifier) ?
      `Điểm đến ở bên ${nextStep.maneuver.modifier === 'right' ? 'phải' : 'trái'} theo OSRM.` : '';
    let seconds = 0;
    for (let i = current; i < route.maneuvers.length - 1; i++) {
      const start = route.maneuvers[i].offset, end = route.maneuvers[i + 1].offset;
      const duration = route.maneuvers[i].step.duration_seconds;
      if (!Number.isFinite(duration) || duration < 0) {seconds = null; break;}
      if (end > start) seconds += duration * Math.max(0, end - Math.max(progress, start)) / (end - start);
    }
    return {instruction: text, distance, maneuver: {...nextStep.maneuver},
      roadName: nextStep.road_name || '', currentRoad: currentStep.road_name || '',
      nextRoad: nextStep.maneuver.type === 'arrive' ? '' : nextStep.road_name || '',
      bearing: Number.isFinite(bearing) && bearing >= 0 && bearing < 360 ? bearing : null,
      remainingDistance: Math.max(0, route.total - progress), remainingDuration: seconds,
      maneuverIndex: next, guidanceValid: true, atDeparture,
      followingInstruction: atDeparture ? `Tiếp theo: ${instruction(nextStep)}` : side};
  }

  function prepareRoute(route) {
    if (route.is_fallback || route.routing_source !== 'osrm' || !Array.isArray(route.steps) || route.steps.length < 2)
      throw new Error('Lộ trình chỉ là bản xem trước; chưa có maneuver OSRM để dẫn đường.');
    const points = [], cumulative = [], maneuvers = [];
    let total = 0;
    for (const step of route.steps) {
      const coords = step.geometry?.coordinates;
      if (!Array.isArray(coords) || !coords.length || !step.maneuver?.location || !step.maneuver.type)
        throw new Error('Dữ liệu hướng dẫn OSRM không đầy đủ.');
      // Concatenated verified step geometries preserve maneuver ordering at loops.
      if (points.length && meters(points[points.length - 1], coords[0]) > 30)
        throw new Error('Geometry các bước OSRM không liên tục.');
      const start = total + (points.length ? meters(points[points.length - 1], coords[0]) : 0);
      maneuvers.push({step, offset: start});
      for (const coord of coords) {
        if (!Array.isArray(coord) || coord.length < 2 || !coord.every(Number.isFinite) || Math.abs(coord[1]) > 90 || Math.abs(coord[0]) > 180)
          throw new Error('Tọa độ OSRM không hợp lệ.');
        if (points.length) total += meters(points[points.length - 1], coord);
        points.push(coord); cumulative.push(total);
      }
    }
    if (total <= 0 || maneuvers[maneuvers.length - 1].step.maneuver.type !== 'arrive')
      throw new Error('Lộ trình OSRM chưa có điểm đến xác nhận.');
    return {points, cumulative, maneuvers, total};
  }

  function projectFix(position, route, progress = 0, advance = 250) {
    const point = [position.longitude, position.latitude];
    let best = null;
    const scaleX = 111195 * Math.cos(radians(position.latitude)), scaleY = 111195;
    for (let i = 1; i < route.points.length; i++) {
      if (route.cumulative[i] < progress - 30 || route.cumulative[i - 1] > progress + advance) continue;
      const a = route.points[i - 1], b = route.points[i];
      const ax = (a[0] - point[0]) * scaleX, ay = (a[1] - point[1]) * scaleY;
      const dx = (b[0] - a[0]) * scaleX, dy = (b[1] - a[1]) * scaleY;
      const length2 = dx * dx + dy * dy;
      const t = length2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / length2)) : 0;
      const distance = Math.hypot(ax + t * dx, ay + t * dy);
      const along = route.cumulative[i - 1] + t * (route.cumulative[i] - route.cumulative[i - 1]);
      if (along > progress + advance || along < progress - 30) continue;
      if (!best || distance < best.distance) best = {distance, along};
    }
    return best;
  }

  function validateGpsPosition(position, now = Date.now(), config = CONFIG) {
    const fix = position?.coords;
    if (!fix || !Number.isFinite(fix.latitude) || !Number.isFinite(fix.longitude) ||
        Math.abs(fix.latitude) > 90 || Math.abs(fix.longitude) > 180)
      return {reason: 'Tọa độ GPS không hợp lệ.'};
    if (!Number.isFinite(position.timestamp) || now - position.timestamp > config.maxFixAge || position.timestamp > now + 2000)
      return {reason: 'Tín hiệu GPS đã cũ hoặc thời gian không hợp lệ; đang chờ vị trí mới.'};
    if (!Number.isFinite(fix.accuracy) || fix.accuracy < 0)
      return {reason: 'Trình duyệt chưa cung cấp độ chính xác GPS.'};
    if (fix.accuracy > config.maxAccuracy)
      return {reason: 'GPS ±' + Math.round(fix.accuracy) + ' m; cần sai số không quá ' + config.maxAccuracy +
        ' m để hướng dẫn rẽ. Thử bật Vị trí chính xác, ra ngoài trời hoặc dùng điện thoại.',
        coarseFix: fix.accuracy <= config.maxDisplayAccuracy ?
          {latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy, coarse: true} : null};
    return {fix: {latitude: fix.latitude, longitude: fix.longitude, accuracy: fix.accuracy,
      heading: Number.isFinite(fix.heading) && fix.heading >= 0 && fix.heading < 360 ? fix.heading : null,
      speed: Number.isFinite(fix.speed) && fix.speed >= 0 ? fix.speed : null}};
  }

  class VoiceNavigation {
    constructor({fetchRoute, checkEligibility, onUpdate = () => {}, onRoute = () => {},
      geolocation = root.navigator?.geolocation, synth = root.speechSynthesis,
      Utterance = root.SpeechSynthesisUtterance, secure = root.isSecureContext,
      now = () => Date.now(), onFix = () => {}, config = {}, destinationName = '',
      // Browser timer methods must retain their Window receiver (WebViews can
      // throw Illegal invocation if a native timer is called as this.setTimer).
      setTimer = (fn, delay) => root.setTimeout(fn, delay), clearTimer = id => root.clearTimeout(id)}) {
      Object.assign(this, {fetchRoute, checkEligibility, onUpdate, onRoute, onFix, geolocation, synth, Utterance, secure, now, setTimer, clearTimer, destinationName});
      this.config = {...CONFIG, ...config}; this.active = false; this.muted = false;
      this.epoch = 0; this.watchId = null; this.speaking = false;
      this.requestTimers = new Set(); this.arrivalCandidate = null;
      this.voicePhase = 'idle'; this.voiceStatus = ''; this.audioInitialized = false;
      this.phase = 'idle'; this.routeStatus = 'idle'; this.gpsQuality = 'waiting';
      this.gpsStatus = 'Chưa bắt đầu theo dõi GPS.';
      this.guidance = emptyGuidance(); this.routeRevision = 0;
      this.voiceListener = () => this.loadVoices();
      this.synth?.addEventListener?.('voiceschanged', this.voiceListener);
      this.loadVoices();
    }
    clearGuidance() {
      this.guidance = emptyGuidance(); this.currentInstruction = null; this.queuedSpeech = null;
      if (this.utteranceManeuverKey) this.cancelSpeech();
    }
    update(values = {}) {
      for (const key of ['phase', 'gpsStatus', 'routeStatus', 'gpsQuality']) if (values[key] !== undefined) this[key] = values[key];
      for (const key of guidanceFields) if (values[key] !== undefined) this.guidance[key] = values[key];
      if (this.phase !== 'arrived' && (!this.active || this.routeStatus !== 'ready' ||
          this.gpsQuality !== 'valid' || this.phase !== 'navigating')) this.clearGuidance();
      this.currentInstruction = this.guidance.instruction;
      this.onUpdate({...values, ...this.guidance, maneuver: this.guidance.maneuver ? {...this.guidance.maneuver} : null,
        active: this.active, muted: this.muted, speaking: this.speaking,
        phase: this.phase, gpsStatus: this.gpsStatus, routeStatus: this.routeStatus,
        gpsQuality: this.gpsQuality, rerouting: this.routeStatus === 'loading',
        voicePhase: this.voicePhase, voiceStatus: this.voiceStatus, speechDiagnostics: this.speechDiagnostics()});
    }
    publishGuidance(values = {}) {
      const next = guidanceAt(this.route, this.progress, this.next, this.destinationName);
      next.maneuverKey = `${this.epoch}:${this.routeRevision}:${this.next}`;
      if (this.guidance.maneuverKey !== next.maneuverKey) {
        this.queuedSpeech = null;
        if (this.utteranceManeuverKey) this.cancelSpeech();
      }
      this.update({...values, ...next});
    }
    waitForGps() {
      this.clearTimer(this.gpsTimer);
      const epoch = this.epoch;
      this.gpsTimer = this.setTimer(() => {
        if (this.active && epoch === this.epoch) {
          this.arrivalCandidate = null;
          this.update({phase: 'waiting', gpsQuality: 'stale',
            gpsStatus: 'Chưa có vị trí GPS hợp lệ mới; marker giữ vị trí cuối. Có thể dừng rồi thử lại.'});
        }
      }, this.config.gpsSilence);
    }
    loadVoices() {
      this.voices = [];
      if (!this.synth || typeof this.synth.speak !== 'function' || !this.Utterance) {
        this.voice = null; this.voiceUpdate('unsupported', 'Trình duyệt không hỗ trợ giọng nói; xem hướng dẫn trên màn hình.'); return;
      }
      try {this.voices = this.synth.getVoices?.() || [];}
      catch (error) {this.voice = null; this.voiceUpdate('error', 'Không thể đọc danh sách giọng nói. Thử lại trong Safari.', error.name); return;}
      this.voice = this.voices.find(v => /^vi(?:[-_]|$)/i.test(v.lang)) || null;
      if (!this.voice) {
        this.audioInitialized = false;
        this.voiceUpdate('unavailable', 'Chưa có giọng tiếng Việt. Kiểm tra giọng nói trên iPhone hoặc mở trực tiếp trong Safari; hướng dẫn hình ảnh vẫn hoạt động.');
      } else if (['idle', 'unavailable', 'unsupported', 'muted', 'cancelled'].includes(this.voicePhase)) {
        this.voiceUpdate('ready', 'Đã tìm thấy giọng tiếng Việt. Bấm “Thử giọng tiếng Việt” để kiểm tra âm thanh.');
      } else this.update({}); // voiceschanged must not erase a playback error or replay audio.
    }
    speechDiagnostics() {
      return {supported: !!(this.synth && typeof this.synth.speak === 'function' && this.Utterance),
        voiceCount: this.voices?.length || 0, voiceName: this.voice?.name || null, voiceLang: this.voice?.lang || null,
        initialized: this.audioInitialized, requested: !!this.utterance, started: this.speaking,
        pending: !!this.synth?.pending, speaking: !!this.synth?.speaking, paused: !!this.synth?.paused,
        error: this.voiceError || null};
    }
    voiceUpdate(phase, message, error = null) {
      this.voicePhase = phase; this.voiceStatus = message; this.voiceError = error;
      this.update({});
    }
    cancelSpeech() {
      const owned = this.utterance;
      this.utterance = null; this.queuedSpeech = null; this.speaking = false;
      this.utteranceManeuverKey = null;
      this.clearTimer(this.speechTimer); this.speechTimer = null;
      if (owned) {
        this.voicePhase = 'cancelled'; this.voiceStatus = 'Đã dừng câu đọc.';
        try {this.synth?.cancel?.();}
        catch (error) {this.voiceError = error.name; this.voicePhase = 'error'; this.voiceStatus = 'Trình duyệt không thể hủy câu đọc; thử lại trong Safari.';}
      }
    }
    testVoice() {
      // Called directly by a click, with no await/timer/network before speak().
      // iOS may require a real gesture; an application boolean is not activation.
      this.interacted = true; this.loadVoices();
      return this.speak('Petro xin chào. Đây là hướng dẫn bằng tiếng Việt.', {direct: true});
    }
    speak(text, {direct = false, terminal = false, maneuverKey = null} = {}) {
      if (maneuverKey && (!this.guidance.guidanceValid || maneuverKey !== this.guidance.maneuverKey)) return false;
      if (this.muted) {this.voiceUpdate('muted', 'Giọng nói đang tắt. Bật giọng tiếng Việt rồi thử lại.'); return false;}
      if (!this.voice || !this.Utterance || !this.synth || !this.interacted) return false;
      if (!direct && ((!this.active && !(terminal && this.arrived)) || !this.audioInitialized)) return false;
      if (this.utterance) {
        // One current utterance and at most one latest announcement; no cancel/speak race per GPS fix.
        if (!direct && text !== this.utterance.text) {this.queuedSpeech = {text, terminal, maneuverKey}; return true;}
        return false;
      }
      let utterance;
      try {utterance = new this.Utterance(text);}
      catch (error) {this.voiceUpdate('error', 'Không thể khởi tạo giọng nói; thử lại trong Safari.', error.name); return false;}
      utterance.lang = 'vi-VN'; utterance.voice = this.voice;
      utterance.volume = 1; utterance.rate = 1; utterance.pitch = 1;
      // Keep a strong reference until a terminal event or bounded timeout.
      this.utterance = utterance; this.utteranceManeuverKey = maneuverKey; let started = false;
      const fail = (phase, message, error) => {
        if (this.utterance !== utterance) return;
        this.cancelSpeech(); this.audioInitialized = false; this.voiceUpdate(phase, message, error);
      };
      utterance.onstart = () => {
        if (this.utterance !== utterance) return;
        started = true; this.speaking = true; this.audioInitialized = true;
        this.clearTimer(this.speechTimer);
        this.speechTimer = this.setTimer(() => fail('timeout', 'Câu đọc không kết thúc. Bấm thử giọng lại hoặc mở trong Safari.', 'end-timeout'), this.config.speechEndTimeout);
        this.voiceUpdate('started', 'Trình duyệt báo bắt đầu phát tiếng Việt. Hãy nghe âm thanh trên thiết bị.');
      };
      utterance.onend = () => {
        if (this.utterance !== utterance) return;
        if (!started) {fail('unconfirmed', 'Chưa xác nhận bắt đầu phát. Bấm thử giọng lại trong Safari.', 'end-before-start'); return;}
        const queued = this.queuedSpeech;
        this.clearTimer(this.speechTimer); this.speechTimer = null;
        this.utterance = null; this.utteranceManeuverKey = null; this.queuedSpeech = null; this.speaking = false;
        this.voiceUpdate('finished', 'Trình duyệt báo kết thúc câu đọc. Nếu không nghe được, thử Safari và kiểm tra âm thanh/giọng tiếng Việt của thiết bị.');
        if (queued && (this.active || queued.terminal && this.arrived)) this.speak(queued.text, queued);
      };
      utterance.onerror = event => fail('error', 'Không thể phát tiếng Việt (' + String(event.error || 'unknown').slice(0, 80) + '). Bấm thử lại hoặc mở trong Safari; vẫn có hướng dẫn hình ảnh.', String(event.error || 'unknown').slice(0, 80));
      utterance.onpause = () => {if (this.utterance === utterance) this.voiceUpdate('paused', 'Trình duyệt đang tạm dừng giọng nói. Nếu không tiếp tục, chờ thông báo rồi bấm thử lại.');};
      utterance.onresume = () => {if (this.utterance === utterance) this.voiceUpdate('started', 'Trình duyệt báo tiếp tục phát tiếng Việt.');};
      this.voiceUpdate('preparing', 'Đã gửi yêu cầu đọc; đang chờ trình duyệt xác nhận bắt đầu phát…');
      this.speechTimer = this.setTimer(() => fail('timeout', 'Chưa xác nhận phát tiếng Việt. Bấm thử giọng trực tiếp; nếu vẫn im lặng, mở Petro trong Safari và kiểm tra giọng tiếng Việt.', 'start-timeout'), this.config.speechStartTimeout);
      try {
        // Resume only as part of a direct user action, never periodically in GPS callbacks.
        if (direct && this.synth.paused) this.synth.resume?.();
        this.synth.speak(utterance);
      } catch (error) {fail('error', 'Không thể gửi yêu cầu giọng nói. Thử lại trong Safari.', error.name); return false;}
      return true; // Request accepted by JS, NOT proof of audible playback.
    }
    mute(value) {
      this.interacted = true; this.muted = value;
      if (value) {this.cancelSpeech(); this.voiceUpdate('muted', 'Giọng nói đang tắt.');}
      else this.loadVoices();
    }
    repeat() {this.interacted = true; if (this.active && this.guidance.guidanceValid && this.currentInstruction)
      this.speak(this.currentInstruction, {direct: true, maneuverKey: this.guidance.maneuverKey});}
    start() {
      if (this.active) return;
      this.interacted = true;
      if (!this.secure || !this.geolocation) {
        this.update({phase: 'error', gpsStatus: 'Cần HTTPS/localhost và trình duyệt hỗ trợ GPS.'}); return;
      }
      this.epoch++; this.active = true; this.route = null; this.progress = 0;
      this.currentInstruction = null; this.cancelSpeech();
      this.lastFixTime = null; this.lastAcceptedFix = null; this.offSince = null; this.lastReroute = null;
      this.announced = new Set(); this.arrived = false; this.busy = false; this.lastEligibility = null;
      this.lastGpsTimestamp = null; this.pendingPosition = null;
      this.arrivalCandidate = null;
      this.update({phase: 'starting', routeStatus: 'idle', gpsQuality: 'waiting',
        gpsStatus: 'Đang khởi động GPS; chờ quyền truy cập và vị trí thực…'});
      this.waitForGps();
      const epoch = this.epoch;
      try {
        const id = this.geolocation.watchPosition(pos => {
          if (this.active && epoch === this.epoch) return this.onPosition(pos);
        }, error => {
          if (!this.active || epoch !== this.epoch) return;
          this.stop(); this.update({phase: 'error', gpsQuality: 'error',
            gpsStatus: error.code === 1 ? 'Bạn chưa cho phép GPS. Hãy kiểm tra quyền vị trí rồi thử lại.' :
              error.code === 3 ? 'Hết thời gian chờ GPS. Bấm Bắt đầu đi để thử lại.' : 'GPS không khả dụng; dẫn đường đã dừng.'});
        }, {enableHighAccuracy: true, maximumAge: 0, timeout: 20000});
        // Some WebViews/mocks can fail before watchPosition returns its ID.
        if (this.active && epoch === this.epoch) this.watchId = id;
        else this.geolocation.clearWatch(id);
        // A click can initialize speech on browsers which require a user
        // gesture. Audible output still depends on installed vi-VN voices.
        if (this.active && !this.muted) this.speak('Đã bật dẫn đường. Đang xác định vị trí GPS.', {direct: true});
      } catch (error) {this.stop(); this.update({phase: 'error', gpsStatus: 'Không thể khởi động GPS. Có thể thử lại.'});}
    }
    endTracking() {
      this.active = false; this.epoch++;
      if (this.watchId !== null) this.geolocation?.clearWatch(this.watchId);
      this.watchId = null;
      this.routeController?.abort(); this.eligibilityController?.abort();
      this.routeController = null; this.eligibilityController = null;
      this.requestTimers.forEach(timer => this.clearTimer(timer)); this.requestTimers.clear();
      this.clearTimer(this.gpsTimer); this.gpsTimer = null;
      this.pendingPosition = null; this.busy = false; this.arrivalCandidate = null;
    }
    stop() {
      this.endTracking(); this.cancelSpeech();
      this.update({phase: this.arrived ? 'arrived' : 'stopped', routeStatus: this.arrived ? 'completed' : 'idle',
        gpsStatus: this.arrived ? 'Đã đến điểm cuối lộ trình; dẫn đường đã kết thúc.' : 'Đã dừng dẫn đường.'});
    }
    completeArrival() {
      if (!this.active || this.arrived) return;
      this.arrived = true; this.endTracking(); this.cancelSpeech();
      this.currentInstruction = 'Bạn đã đến trạm xăng.';
      this.update({phase: 'arrived', routeStatus: 'completed', instruction: this.currentInstruction,
        distance: 0, remainingDistance: 0, remainingDuration: 0, maneuver: {type:'arrive'},
        roadName: '', currentRoad: '', nextRoad: '', bearing: null, followingInstruction: '', atDeparture: false,
        guidanceValid: false, maneuverKey: null, gpsStatus: 'Đã đến điểm cuối lộ trình; dẫn đường đã kết thúc.'});
      this.speak(this.currentInstruction, {terminal: true});
    }
    requestDeadline(controller) {
      const timer = this.setTimer(() => controller.abort(), this.config.requestTimeout);
      this.requestTimers.add(timer); return timer;
    }
    clearRequestDeadline(timer) {
      this.clearTimer(timer); this.requestTimers.delete(timer);
    }
    destroy() {this.stop(); this.synth?.removeEventListener?.('voiceschanged', this.voiceListener);}
    async refreshRoute(fix, rerouting = false) {
      if (!this.active) return;
      const epoch = this.epoch; this.lastReroute = this.now();
      const revision = ++this.routeRevision;
      this.routeController?.abort();
      const controller = new AbortController(); this.routeController = controller;
      const timer = this.requestDeadline(controller);
      this.arrivalCandidate = null;
      this.queuedSpeech = null; // A pending maneuver from the old route must not play after replacement.
      this.update({routeStatus: 'loading', gpsStatus: rerouting ? 'Đang tính lại tuyến; GPS vẫn cập nhật.' : 'Đang lấy lộ trình từ GPS thực…'});
      try {
        const data = await this.fetchRoute(fix, {signal: controller.signal});
        if (!this.active || epoch !== this.epoch || revision !== this.routeRevision) return;
        this.onRoute(data); // Even fallback is shown honestly as a dashed preview.
        this.route = prepareRoute(data); this.progress = 0; this.lastFixTime = null;
        this.next = 1; this.announced = new Set(); this.offSince = null;
        if (this.now() - this.lastGpsTimestamp > this.config.maxFixAge)
          this.update({gpsQuality: 'stale', gpsStatus: 'GPS đã cũ trong lúc tải tuyến; chờ vị trí mới.'});
        this.publishGuidance({routeStatus: 'ready', phase: this.gpsQuality === 'valid' ? 'navigating' : 'waiting',
          ...(this.gpsQuality === 'valid' ? {gpsStatus: 'GPS sẵn sàng; đang theo dõi tuyến OSRM.'} : {})});
      } catch (error) {
        if (epoch !== this.epoch || revision !== this.routeRevision) return;
        this.stop(); this.update({phase: 'error', routeStatus: 'error', gpsStatus: 'Không thể dẫn đường: ' +
          (error.name === 'AbortError' ? 'Hết thời gian tải lộ trình; có thể thử lại.' : error.message)});
      } finally {this.clearRequestDeadline(timer); if (this.routeController === controller) this.routeController = null;}
    }
    async onPosition(position) {
      if (!this.active) return;
      const valid = validateGpsPosition(position, this.now(), this.config);
      if (valid.reason) {
        this.arrivalCandidate = null;
        // Show a *real but imprecise* position while waiting. Never use this
        // sample to authorize routing, arrival or spoken turns.
        if (valid.coarseFix) this.onFix(valid.coarseFix);
        this.update({gpsQuality: valid.coarseFix ? 'coarse' : 'rejected', phase: 'waiting', gpsStatus: valid.reason});
        this.waitForGps();
        return;
      }
      if (this.lastGpsTimestamp !== null && position.timestamp <= this.lastGpsTimestamp) {
        this.arrivalCandidate = null;
        this.update({gpsQuality: 'rejected', phase: 'waiting', gpsStatus: 'Bỏ qua callback GPS trùng/cũ; đang chờ vị trí mới.'}); return;
      }
      const fix = valid.fix, epoch = this.epoch;
      this.lastGpsTimestamp = position.timestamp; this.waitForGps();
      // Render actual GPS BEFORE eligibility/OSRM awaits; never snap to a route.
      this.onFix(fix);
      this.update({fix, gpsQuality: 'valid', phase: this.route ? 'navigating' : 'starting',
        gpsStatus: `GPS ±${Math.round(fix.accuracy)} m; ${this.busy ? 'đang xử lý tuyến, vị trí vẫn cập nhật.' : 'đã nhận vị trí thực.'}`});
      this.pendingPosition = {fix, timestamp: position.timestamp};
      if (this.busy) return; // Marker updated; keep latest sample for matching.
      this.busy = true;
      try {
        while (this.active && epoch === this.epoch && this.pendingPosition) {
          const next = this.pendingPosition; this.pendingPosition = null;
          await this.processPosition(next, epoch);
        }
      } finally {if (epoch === this.epoch) {this.busy = false; this.update({});}}
    }
    async processPosition(position, epoch) {
      if (!this.active || epoch !== this.epoch) return;
      let {fix} = position;
      const now = this.now();
      try {
        if (this.lastEligibility === null || now - this.lastEligibility >= this.config.eligibilityInterval) {
          const controller = new AbortController(); this.eligibilityController = controller;
          const timer = this.requestDeadline(controller);
          try {await this.checkEligibility({signal: controller.signal}); if (this.active && epoch === this.epoch) this.lastEligibility = now;}
          finally {this.clearRequestDeadline(timer); if (this.eligibilityController === controller) this.eligibilityController = null;}
        }
      } catch (error) {
        if (epoch === this.epoch) {this.stop(); this.update({phase: 'error', gpsStatus: 'Trạm không còn khả dụng hoặc không thể xác minh trạng thái; đã dừng.'});}
        return;
      }
      if (!this.active || epoch !== this.epoch) return;
      // Coalesce fixes received during authorization; do not replay stale work.
      if (this.pendingPosition) {position = this.pendingPosition; this.pendingPosition = null; fix = position.fix;}
      if (this.now() - position.timestamp > this.config.maxFixAge) {
        this.arrivalCandidate = null;
        this.update({phase: 'waiting', gpsQuality: 'stale', gpsStatus: 'GPS đã cũ trong lúc chờ mạng; chờ vị trí mới.'}); return;
      }
      if (this.gpsQuality !== 'valid') return;
      if (!this.route) {
        await this.refreshRoute(fix);
        if (this.active && epoch === this.epoch && this.route) {
          this.lastFixTime = position.timestamp; this.lastAcceptedFix = fix;
        }
        return;
      }
      const elapsed = this.lastFixTime === null ? 1 : Math.max(1, (position.timestamp - this.lastFixTime) / 1000);
      // Some browsers omit speed. Derive only a bounded tolerance from real fixes,
      // not a simulated vehicle speed, and never use it as a driving-distance metric.
      const movementSpeed = this.lastAcceptedFix ? meters([this.lastAcceptedFix.longitude, this.lastAcceptedFix.latitude],
        [fix.longitude, fix.latitude]) / elapsed : 0;
      const speed = Math.max(0, Math.min(60, Number.isFinite(fix.speed) ? fix.speed : movementSpeed));
      const projection = projectFix(fix, this.route, this.progress, Math.min(500, Math.max(100, speed * elapsed * 2 + fix.accuracy * 2 + 30)));
      const off = !projection || projection.distance > Math.max(this.config.offRouteMeters, fix.accuracy * 2);
      if (off) {
        this.arrivalCandidate = null;
        if (this.offSince === null) this.offSince = now;
        this.update({phase: 'waiting', gpsStatus: 'Vị trí lệch tuyến; đang xác minh để tránh nhiễu GPS.'});
        if (now - this.offSince >= this.config.offRouteDebounce && (this.lastReroute === null || now - this.lastReroute >= this.config.rerouteCooldown)) {
          this.speak('Bạn có thể đã lệch tuyến. Đang tính lại lộ trình.');
          await this.refreshRoute(fix, true);
          if (this.active && epoch === this.epoch && this.route) {
            this.lastFixTime = position.timestamp; this.lastAcceptedFix = fix;
          }
        }
        return;
      }
      this.offSince = null; this.lastFixTime = position.timestamp;
      this.lastAcceptedFix = fix;
      this.progress = Math.max(this.progress, projection.along);
      const maneuvers = this.route.maneuvers;
      while (this.next < maneuvers.length - 1) {
        const gap = maneuvers[this.next + 1].offset - maneuvers[this.next].offset;
        // Preserve normal GPS hysteresis, but never let it consume an entire
        // short connector and hide the following turn (e.g. two turns 10 m apart).
        const passedBuffer = Math.min(Math.max(20, fix.accuracy), gap / 2);
        if (this.progress <= maneuvers[this.next].offset + passedBuffer) break;
        this.next++;
      }
      const current = maneuvers[this.next], remaining = Math.max(0, current.offset - this.progress);
      this.publishGuidance({phase: 'navigating', gpsStatus: `GPS ±${Math.round(fix.accuracy)} m; hỗ trợ dẫn đường thử nghiệm.`, fix});
      if (current.step.maneuver.type === 'arrive') {
        // The same existing endpoint detector, now requiring consecutive slow,
        // accurate real fixes. Proximity alone cannot prove access to a forecourt.
        if (remaining <= this.config.arrivalMeters && fix.accuracy <= this.config.arrivalMaxAccuracy &&
            speed <= this.config.arrivalMaxSpeed &&
            meters([fix.longitude, fix.latitude], this.route.points[this.route.points.length - 1]) <= this.config.arrivalMeters) {
          const previous = this.arrivalCandidate;
          this.arrivalCandidate = previous && position.timestamp - previous.last <= this.config.arrivalMaxGap ?
            {...previous, count: previous.count + 1, last: position.timestamp} :
            {count: 1, since: position.timestamp, last: position.timestamp};
          if (this.arrivalCandidate.count >= this.config.arrivalConfirmFixes &&
              position.timestamp - this.arrivalCandidate.since >= this.config.arrivalConfirmMs) this.completeArrival();
        } else this.arrivalCandidate = null;
        return;
      }
      this.arrivalCandidate = null;
      const early = Math.min(600, Math.max(this.config.earlyMeters, speed * 20));
      const near = Math.min(150, Math.max(this.config.nearMeters, speed * 5, fix.accuracy * 2));
      const phase = remaining <= near ? 'near' : remaining <= early ? 'early' : null;
      if (phase && !this.announced.has(`${this.next}:${phase}`)) {
        // Don't consume the threshold before speech has been initialized by a real gesture.
        if (this.speak(this.currentInstruction, {maneuverKey: this.guidance.maneuverKey})) {
          this.announced.add(`${this.next}:${phase}`);
          // If first GPS fix is already close, don't enqueue an obsolete early warning.
          if (phase === 'near') this.announced.add(`${this.next}:early`);
        }
      }
    }
  }
  const api = {VoiceNavigation, instruction, prepareRoute, projectFix, meters, validateGpsPosition, CONFIG};
  root.PetroNavigation = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
