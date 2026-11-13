/**
 * Petro Map display and Smart Routing client.
 * Ranking and route calculations are performed by backend services.
 */

// Tọa độ trung tâm Cần Thơ (nơi tập trung mạng lưới trạm xăng trong CSDL)
const DEFAULT_COORDS = {
  lat: 10.0298,
  lng: 105.7765,
  name: "Cần Thơ (Trung tâm trạm xăng)"
};

class PetroMapService {
  constructor() {
    this.map = null;
    this.userLocation = { lat: DEFAULT_COORDS.lat, lng: DEFAULT_COORDS.lng };
    this.userMarker = null;
    this.stationMarkers = [];
    this.routeLayer = null;
    this.stations = [];
    this.currentNearest = null;
    this.recommendations = [];
    this.excludeStations = [];
    this.currentHeading = null;
    this.selectedStation = null;
    this.vehicleType = "car"; // 'car' | 'motorbike'
    this.activeFuelFilter = null;
    this.activeServiceFilter = null;
    this.activeRadiusFilter = null;
    this.searchQuery = "";
    this.amenityIds = [];
    this.amenityMatch = 'all';
    this.hasInitialFitted = false;

    this.init();
  }

  async init() {
    const savedFilters = new URLSearchParams(window.location.search);
    this.amenityIds = [...new Set(savedFilters.getAll('amenity_ids'))];
    this.amenityMatch = savedFilters.get('amenity_match') === 'any' ? 'any' : 'all';
    this.activeFuelFilter = savedFilters.get('fuel_type');
    this.activeRadiusFilter = Number(savedFilters.get('radius_km')) || null;
    this.searchQuery = savedFilters.get('search') || '';
    const searchInput = document.getElementById('station-search-input');
    if (searchInput) searchInput.value = this.searchQuery;
    this.updateFilterChips();
    // Catalog loading must not depend on Leaflet/CDN initialization succeeding.
    const amenitiesReady = this.loadAmenities();
    try {
      this.initLeafletMap();
      this.setupEventListeners();
    } catch (error) {
      console.error('Không thể khởi tạo bản đồ:', error);
      const list = document.getElementById('station-list');
      if (list) list.textContent = 'Không thể khởi tạo bản đồ. Vui lòng tải lại trang; danh mục tiện ích vẫn có thể xem.';
      await amenitiesReady;
      return;
    }
    await amenitiesReady;
    // Refresh on returning to the map, without polling or calling OSRM.
    window.addEventListener("focus", () => this.fetchAndRenderStations());
    window.addEventListener("pageshow", event => {
      if (event.persisted) this.fetchAndRenderStations();
    });
    await this.fetchAndRenderStations();
    await this.detectUserLocation();

    // Kiểm tra query parameter (vd: ?action=nearest hoặc ?tx_ma=...)
    const urlParams = new URLSearchParams(window.location.search);
    this.excludeStations = (urlParams.get("exclude") || "").split(",").filter(Boolean);
    if (urlParams.get("action") === "nearest") {
      setTimeout(() => this.findNearestStation(), 700);
    } else if (urlParams.get("tx_ma")) {
      const targetMa = urlParams.get("tx_ma");
      setTimeout(() => this.selectStationById(targetMa), 700);
    }
  }

  /**
   * Khởi tạo bản đồ Leaflet với lớp bản đồ chất lượng cao
   */
  initLeafletMap() {
    const mapContainer = document.getElementById("petro-map");
    if (!mapContainer) return;

    this.map = L.map("petro-map", {
      zoomControl: false, // Dùng controls tùy biến
      attributionControl: true,
      dragging: true,
      touchZoom: true,
      scrollWheelZoom: true,
      doubleClickZoom: true,
      boxZoom: true,
      keyboard: true
    }).setView([DEFAULT_COORDS.lat, DEFAULT_COORDS.lng], 14);

    // Shared basemap lifecycle/diagnostics; does not fetch/rank stations or routes.
    this.basemaps = PetroBasemaps.attach(this.map);

    // Cho phép người dùng click trên bản đồ để đổi vị trí giả lập
    this.map.on("click", (e) => {
      this.setUserLocation(e.latlng.lat, e.latlng.lng, "Vị trí đã chọn");
      this.fetchAndRenderStations();
    });

    this.updateUserMarker();
  }

  /**
   * Mở bộ chọn nền; không thay đổi camera, marker, route hay recommendation.
   */
  toggleMapLayer() {
    if (this.basemaps) this.basemaps.togglePopover();
  }

