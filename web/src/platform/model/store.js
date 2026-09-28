// Projects created in the new-project flow live in the viewer's browser for now.

export function loadSaved() {
  try { return JSON.parse(localStorage.getItem('te.projects') || '[]') } catch { return [] }
}
export function saveProject(p) {
  try { localStorage.setItem('te.projects', JSON.stringify([...loadSaved().filter((x) => x.project_id !== p.project_id), p])) } catch { /* storage unavailable */ }
}
