// Drag to reorder (mouse and touch) by a ".handle" inside rows marked with data-id.
// onmove(id, index) is called while dragging (the caller reorders its own list), onend() when dropped.
export function sortable(node, params) {
  let opts = params;
  let id = null;
  function down(e) {
    const h = e.target.closest('.handle');
    if (!h || !node.contains(h)) return;
    id = Number(h.closest('[data-id]').dataset.id);
    e.preventDefault();
    node.setPointerCapture(e.pointerId);
    node.classList.add('sorting');
  }
  function move(e) {
    if (id === null) return;
    const rows = [...node.querySelectorAll('[data-id]')].filter((r) => Number(r.dataset.id) !== id);
    const index = rows.filter((r) => { const b = r.getBoundingClientRect(); return b.top + b.height / 2 < e.clientY; }).length;
    opts.onmove(id, index);
  }
  function up() {
    if (id === null) return;
    id = null;
    node.classList.remove('sorting');
    opts.onend();
  }
  node.addEventListener('pointerdown', down);
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', up);
  return {
    update(p) { opts = p; },
    destroy() {
      node.removeEventListener('pointerdown', down);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', up);
      node.removeEventListener('pointercancel', up);
    },
  };
}