  /**
   * Căn góc nhìn vào trung tâm cụm 10 trạm xăng Cần Thơ
   */
  focusCanThoCenter() {
    if (!this.map) return;
    if (this.stationMarkers.length > 0) {
      const group = L.featureGroup(this.stationMarkers);
      this.map.fitBounds(group.getBounds(), { padding: [40, 40] });
      this.showToast("🎯 Đang xem cận cảnh mạng lưới trạm xăng Cần Thơ");
    } else {
      this.map.flyTo([DEFAULT_COORDS.lat, DEFAULT_COORDS.lng], 14);
    }
  }

  /**
   * Cập nhật Marker vị trí người dùng
   */
  updateUserMarker() {
    if (!this.map) return;

    const userIcon = L.divIcon({
      className: "user-pin-container",
      html: `
        <div style="position: relative; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;">
          <div style="position: absolute; width: 32px; height: 32px; border-radius: 50%; background: rgba(16, 185, 129, 0.35);" class="radar-ring"></div>
          <div style="width: 16px; height: 16px; border-radius: 50%; background: #006c49; border: 2.5px solid white; box-shadow: 0 2px 6px rgba(0,0,0,0.35);"></div>
        </div>
      `,
      iconSize: [32, 32],
      iconAnchor: [16, 16]
    });

    if (this.userMarker) {
      this.userMarker.setLatLng([this.userLocation.lat, this.userLocation.lng]);
    } else {
      this.userMarker = L.marker([this.userLocation.lat, this.userLocation.lng], {
        icon: userIcon,
        zIndexOffset: 1000,
        draggable: true
      }).addTo(this.map);

      this.userMarker.bindTooltip("Vị trí của bạn (Kéo thả để di chuyển)", {
        direction: "top",
        offset: [0, -10]
      });

      this.userMarker.on("dragend", (e) => {
        const pos = e.target.getLatLng();
        this.setUserLocation(pos.lat, pos.lng, "Vị trí kéo thả");
        this.fetchAndRenderStations();
      });
    }
  }

  /**
   * Thiết lập vị trí người dùng
   */
  setUserLocation(lat, lng, label = "Vị trí hiện tại") {
    this.userLocation = { lat, lng };
    this.updateUserMarker();
    this.showToast(`📍 Đã cập nhật ${label}`);
  }

