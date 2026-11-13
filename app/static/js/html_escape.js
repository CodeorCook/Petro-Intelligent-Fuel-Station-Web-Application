// User-authored station labels must remain text inside existing HTML templates.
function petroEscapeHtml(value) {
  const entities={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
  return String(value ?? "").replace(/[&<>"']/g,character=>entities[character]);
}
