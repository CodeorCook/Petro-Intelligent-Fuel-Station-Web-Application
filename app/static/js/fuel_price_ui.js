/* Presentation-only synchronization timestamps, shared by both price views. */
(function(root) {
  'use strict';
  function formatSyncStatus(latest) {
    const stamp = value => new Date(value).toLocaleString('vi-VN', {timeZone: 'Asia/Ho_Chi_Minh'});
    const parts = [];
    if (latest.is_cached) parts.push('Kết quả nguồn trực tuyến từ bộ nhớ đệm');
    if (latest.fetched_at) parts.push(`Thu thập nguồn: ${stamp(latest.fetched_at)}`);
    if (latest.last_attempt_at) parts.push(`Lần thử đồng bộ (tiến trình này): ${stamp(latest.last_attempt_at)}`);
    if (latest.last_success_at) parts.push(`Xác minh nguồn thành công: ${stamp(latest.last_success_at)}`);
    if (latest.sources_attempted?.length) parts.push('Nguồn đã kiểm tra: ' + latest.sources_attempted.map(a =>
      `${a.source === 'petrolimex' ? 'Petrolimex Vùng 2' : a.source === 'pvoil' ? 'PVOIL' : a.source}: ${a.status === 'verified' ? a.effective_date : a.detail}`).join('; '));
    if (latest.sync_error) parts.push(`Lỗi đồng bộ: ${latest.sync_error}`);
    return parts.join(' · ') || 'Mốc đồng bộ chưa khả dụng trong tiến trình này; xem nhật ký tác vụ.';
  }
  root.PetroFuelPricesUI = {formatSyncStatus};
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PetroFuelPricesUI;
})(typeof window !== 'undefined' ? window : globalThis);
