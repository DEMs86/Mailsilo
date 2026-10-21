let filesState = {
  ext: null,          // null = All, "" = files without extension
  filters: { filename: "", ext: "", size: "" },  // per-column masks, '*' matches anything
  filterCol: null,    // column whose filter input is currently open
  sortBy: "filename",
  sortOrder: "asc",
  page: 1,
  perPage: 100,
};

/* ---------- view ---------- */

async function renderFiles() {
  setSplitView(true);
  showFilesPanel(true);
  await renderFileExtensions();
  await renderFilesTable();
}

function showFilesPanel(show) {
  const panel = $("#filesPanel");
  if (!panel) return;
  if (!show) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "flex";
  const empty = $("#detailEmpty");
  const content = $("#detailContent");
  if (empty) empty.style.display = "none";
  if (content) content.style.display = "none";
  const dp = $("#detailPanel");
  if (dp) dp.classList.remove("show-mobile");
}

function hideFilesPanel() {
  showFilesPanel(false);
}

/* ---------- left panel: file types ---------- */

function fileExtLabel(ext) {
  return ext ? ext.toUpperCase() : "(no extension)";
}

function fileExtRowHtml(ext, label, count) {
  const selected = filesState.ext === ext;
  const dataExt = ext === null ? "*" : ext;
  return `<button type="button" class="files-filter-item${selected ? " active" : ""}" data-action="files-ext" data-ext="${escAttr(dataExt)}">
    <span class="files-filter-name">${esc(label)}</span>
    <span class="files-filter-count">${count}</span>
  </button>`;
}

async function renderFileExtensions() {
  const data = await api("/api/files/extensions");
  setListTitle("Files", `${data.total} file(s)`);

  let html = `<div class="files-filter">`;
  html += fileExtRowHtml(null, "All", data.total);
  for (const item of data.items) {
    html += fileExtRowHtml(item.ext, fileExtLabel(item.ext), item.count);
  }
  html += `</div>`;
  $("#listPanelBody").innerHTML = html;
}

function filesSelectExt(raw) {
  filesState.ext = raw === "*" ? null : raw;
  filesState.page = 1;
  renderFileExtensions().catch((e) => toast(`Error: ${e.message}`));
  renderFilesTable().catch((e) => toast(`Error: ${e.message}`));
}

/* ---------- right panel: table ---------- */

function filesSort(key) {
  if (filesState.sortBy === key) {
    filesState.sortOrder = filesState.sortOrder === "asc" ? "desc" : "asc";
  } else {
    filesState.sortBy = key;
    filesState.sortOrder = key === "size" ? "desc" : "asc";
  }
  filesState.page = 1;
  renderFilesTable().catch((e) => toast(`Error: ${e.message}`));
}

const FILES_COLUMNS = [
  { key: "filename", label: "Name", cls: "", placeholder: "name, * = any chars" },
  { key: "ext", label: "Extension", cls: "", placeholder: "ext, e.g. do*" },
  { key: "size", label: "Size", cls: "num", placeholder: "bytes, e.g. 284*" },
];

function filesTableHeadHtml() {
  const cell = (col) => {
    const sorted = filesState.sortBy === col.key;
    const arrow = sorted ? (filesState.sortOrder === "asc" ? "▲" : "▼") : "";
    const arrowHtml = arrow ? ` <span class="files-sort-arrow">${arrow}</span>` : "";
    const filter = filesState.filters[col.key] || "";
    const filterTitle = filter
      ? `Filter: ${filter} (click to change)`
      : "Filter this column";
    return `<th class="${col.cls}${sorted ? " active" : ""}">
      <span class="files-th-label" data-action="files-sort" data-sort="${col.key}" title="Sort by ${col.label}">${col.label}${arrowHtml}</span>
      <button type="button" class="files-filter-btn${filter ? " on" : ""}" data-action="files-filter-open" data-col="${col.key}" title="${escAttr(filterTitle)}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
      </button>
    </th>`;
  };

  const filterRow = filesState.filterCol
    ? `<tr class="files-filter-row">${FILES_COLUMNS.map((col) => (col.key === filesState.filterCol
        ? `<th class="${col.cls}"><input type="text" class="files-filter-input" id="filesFilterInput" data-col="${col.key}" value="${escAttr(filesState.filters[col.key] || "")}" placeholder="${escAttr(col.placeholder)}" onkeydown="filesFilterKeydown(event)"></th>`
        : `<th class="${col.cls}"></th>`)).join("")}<th class="col-actions"></th></tr>`
    : "";

  return `<thead><tr>
    ${FILES_COLUMNS.map(cell).join("")}
    <th class="col-actions"></th>
  </tr>${filterRow}</thead>`;
}