  /**
   * Tự động lấy vị trí GPS thực tế
   */
  async detectUserLocation() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) {
        resolve(false);
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const { latitude, longitude, heading } = pos.coords;
          this.userLocation = { lat: latitude, lng: longitude };
          this.currentHeading = Number.isFinite(heading) ? heading : null;
          this.updateUserMarker();
          this.persistLatestLocation();

          // Tính khoảng cách tới cụm trạm Cần Thơ
          const distKm = Math.hypot(latitude - DEFAULT_COORDS.lat, longitude - DEFAULT_COORDS.lng) * 111;

          if (distKm <= 20) {
            // Nếu người dùng ở trong phạm vi Cần Thơ, zoom vào người dùng
            if (this.map) this.map.flyTo([latitude, longitude], 14, { duration: 0.8 });
          } else {
            // Nếu người dùng ở xa (như Trà Vinh, Vĩnh Long > 20km), giữ góc nhìn trạm Cần Thơ để người dùng thấy rõ đường và trạm
            this.showToast(`📍 Vị trí GPS cách trạm Cần Thơ ~${Math.round(distKm)} km. Đang hiển thị khu vực trạm.`);
          }
          this.fetchAndRenderStations();
          resolve(true);
        },
        (err) => {
          this.userLocation = { lat: DEFAULT_COORDS.lat, lng: DEFAULT_COORDS.lng };
          this.updateUserMarker();
          if (this.map) this.map.setView([DEFAULT_COORDS.lat, DEFAULT_COORDS.lng], 14);
          resolve(false);
        },
        { timeout: 5000, enableHighAccuracy: true }
      );
    });
  }

  async persistLatestLocation() {
    // TODO: Wire this to the authenticated username once the login/session
    // contract is available. Never invent or hard-code a username here.
    const username = window.sessionStorage.getItem("petro_username");
    if (!username) return;
    try {
      await fetch("/api/locations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          nd_tendangnhap: username,
          thoigian: new Date().toISOString(),
          kinhdo: this.userLocation.lng,
          vido: this.userLocation.lat
        })
      });
    } catch (error) {
      console.warn("Không thể lưu vị trí mới nhất:", error);
    }
  }

  /**
   * Gọi API lấy danh sách trạm xăng gần nhất
   */
  async fetchAndRenderStations() {
    const refreshGeneration = this.refreshGeneration = (this.refreshGeneration || 0) + 1;
    const listContainer = document.getElementById("station-list");
    if (listContainer && this.stations.length === 0) {
      listContainer.innerHTML = `
        <div class="flex flex-col items-center justify-center p-8 text-center text-secondary">
          <div class="w-8 h-8 border-3 border-primary border-t-transparent rounded-full animate-spin mb-3"></div>
          <p class="text-body-md">Đang quét trạm xăng gần bạn...</p>
        </div>
      `;
    }

    try {
      const params = new URLSearchParams({
        lat: this.userLocation.lat,
        lng: this.userLocation.lng,
        vehicle_type: this.vehicleType
      });

      if (this.searchQuery) params.append("search", this.searchQuery);
      if (this.activeFuelFilter) params.append("fuel_type", this.activeFuelFilter);
      if (this.activeServiceFilter) params.append("service", this.activeServiceFilter);
      if (this.activeRadiusFilter) params.append("radius_km", this.activeRadiusFilter);
      this.amenityIds.forEach(id => params.append('amenity_ids', id));
      params.set('amenity_match', this.amenityMatch);

      const response = await fetch(`/api/map/stations?${params.toString()}`, {cache: "no-store"});
      if (!response.ok) throw new Error(`Station display HTTP ${response.status}`);
      const data = await response.json();
      if (refreshGeneration !== this.refreshGeneration) return;

      if (data.status === "success") {
        this.stations = data.stations || [];
        this.currentNearest = null;
        this.selectedStation = null;
        this.recommendations = [];
        this.renderRecommendations();
        if (this.routeLayer) {
          this.map.removeLayer(this.routeLayer);
          this.routeLayer = null;
        }
        document.getElementById("route-summary-banner")?.classList.add("hidden");
        this.renderMapMarkers();
        this.renderStationList();
        this.updateStationCount(this.stations.length);

        if (this.map) this.map.invalidateSize();
      }
    } catch (error) {
      if (refreshGeneration !== this.refreshGeneration) return;
      console.error("Lỗi khi tải danh sách trạm xăng:", error);
      this.stations = [];
      this.recommendations = [];
      this.selectedStation = null;
      this.currentNearest = null;
      if (this.routeLayer) {
        this.map.removeLayer(this.routeLayer);
        this.routeLayer = null;
      }
      document.getElementById("route-summary-banner")?.classList.add("hidden");
      this.renderRecommendations();
      this.renderMapMarkers();
      this.renderStationList();
      this.showToast("Thông tin trạm tạm thời không khả dụng.");
    }
  }

  /**
   * Render các Marker trạm xăng lên bản đồ
   */
  renderMapMarkers() {
    // Xóa marker cũ
    this.stationMarkers.forEach(m => this.map.removeLayer(m));
    this.stationMarkers = [];

    this.stations.forEach((st, index) => {
      const isNearest = false;
      const badgeColor = isNearest ? "#006c49" : (st.brand_color || "#006c49");

      // Marker HTML sạch không bị xung đột CSS
      const markerHtml = `
        <div style="display: flex; flex-direction: column; align-items: center; cursor: pointer; user-select: none;">
          <div style="background: white; border: 1.5px solid ${badgeColor}; border-radius: 9999px; padding: 1px 6px; box-shadow: 0 2px 5px rgba(0,0,0,0.15); display: flex; align-items: center; gap: 4px; white-space: nowrap;">
            <span style="width: 7px; height: 7px; border-radius: 50%; background: ${badgeColor}; display: inline-block;"></span>
            <span style="font-size: 11px; font-weight: 700; color: #1f2937;">${PetroTravelFormat.straight(st.straight_line_distance_km)}</span>
          </div>
          <div style="width: 32px; height: 32px; border-radius: 50%; background: ${badgeColor}; color: white; display: flex; align-items: center; justify-content: center; box-shadow: 0 3px 8px rgba(0,0,0,0.25); border: 2px solid white; margin-top: -2px;">
            <span class="material-symbols-outlined" style="font-size: 18px; font-variation-settings: 'FILL' 1;">local_gas_station</span>
          </div>
        </div>
      `;

      const icon = L.divIcon({
        className: `station-pin station-${st.tx_ma}`,
        html: markerHtml,
        iconSize: [60, 50],
        iconAnchor: [30, 48]
      });

      const marker = L.marker([st.lat, st.lng], { icon }).addTo(this.map);

      // Popup chi tiết
      const fuelListHtml = (st.fuels || []).slice(0, 3).map(f => `
        <div class="flex justify-between items-center text-xs py-1 border-b border-gray-100 last:border-0">
          <span class="text-gray-600 font-medium">${f.name}</span>
          <span class="font-bold text-emerald-700">${f.price.toLocaleString("vi-VN")} đ</span>
        </div>
      `).join("");

      const servicesHtml = (st.services || []).slice(0, 3).map(s => `
        <span class="px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-[11px]">${s}</span>
      `).join("");

      const popupContent = `
        <div class="p-1 min-w-[240px] font-sans">
          <div class="flex items-start justify-between mb-1.5">
            <div>
              <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold text-white mb-1" style="background-color: ${badgeColor};">
                ${st.brand || 'Chưa xác định'}
              </span>
              <h4 class="font-bold text-[15px] text-gray-900 leading-snug">${petroEscapeHtml(st.tx_ten)}</h4>
            </div>
            <div class="flex items-center gap-0.5 bg-yellow-50 px-1.5 py-0.5 rounded text-[11px] font-bold text-yellow-700">
              <span class="material-symbols-outlined text-[13px] text-yellow-500" style="font-variation-settings: 'FILL' 1;">star</span>
              ${st.rating == null ? 'Chưa có' : st.rating}
            </div>
          </div>

          <p class="text-xs text-gray-500 mb-2 leading-tight">${petroEscapeHtml(st.tx_diachi)}</p>

          <div class="flex items-center gap-2 mb-2.5">
            <span class="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 bg-emerald-50 px-2 py-1 rounded-md">
              <span class="material-symbols-outlined text-[14px]">straighten</span> ${PetroTravelFormat.straight(st.straight_line_distance_km)}
            </span>
          </div>

          <div class="bg-gray-50 p-2 rounded-lg mb-2.5">
            <div class="text-[11px] font-bold text-gray-700 uppercase tracking-wider mb-1">Giá xăng dầu hôm nay</div>
            ${fuelListHtml}
          </div>

          <div class="flex flex-wrap gap-1 mb-3">
            ${servicesHtml}
          </div>

          <div class="grid grid-cols-2 gap-2 pt-1 border-t border-gray-100">
            <a href="/ChiTiet.html?tx_ma=${st.tx_ma}" class="py-1.5 px-3 rounded-lg border border-gray-200 text-gray-700 font-medium text-xs text-center hover:bg-gray-50">
              Chi tiết
            </a>
            <button onclick="window.petroMap.drawRouteToStation('${st.tx_ma}')" class="py-1.5 px-3 rounded-lg bg-emerald-700 text-white font-bold text-xs text-center hover:bg-emerald-800 flex items-center justify-center gap-1 shadow-sm">
              <span class="material-symbols-outlined text-[15px]">directions</span> Chỉ đường
            </button>
          </div>
        </div>
      `;

      marker.bindPopup(popupContent, { maxWidth: 300, className: "petro-popup" });

      marker.on("click", () => {
        this.highlightSidebarCard(st.tx_ma);
      });

      this.stationMarkers.push(marker);
    });
  }

  /**
   * Render danh sách thẻ trạm xăng ở thanh bên trái (Sidebar)
   */
  renderStationList() {
    const listContainer = document.getElementById("station-list");
    if (!listContainer) return;

    if (this.stations.length === 0) {
      listContainer.innerHTML = `
        <div class="flex flex-col items-center justify-center p-8 text-center text-secondary">
          <span class="material-symbols-outlined text-[48px] text-outline mb-2">search_off</span>
          <p class="font-bold text-on-surface">Không tìm thấy trạm xăng phù hợp</p>
          <p class="text-body-md text-on-surface-variant mt-1">Hãy thử xóa bộ lọc hoặc tìm kiếm từ khóa khác.</p>
          <button onclick="window.petroMap.resetFilters()" class="btn-secondary mt-4 py-2 px-4 text-xs font-semibold">
            Đặt lại bộ lọc
          </button>
        </div>
      `;
      return;
    }

    let html = "";
    this.stations.forEach((st, index) => {
      const isNearest = false;
      const brandColor = isNearest ? "#006c49" : (st.brand_color || "#545f73");

      const fuelBadge = (st.fuels && st.fuels.length > 0)
        ? `<div class="bg-surface-container-low px-2 py-1 rounded text-label-md text-on-surface flex justify-between items-center border border-outline-variant/30 mt-1">
             <span class="font-medium text-xs text-secondary">${st.fuels[0].name}</span>
             <span class="font-bold text-xs text-primary">${st.fuels[0].price.toLocaleString("vi-VN")} đ/L</span>
           </div>`
        : "";

      html += `
        <div id="card-${st.tx_ma}" 
             onclick="window.petroMap.selectStationById('${st.tx_ma}')"
             class="card-base p-md hover:border-primary-container transition-all cursor-pointer station-card ${isNearest ? 'border-primary ring-1 ring-primary/20 bg-emerald-50/20' : ''}">
          
          <div class="flex justify-between items-start mb-xs">
            <div class="flex-1 pr-2">
              <div class="flex items-center gap-1.5 mb-1">
                <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold text-white" style="background-color: ${brandColor};">
                  ${st.brand || 'Chưa xác định'}
                </span>
                ${isNearest ? '<span class="bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-0.5"><span class="material-symbols-outlined text-[12px]">verified</span> GẦN NHẤT</span>' : ''}
              </div>
              <h3 class="text-title-md font-bold text-on-surface line-clamp-1">${petroEscapeHtml(st.tx_ten)}</h3>
            </div>
            
            <div class="flex items-center gap-xs bg-surface-container px-2 py-0.5 rounded text-label-md font-medium text-on-surface-variant shrink-0">
              <span class="text-tertiary-container material-symbols-outlined text-[14px]" style="font-variation-settings: 'FILL' 1;">star</span>
              ${st.rating == null ? 'Chưa có' : st.rating}
            </div>
          </div>

          <p class="text-body-md text-on-surface-variant mb-sm line-clamp-1">${petroEscapeHtml(st.tx_diachi)}</p>

          <div class="flex flex-wrap gap-sm mb-sm">
            <span class="inline-flex items-center gap-xs px-2 py-1 rounded-md bg-surface-container-low text-label-md text-secondary border border-outline-variant/50">
              <span class="material-symbols-outlined text-[14px]">route</span>
              ${PetroTravelFormat.straight(st.straight_line_distance_km)}
            </span>
          </div>

          ${fuelBadge}

          <div class="flex gap-sm mt-md pt-xs border-t border-outline-variant/30">
            <a href="/ChiTiet.html?tx_ma=${st.tx_ma}" onclick="event.stopPropagation()" class="btn-secondary flex-1 py-1.5 text-center text-label-md">
              Chi tiết
            </a>
            <button onclick="event.stopPropagation(); window.petroMap.drawRouteToStation('${st.tx_ma}')" class="btn-primary flex-1 py-1.5 text-center text-label-md">
              <span class="material-symbols-outlined text-[16px]">directions</span> Chỉ đường
            </button>
          </div>
        </div>
      `;
    });

    listContainer.innerHTML = html;
  }

  /**
   * Chọn trạm theo mã trạm: Zoom tới marker, mở popup và highlight thẻ
   */
  selectStationById(tx_ma) {
    const station = this.stations.find(s => s.tx_ma === tx_ma);
    if (!station || !this.map) return;

    this.selectedStation = station;
    this.map.flyTo([station.lat, station.lng], 16, { duration: 0.8 });

    const markerIndex = this.stations.findIndex(s => s.tx_ma === tx_ma);
    if (markerIndex !== -1 && this.stationMarkers[markerIndex]) {
      this.stationMarkers[markerIndex].openPopup();
    }

    this.highlightSidebarCard(tx_ma);
  }

  /**
   * Làm nổi bật thẻ trong Sidebar và cuộn tới vị trí của thẻ
   */
  highlightSidebarCard(tx_ma) {
    document.querySelectorAll(".station-card").forEach(c => {
      c.classList.remove("ring-2", "ring-primary", "bg-emerald-50/40");
    });

    const card = document.getElementById(`card-${tx_ma}`);
    if (card) {
      card.classList.add("ring-2", "ring-primary", "bg-emerald-50/40");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  /** Smart Routing là nguồn duy nhất để xếp hạng trạm. */
  async findNearestStation() {
    await this.fetchAndRenderStations();
    const refreshGeneration = this.refreshGeneration;
    try {
      const response = await fetch("/api/routing/recommendations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          latitude: this.userLocation.lat,
          longitude: this.userLocation.lng,
          heading: Number.isFinite(this.currentHeading) ? this.currentHeading : null,
          radius_km: this.activeRadiusFilter || 10,
          exclude_stations: this.excludeStations,
          limit: 3,
          ...this.discoveryFilters()
        })
      });
      if (!response.ok) throw new Error(`Smart Routing HTTP ${response.status}`);
      const data = await response.json();
      if (refreshGeneration !== this.refreshGeneration) return;
      this.recommendations = data.recommendations || [];
      this.renderRecommendations();
      if (this.recommendations.length === 0) {
        this.showToast(data.message || "Không tìm thấy trạm phù hợp.");
        return;
      }
      const best = this.recommendations[0];
      await this.drawRouteToStation(best.station_id);
    } catch (error) {
      console.error("Không thể lấy Smart Routing recommendations:", error);
      this.showToast("Không thể tải gợi ý định tuyến lúc này.");
    }
  }

  renderRecommendations() {
    const container = document.getElementById("routing-recommendations");
    if (!container) return;
    if (this.recommendations.length === 0) {
      container.innerHTML = "";
      container.classList.add("hidden");
      return;
    }
    container.innerHTML = this.recommendations.map((item, index) => `
      <div class="p-3 border-b border-slate-100 last:border-0">
        <div class="flex justify-between gap-2">
          <button class="text-left flex-1" onclick="window.petroMap.selectRecommendation('${item.station_id}')">
            <div class="font-bold text-sm">${index + 1}. ${petroEscapeHtml(item.station_name)}</div>
            <div class="text-xs text-gray-600">${PetroTravelFormat.road(item)} • ${PetroTravelFormat.eta(item)} • ${item.traffic_level}</div>
            <div class="text-[11px] text-emerald-700 mt-1">${item.labels.join(" • ")}</div>
            <div class="text-[11px] text-gray-500">${item.reason}</div>
          </button>
          <button class="text-xs text-red-600 font-semibold" onclick="window.petroMap.skipRecommendedStation('${item.station_id}')">Bỏ qua</button>
        </div>
      </div>
    `).join("");
    container.classList.remove("hidden");
  }

  async selectRecommendation(stationId) {
    this.selectStationById(stationId);
    await this.drawRouteToStation(stationId);
  }

  async skipRecommendedStation(stationId) {
    if (!this.excludeStations.includes(stationId)) this.excludeStations.push(stationId);
    await this.findNearestStation();
  }

  /**
   * Vẽ geometry do backend routing provider trả về.
   */
  async drawRouteToStation(tx_ma) {
    if (!this.map) return;
    const refreshGeneration = this.refreshGeneration;
    // Never route using a stale marker or a pending update snapshot.
    let display;
    try {
      display = await fetch(`/api/map/stations/${encodeURIComponent(tx_ma)}`, {cache: "no-store"});
    } catch (error) {
      await this.fetchAndRenderStations();
      this.showToast("Thông tin trạm tạm thời không khả dụng.");
      return;
    }
    if (!display.ok) {
      await this.fetchAndRenderStations();
      this.showToast("Trạm không còn công khai hoặc thông tin tạm thời không khả dụng.");
      return;
    }
    const station = (await display.json()).station;
    if (refreshGeneration !== this.refreshGeneration) return;

    this.selectedStation = station;
    this.highlightSidebarCard(tx_ma);

    // Xóa tuyến đường cũ nếu có
    if (this.routeLayer) {
      this.map.removeLayer(this.routeLayer);
      this.routeLayer = null;
    }

    try {
      const url = `/api/routing/route?start_lat=${this.userLocation.lat}&start_lng=${this.userLocation.lng}&end_lat=${station.lat}&end_lng=${station.lng}&station_id=${encodeURIComponent(tx_ma)}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Route geometry HTTP ${res.status}`);
      const data = await res.json();
      if (refreshGeneration !== this.refreshGeneration) return;

      if (data.geometry && data.geometry.coordinates) {
        const coordinates = data.geometry.coordinates.map(coord => [coord[1], coord[0]]);

        // Tuyến đường viền ngoài
        const routeOutline = L.polyline(coordinates, {
          color: "#00422b",
          weight: 7,
          opacity: 0.6,
          lineCap: "round",
          lineJoin: "round"
        });

        // Tuyến đường sáng bên trong
        const routeInner = L.polyline(coordinates, {
          color: "#10b981",
          weight: 4,
          opacity: 0.95,
          dashArray: data.is_fallback ? "8, 6" : null,
          lineCap: "round",
          lineJoin: "round"
        });

        this.routeLayer = L.layerGroup([routeOutline, routeInner]).addTo(this.map);

        const bounds = L.latLngBounds([
          [this.userLocation.lat, this.userLocation.lng],
          [station.lat, station.lng]
        ]);
        this.map.fitBounds(bounds, { padding: [80, 80] });

        const markerIndex = this.stations.findIndex(s => s.tx_ma === tx_ma);
        if (markerIndex !== -1 && this.stationMarkers[markerIndex]) {
          this.stationMarkers[markerIndex].openPopup();
        }

        this.showRouteSummary(station.tx_ten, data.distance_km, data.duration_minutes, data.routing_source, data.is_fallback);
      }
    } catch (err) {
      console.warn("Không thể tải route geometry từ backend:", err);
      await this.fetchAndRenderStations();
      this.showToast("Không thể hiển thị lộ trình lúc này.");
    }
  }

  /**
   * Hiển thị bảng tóm tắt lộ trình chỉ đường
   */
  showRouteSummary(stationName, distanceKm, durationMinutes, routingSource, isFallback) {
    const banner = document.getElementById("route-summary-banner");
    if (!banner) return;

    const route = {distance_km: distanceKm, duration_minutes: durationMinutes, routing_source: routingSource, is_fallback: isFallback};
    const kmText = PetroTravelFormat.road(route);
    banner.innerHTML = `
      <div class="flex items-center justify-between gap-4 bg-white/95 backdrop-blur-md p-3 px-4 rounded-xl shadow-xl border border-emerald-200">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-full bg-emerald-600 text-white flex items-center justify-center shrink-0">
            <span class="material-symbols-outlined text-[22px]">navigation</span>
          </div>
          <div>
            <h4 class="font-bold text-sm text-gray-900 line-clamp-1">Đến ${petroEscapeHtml(stationName)}</h4>
            <div class="flex items-center gap-2 text-xs text-gray-600 mt-0.5">
              <span class="font-bold text-emerald-700">${kmText}</span>
              <span>•</span>
              <span>${PetroTravelFormat.eta(route)}</span>
              <span>• ${routingSource}${routingSource === 'haversine_fallback' ? ' (ước lượng đường thẳng)' : ''}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <a href="${petroEscapeHtml(this.navigationUrl())}" class="btn-primary py-2 px-3 text-xs font-bold rounded-lg whitespace-nowrap flex items-center gap-1">
            Bắt đầu đi <span class="material-symbols-outlined text-[16px]">arrow_forward</span>
          </a>
          <button onclick="document.getElementById('route-summary-banner').classList.add('hidden')" class="p-1 hover:bg-gray-100 rounded-full text-gray-400">
            <span class="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
      </div>
    `;
    banner.classList.remove("hidden");
  }

  /**
   * Thiết lập các bộ lắng nghe sự kiện
   */
  setupEventListeners() {
    // Ô tìm kiếm
    const searchInput = document.getElementById("station-search-input");
    if (searchInput) {
      let debounceTimer = null;
      searchInput.addEventListener("input", (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          this.searchQuery = e.target.value.trim();
          this.fetchAndRenderStations();
        }, 300);
      });
    }

    // Nút "Vị trí hiện tại"
    const myLocationBtns = document.querySelectorAll(".btn-my-location");
    myLocationBtns.forEach(btn => {
      btn.addEventListener("click", async () => {
        btn.classList.add("animate-pulse");
        await this.detectUserLocation();
        await this.fetchAndRenderStations();
        btn.classList.remove("animate-pulse");
      });
    });

    // Nút "Tìm trạm gần nhất"
    const findNearestBtns = document.querySelectorAll(".btn-find-nearest");
    findNearestBtns.forEach(btn => {
      btn.addEventListener("click", () => {
        this.findNearestStation();
      });
    });

    // Nút Zoom
    const btnZoomIn = document.getElementById("btn-zoom-in");
    const btnZoomOut = document.getElementById("btn-zoom-out");
    if (btnZoomIn) btnZoomIn.addEventListener("click", () => this.map && this.map.zoomIn());
    if (btnZoomOut) btnZoomOut.addEventListener("click", () => this.map && this.map.zoomOut());
  }

  setFuelFilter(fuelCode) {
    this.activeFuelFilter = (this.activeFuelFilter === fuelCode) ? null : fuelCode;
    this.updateFilterChips();
    this.fetchAndRenderStations();
  }

  setRadiusFilter(radiusKm) {
    this.activeRadiusFilter = (this.activeRadiusFilter === radiusKm) ? null : radiusKm;
    this.updateFilterChips();
    this.fetchAndRenderStations();
  }

  updateFilterChips() {
    document.querySelectorAll(".chip-fuel").forEach(el => {
      const code = el.getAttribute("data-fuel");
      if (code === this.activeFuelFilter) {
        el.classList.add("bg-primary", "text-white", "border-primary");
        el.classList.remove("bg-surface-container-low", "text-on-surface-variant");
      } else {
        el.classList.remove("bg-primary", "text-white", "border-primary");
        el.classList.add("bg-surface-container-low", "text-on-surface-variant");
      }
    });

    document.querySelectorAll(".chip-radius").forEach(el => {
      const r = parseFloat(el.getAttribute("data-radius"));
      if (r === this.activeRadiusFilter) {
        el.classList.add("bg-primary", "text-white", "border-primary");
        el.classList.remove("bg-surface-container-low", "text-on-surface-variant");
      } else {
        el.classList.remove("bg-primary", "text-white", "border-primary");
        el.classList.add("bg-surface-container-low", "text-on-surface-variant");
      }
    });
  }

  resetFilters() {
    this.activeFuelFilter = null;
    this.activeServiceFilter = null;
    this.activeRadiusFilter = null;
    this.searchQuery = "";
    this.amenityIds = [];
    this.syncAmenityControls();
    const input = document.getElementById("station-search-input");
    if (input) input.value = "";
    this.updateFilterChips();
    this.fetchAndRenderStations();
  }

  updateStationCount(count) {
    const el = document.getElementById("station-count-badge");
    if (el) el.textContent = `${count} trạm`;
  }

  discoveryFilters() {
    return { amenity_ids: [...this.amenityIds], amenity_match: this.amenityMatch,
      fuel_type: this.activeFuelFilter, search: this.searchQuery || null,
      service_name: this.activeServiceFilter };
  }

  navigationUrl() {
    const params = new URLSearchParams({tx_ma: this.selectedStation?.tx_ma || '',
      amenity_match: this.amenityMatch, radius_km: this.activeRadiusFilter || 10,
      exclude: this.excludeStations.join(',')});
    this.amenityIds.forEach(id => params.append('amenity_ids', id));
    if (this.activeFuelFilter) params.set('fuel_type', this.activeFuelFilter);
    if (this.searchQuery) params.set('search', this.searchQuery);
    return `/ChiDuong.html?${params}`;
  }

  syncAmenityControls() {
    const count = document.getElementById('amenity-count');
    if (count) count.textContent = this.amenityIds.length;
    document.querySelectorAll('#amenity-options input').forEach(input => {
      input.checked = this.amenityIds.includes(input.value);
    });
  }

  async loadAmenities() {
    const container = document.getElementById('amenity-options');
    if (!container) return;
    if (this.amenitiesLoading) return;
    this.amenitiesLoading = true;
    container.textContent = 'Đang tải tiện ích…';
    container.setAttribute('aria-busy', 'true');
    // Bind once: retry must never multiply change/clear handlers.
    const mode = document.getElementById('amenity-match');
    const clear = document.getElementById('amenity-clear');
    if (!this.amenityControlsBound) {
      if (mode) mode.addEventListener('change', () => {this.amenityMatch = mode.value; this.fetchAndRenderStations();});
      if (clear) clear.addEventListener('click', () => {
        this.amenityIds = []; this.syncAmenityControls(); this.fetchAndRenderStations();
      });
      this.amenityControlsBound = true;
    }
    if (mode) mode.value = this.amenityMatch;
    this.syncAmenityControls();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.amenityTimeoutMs || 8000);
    try {
      const response = await fetch('/api/services', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const services = await response.json();
      if (!Array.isArray(services) || services.some(service => !service ||
          typeof service.dv_ma !== 'string' || service.dv_ma.length !== 8 ||
          typeof service.dv_ten !== 'string' || !service.dv_ten.trim()) ||
          new Set(services.map(service => service.dv_ma)).size !== services.length) {
        throw new Error('Định dạng danh mục không hợp lệ');
      }
      container.replaceChildren();
      for (const service of services) {
        const label = document.createElement('label');
        label.className = 'flex items-center gap-2';
        const input = document.createElement('input');
        input.type = 'checkbox'; input.value = service.dv_ma;
        input.addEventListener('change', () => {
          this.amenityIds = input.checked ? [...new Set([...this.amenityIds, input.value])] : this.amenityIds.filter(id => id !== input.value);
          this.syncAmenityControls(); this.fetchAndRenderStations();
        });
        label.append(input, document.createTextNode(service.dv_ten)); container.append(label);
      }
      if (!services.length) container.textContent = 'Chưa có tiện ích trong danh mục.';
      this.syncAmenityControls();
    } catch (error) {
      console.warn('Không thể tải danh mục tiện ích:', controller.signal.aborted ? 'timeout' : error.message);
      container.replaceChildren();
      const message = document.createElement('p');
      message.textContent = controller.signal.aborted ? 'Tải tiện ích quá thời gian. Vui lòng thử lại.' :
        `Không thể tải danh mục tiện ích (${error.message}). Vui lòng thử lại.`;
      const retry = document.createElement('button');
      retry.type = 'button'; retry.textContent = 'Thử lại'; retry.className = 'text-primary underline p-2';
      retry.addEventListener('click', () => this.loadAmenities());
      container.append(message, retry);
    } finally {
      clearTimeout(timeout); this.amenitiesLoading = false;
      container.setAttribute('aria-busy', 'false');
    }
  }

  showToast(message) {
    let toast = document.getElementById("petro-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "petro-toast";
      toast.className = "fixed bottom-6 right-6 z-[2000] bg-gray-900/90 text-white px-4 py-2.5 rounded-xl shadow-2xl text-xs font-medium backdrop-blur-md transition-all duration-300 pointer-events-none transform translate-y-4 opacity-0";
      document.body.appendChild(toast);
    }

    toast.textContent = message;
    toast.classList.remove("translate-y-4", "opacity-0");
    toast.classList.add("translate-y-0", "opacity-100");

    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      toast.classList.remove("translate-y-0", "opacity-100");
      toast.classList.add("translate-y-4", "opacity-0");
    }, 3500);
  }
}

// Khởi chạy khi DOM sẵn sàng
document.addEventListener("DOMContentLoaded", () => {
  window.petroMap = new PetroMapService();
});
