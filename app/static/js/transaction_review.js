/* Read-only eligibility before prompting; only the explicit Submit posts a review. */
(function(root) {
  'use strict';
  const mounted = new Map();
  async function mount(invoiceId, host, {auto = false} = {}) {
    if (!invoiceId || !host || mounted.has(invoiceId)) return;
    mounted.set(invoiceId, true);
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn-secondary my-3';
    button.textContent = 'Đánh giá giao dịch';
    const info = document.createElement('p'); info.setAttribute('role', 'status'); host.append(info);
    const endpoint = `/api/transactions/${encodeURIComponent(invoiceId)}/review`;
    const key = `petro.review.prompted.v1.${invoiceId}`;
    async function eligibility() {
      const response = await fetch(endpoint, {cache:'no-store', credentials:'same-origin'});
      if (!response.ok) throw new Error('Chưa thể kiểm tra quyền đánh giá. Vui lòng thử lại.');
      return response.json();
    }
    let state;
    try { state = await eligibility(); }
    catch (_) { info.textContent = 'Chưa thể tải đánh giá. Bạn có thể mở lại giao dịch từ Lịch sử.'; return; }
    if (!state.enabled || !state.eligible) return;
    host.append(button);
    if (state.reviewed) { button.textContent = 'Đã đánh giá'; button.disabled = true; return; }
    async function open() {
      if (button.disabled || document.getElementById('transaction-review-dialog')) return;
      button.disabled = true;
      try {
        state = await eligibility();
        if (!state.enabled || !state.eligible) { info.textContent = state.reason || 'Giao dịch chưa đủ điều kiện đánh giá.'; return; }
        if (state.reviewed) { button.textContent = 'Đã đánh giá'; return; }
        const dialog = document.createElement('dialog'); dialog.id = 'transaction-review-dialog';
        dialog.setAttribute('aria-labelledby', 'review-dialog-title');
        dialog.style.cssText = 'box-sizing:border-box;width:min(92vw,28rem);max-height:90dvh;overflow:auto;border-radius:16px;padding:24px;';
        dialog.innerHTML = `<form><h2 id="review-dialog-title" class="text-xl font-bold">Đánh giá trải nghiệm tại trạm</h2>
          <p>Biên lai vẫn được lưu trong Lịch sử giao dịch.</p>
          <fieldset class="my-4" style="min-width:0"><legend>Chọn từ 1 đến 5 sao (bắt buộc)</legend><div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px">
            ${[1,2,3,4,5].map(n=>`<label style="box-sizing:border-box;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 0;min-height:44px"><input type="radio" name="stars" value="${n}" required aria-label="${n} sao">${n} ★</label>`).join('')}
          </div></fieldset><label for="review-comment">Nhận xét (không bắt buộc, tối đa 500 ký tự)</label>
          <textarea id="review-comment" name="comment" maxlength="500" rows="3" style="box-sizing:border-box;width:100%;border:1px solid #777;border-radius:6px;padding:8px"></textarea>
          <p role="alert" data-review-error></p><div class="flex gap-3 mt-4">
          <button type="button" class="btn-secondary" data-review-skip>Để sau</button>
          <button type="submit" class="btn-primary">Gửi đánh giá</button></div></form>`;
        document.body.append(dialog);
        let busy = false; const form = dialog.querySelector('form'), send = form.querySelector('[type=submit]');
        const skip = form.querySelector('[data-review-skip]'), error = form.querySelector('[data-review-error]');
        function close() { dialog.close(); dialog.remove(); button.disabled = state.reviewed === true; button.focus(); }
        skip.addEventListener('click', close);
        dialog.addEventListener('cancel', event => {event.preventDefault(); if (!busy) close();});
        form.addEventListener('submit', async event => {
          event.preventDefault(); if (busy || !form.reportValidity()) return;
          busy = true; send.disabled = true; skip.disabled = true; error.textContent = '';
          try {
            const payload = {stars:Number(form.elements.stars.value), comment:form.elements.comment.value.trim()};
            const response = await fetch(endpoint, {method:'POST', credentials:'same-origin',
              headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
            if (!response.ok) {
              // A lost success response/different-tab submission may already have
              // committed. Recheck server state before inviting another submit.
              const latest = await eligibility();
              if (!latest.reviewed) throw new Error('Chưa lưu được đánh giá. Vui lòng thử lại.');
              state.reviewed = true; button.textContent = 'Đã đánh giá';
              info.textContent = 'Giao dịch đã có đánh giá; nội dung đã lưu được giữ nguyên.';
              close(); return;
            }
            state.reviewed = true; button.textContent = 'Đã đánh giá';
            info.textContent = 'Cảm ơn bạn đã đánh giá.'; close();
          } catch (_) { error.textContent = 'Chưa lưu được đánh giá. Vui lòng thử lại; hệ thống sẽ tránh ghi trùng.'; }
          finally {busy = false; send.disabled = false; skip.disabled = false;}
        });
        dialog.showModal(); dialog.querySelector('input').focus();
      } catch (_) { info.textContent = 'Chưa thể kiểm tra quyền đánh giá. Bấm Đánh giá giao dịch để thử lại.'; }
      finally {button.disabled = state.reviewed === true;}
    }
    button.addEventListener('click', open);
    let prompted = true;
    try { prompted = localStorage.getItem(key) === '1'; if (!prompted) localStorage.setItem(key, '1'); }
    catch (_) { /* No durable browser storage: manual review only, no refresh loop. */ }
    if (auto && !prompted) await open();
  }
  root.PetroTransactionReview = {mount};
})(window);
