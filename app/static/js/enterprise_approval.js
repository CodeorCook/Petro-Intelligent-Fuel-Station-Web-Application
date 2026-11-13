/* Enterprise approval only. All user content is rendered as text, never HTML. */
(() => {
  const page = document.querySelector("[data-approval-page]");
  if (!page) return;
  const message = document.getElementById("approval-message");
  const labels = {CHO_DUYET:"Chờ duyệt", CAN_BO_SUNG:"Cần bổ sung", TU_CHOI:"Từ chối",
    DA_DUYET:"Đã duyệt", CHUA_HOAN_THIEN:"Chưa hoàn thiện", TAM_KHOA:"Tạm khóa"};
  let busy = false, staging = [], selected = null, offset = 0;
  const notify = text => { message.textContent = text; };
  async function api(url, options = {}) {
    const response = await fetch(url, {credentials:"same-origin", ...options});
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) throw new Error("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
      throw new Error(typeof data.detail === "string" ? data.detail :
        (Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(". ") : "Không thể xử lý hồ sơ lúc này."));
    }
    return data;
  }
  const json = (method, body) => ({method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  async function action(operation) {
    if (busy) return;
    busy = true;
    page.setAttribute("aria-busy", "true");
    try { await operation(); } catch (error) { notify(error.message || "Không thể kết nối máy chủ."); }
    finally { busy = false; page.removeAttribute("aria-busy"); }
  }
  function documents(container, attachments) {
    container.replaceChildren();
    for (const attachment of attachments) {
      const item = document.createElement("li"), link = document.createElement("a");
      link.className = "text-primary underline";
      link.textContent = `${attachment.tmc_ten} (${Math.ceil((attachment.tmc_kich_thuoc || 0)/1024)} KB)`;
      link.href = `/api/enterprise-approval/evidence/${encodeURIComponent(attachment.tmc_ma)}`;
      link.setAttribute("download", "");
      item.append(link); container.append(item);
    }
  }
  async function refreshEnterprise() {
    const [status, profile, uploads, history] = await Promise.all([
      api("/api/enterprise/status"), api("/api/enterprise/profile"),
      api("/api/enterprise/evidence/staging"), api("/api/enterprise/approvals")
    ]);
    staging = uploads;
    document.getElementById("enterprise-approval-status").textContent = labels[status.enterprise_status] || status.enterprise_status;
    const form = document.getElementById("enterprise-profile-form");
    for (const input of form.querySelectorAll("input")) input.value = profile?.[input.name] || "";
    const editable = !["DA_DUYET", "TAM_KHOA"].includes(status.enterprise_status);
    form.querySelectorAll("input,button").forEach(input => input.disabled = !editable);
    document.getElementById("upload-enterprise-evidence").disabled = !editable;
    document.getElementById("enterprise-evidence-file").disabled = !editable;
    document.getElementById("submit-enterprise-approval").disabled = !status.can_submit;
    document.getElementById("approved-stations-link").classList.toggle("hidden", status.enterprise_status !== "DA_DUYET");
    const list = document.getElementById("enterprise-staging-list"); list.replaceChildren();
    for (const file of staging) {
      const row = document.createElement("li"), remove = document.createElement("button");
      row.append(document.createTextNode(file.name + " "));
      remove.className = "text-primary underline"; remove.textContent = "Xóa tệp nháp";
      remove.addEventListener("click", () => action(async () => {
        await api(`/api/enterprise/evidence/staging/${file.token}`, {method:"DELETE"});
        await refreshEnterprise(); notify("Đã xóa minh chứng nháp.");
      }));
      row.append(remove); list.append(row);
    }
    const historyBox = document.getElementById("enterprise-approval-history"); historyBox.replaceChildren();
    if (!history.length) historyBox.textContent = "Chưa có lần nộp hồ sơ.";
    for (const request of history) {
      const card = document.createElement("article"), title = document.createElement("h3"), feedback = document.createElement("p"), files = document.createElement("ul");
      card.className = "border rounded-lg p-md";
      title.textContent = `Lần ${request.ycdn_lan_gui}: ${labels[request.ycdn_trangthai]} — ${new Date(request.ycdn_ngaygui).toLocaleString("vi-VN")}`;
      feedback.textContent = request.ycdn_lydo ? `Phản hồi: ${request.ycdn_lydo}` : "Chưa có phản hồi.";
      documents(files, request.tep_minh_chung); card.append(title, feedback, files); historyBox.append(card);
    }
  }
  async function saveDraft() {
    const form = document.getElementById("enterprise-profile-form");
    if (!form.reportValidity()) throw new Error("Vui lòng kiểm tra thông tin hồ sơ.");
    const values = Object.fromEntries([...form.querySelectorAll("input")].map(input => [input.name, input.value.trim() || null]));
    return api("/api/enterprise/profile", json("PUT", values));
  }
  if (page.dataset.approvalPage === "enterprise") {
    document.getElementById("enterprise-profile-form").addEventListener("submit", event => {
      event.preventDefault(); action(async () => { await saveDraft(); notify("Đã lưu bản nháp."); await refreshEnterprise(); });
    });
    document.getElementById("upload-enterprise-evidence").addEventListener("click", () => action(async () => {
      const file = document.getElementById("enterprise-evidence-file").files[0];
      if (!file || file.size > 5*1024*1024) throw new Error("Chọn tệp minh chứng không quá 5 MB.");
      const body = new FormData(); body.append("file", file);
      await api("/api/enterprise/evidence/staging", {method:"POST", body});
      document.getElementById("enterprise-evidence-file").value = "";
      await refreshEnterprise(); notify("Minh chứng đã lưu riêng tư. Hãy gửi xét duyệt để gắn tệp với lần nộp.");
    }));
    document.getElementById("submit-enterprise-approval").addEventListener("click", () => action(async () => {
      if (!staging.length) throw new Error("Cần tải ít nhất một tài liệu pháp lý.");
      if (!window.confirm("Gửi bản chụp hồ sơ và các minh chứng này để xét duyệt?")) return;
      await saveDraft();
      await api("/api/enterprise/approvals", json("POST", {evidence_tokens:staging.map(file => file.token)}));
      await refreshEnterprise(); notify("Đã gửi hồ sơ. Minh chứng và bản chụp của lần nộp được giữ nguyên.");
    }));
    action(refreshEnterprise);
  } else {
    async function showRequest(id) {
      selected = await api(`/api/admin/enterprise-approvals/${encodeURIComponent(id)}`);
      document.getElementById("admin-approval-detail").classList.remove("hidden");
      document.getElementById("admin-approval-title").textContent = `${selected.ycdn_dulieu.hsdn_tenphaply} — Lần ${selected.ycdn_lan_gui}`;
      document.getElementById("admin-approval-snapshot").textContent = JSON.stringify(selected.ycdn_dulieu, null, 2);
      document.getElementById("admin-approval-feedback").textContent = selected.ycdn_lydo || labels[selected.ycdn_trangthai];
      document.getElementById("admin-approval-reason").value = "";
      documents(document.getElementById("admin-approval-evidence"), selected.tep_minh_chung);
      page.querySelectorAll(".approval-decision").forEach(button => button.disabled = selected.ycdn_trangthai !== "CHO_DUYET");
    }
    async function refreshAdmin() {
      const state = document.getElementById("admin-approval-filter").value;
      const rows = await api(`/api/admin/enterprise-approvals?status=${encodeURIComponent(state)}&limit=20&offset=${offset}`);
      const box = document.getElementById("admin-enterprise-approval-list"); box.replaceChildren();
      if (!rows.length) box.textContent = "Không có hồ sơ trong danh sách này.";
      for (const row of rows) {
        const button = document.createElement("button"); button.className = "btn-secondary block w-full";
        button.textContent = `${row.ycdn_dulieu.hsdn_tenphaply} — Lần ${row.ycdn_lan_gui} — ${labels[row.ycdn_trangthai]}`;
        button.addEventListener("click", () => action(() => showRequest(row.ycdn_ma))); box.append(button);
      }
      document.getElementById("approval-previous-page").disabled = offset === 0;
      document.getElementById("approval-next-page").disabled = rows.length < 20;
    }
    document.getElementById("admin-approval-filter").addEventListener("change", () => action(async () => { offset = 0; selected = null; document.getElementById("admin-approval-detail").classList.add("hidden"); await refreshAdmin(); }));
    for (const [id, direction] of [["approval-previous-page", -1], ["approval-next-page", 1]]) {
      document.getElementById(id).addEventListener("click", () => action(async () => { offset = Math.max(0, offset + direction*20); await refreshAdmin(); }));
    }
    page.querySelectorAll(".approval-decision").forEach(button => button.addEventListener("click", () => action(async () => {
      if (!selected) return;
      const decision = button.dataset.decision, reason = document.getElementById("admin-approval-reason").value.trim();
      if (decision !== "DA_DUYET" && !reason) throw new Error("Cần nhập lý do từ chối hoặc yêu cầu bổ sung.");
      if (!window.confirm(`Xác nhận quyết định: ${labels[decision]}?`)) return;
      const id = selected.ycdn_ma;
      await api(`/api/admin/enterprise-approvals/${encodeURIComponent(id)}/decision`, json("POST", {decision, reason:reason || null}));
      await showRequest(id); await refreshAdmin(); notify("Đã lưu quyết định xét duyệt.");
    })));
    action(refreshAdmin);
  }
})();
