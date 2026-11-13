/* Presentation only. Input remains OSRM minutes/km; never change routing data. */
(function(root) {
  'use strict';
  const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  function duration(minutes) {
    if (!valid(minutes)) return 'Chưa có thời gian di chuyển';
    const total = Math.round(minutes);
    if (total === 0) return minutes === 0 ? '0 phút' : 'Dưới 1 phút';
    if (total < 60) return `Khoảng ${total} phút`;
    return `${Math.floor(total / 60)} giờ${total % 60 ? ` ${total % 60} phút` : ''}`;
  }
  function km(value, digits = 1) {
    return valid(value) ? `${value.toLocaleString('vi-VN', {minimumFractionDigits: digits, maximumFractionDigits: digits})} km` : null;
  }
  function straight(value) { return km(value, 2) ? `Cách bạn khoảng ${km(value, 2)} (đường thẳng)` : 'Chưa có khoảng cách đường thẳng'; }
  function isRoad(route) { return route?.is_fallback !== true && /^osrm$/i.test(route?.routing_source || ''); }
  function road(route) { return isRoad(route) && km(route.distance_km) ? `Quãng đường di chuyển: ${km(route.distance_km)}` : 'Chưa có quãng đường di chuyển'; }
  function eta(route) { return isRoad(route) ? duration(route.duration_minutes) : 'Chưa có thời gian di chuyển'; }
  const api = {duration, km, straight, isRoad, road, eta};
  root.PetroTravelFormat = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