/* ---------- per-column filters ---------- */

function filesFilterOpen(col) {
  filesState.filterCol = filesState.filterCol === col ? null : col;
  renderFilesTable().catch((e) => toast(`Error: ${e.message}`));
}

function filesFilterApply(col, value) {
  filesState.filters[col] = (value || "").trim();
  filesState.filterCol = null;
  filesState.page = 1;
  renderFilesTable().catch((e) => toast(`Error: ${e.message}`));
}

function filesFilterKeydown(event) {
  const col = event.target.dataset.col;
  if (!col) return;
  if (event.key === "Enter") {
    event.preventDefault();
    filesFilterApply(col, event.target.value);
  } else if (event.key === "Escape") {
    event.preventDefault();
    event.target.value = "";
    filesFilterApply(col, "");
  }
}

function fileRowHtml(f) {
  const name = f.filename || "(unnamed)";
  const href = f.email_id
    ? `/api/emails/${f.email_id}/attachment/${f.id}?token=${encodeURIComponent(AUTH_TOKEN)}`
    : "";
  const nameHtml = href
    ? `<a href="${escAttr(href)}" target="_blank" download="${escAttr(name)}">${esc(name)}</a>`
    : esc(name);

  const hasEmail = !!f.email_id;
  const openEmail = hasEmail
    ? `<button type="button" class="icon-btn" data-action="file-open-email" data-email-id="${f.email_id}" data-folder="${escAttr(f.folder)}" data-account-id="${f.account_id ?? ""}" data-account-email="${escAttr(f.account_email)}" title="Go to email">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
      </button>`
    : "";
  const openThread = hasEmail
    ? `<button type="button" class="icon-btn" data-action="file-open-thread" data-email-id="${f.email_id}" title="Show all emails in conversation">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      </button>`
    : "";

  return `<tr>
    <td class="file-name" title="${escAttr(f.subject || name)}">${nameHtml}</td>
    <td class="file-ext">${esc(f.ext || "—")}</td>
    <td class="file-size num">${formatBytes(f.size)}</td>
    <td class="file-actions">${openEmail}${openThread}</td>
  </tr>`;
}

async function renderFilesTable() {
  const wrap = $("#filesTableWrap");
  if (!wrap) return;

  const params = new URLSearchParams({
    page: String(filesState.page),
    per_page: String(filesState.perPage),
    sort_by: filesState.sortBy,
    sort_order: filesState.sortOrder,
  });
  if (filesState.ext !== null) params.set("ext", filesState.ext);
  if (filesState.filters.filename) params.set("name", filesState.filters.filename);
  if (filesState.filters.ext) params.set("ext_mask", filesState.filters.ext);
  if (filesState.filters.size) params.set("size", filesState.filters.size);

  const data = await api(`/api/files?${params.toString()}`);

  const title = $("#filesPanelTitle");
  const count = $("#filesPanelCount");
  if (title) title.textContent = filesState.ext === null ? "All files" : fileExtLabel(filesState.ext);
  if (count) count.textContent = `${data.total} file(s)`;

  if (!data.items.length) {
    const msg = filesState.ext === null
      ? "No files match the current filters."
      : "No files with this extension and the current filters.";
    wrap.innerHTML = `<table class="files-table">
      <colgroup><col><col class="col-ext"><col class="col-size"><col class="col-actions"></colgroup>
      ${filesTableHeadHtml()}
      <tbody><tr><td colspan="4"><div class="empty-state">${msg}</div></td></tr></tbody>
    </table>`;
    focusFilesFilterInput();
    return;
  }

  wrap.innerHTML = `<table class="files-table">
    <colgroup><col><col class="col-ext"><col class="col-size"><col class="col-actions"></colgroup>
    ${filesTableHeadHtml()}
    <tbody>${data.items.map(fileRowHtml).join("")}</tbody>
  </table>` + pagination(data.total, data.page, data.per_page, "files-page");

  focusFilesFilterInput();
}

function focusFilesFilterInput() {
  if (!filesState.filterCol) return;
  const input = $("#filesFilterInput");
  if (!input) return;
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

/* ---------- row actions ---------- */

async function openFileEmail(ds) {
  const emailId = parseInt(ds.emailId);
  const accountId = parseInt(ds.accountId);
  if (ds.folder && Number.isFinite(accountId)) {
    state.view = "folder";
    state.folder = {
      accountEmail: ds.accountEmail || "",
      folderName: ds.folder,
      accountId,
      page: 1,
    };
    state.selectedEmailId = emailId;
    await renderFolder();
  }
  await showEmail(emailId);
}
