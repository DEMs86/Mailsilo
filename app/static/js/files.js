let filesState = {
  ext: null,          // null = All, "" = files without extension
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

function filesTableHeadHtml() {
  const head = (key, label, cls = "") => {
    const active = filesState.sortBy === key;
    const arrow = active ? (filesState.sortOrder === "asc" ? "▲" : "▼") : "";
    const arrowHtml = arrow ? ` <span class="files-sort-arrow">${arrow}</span>` : "";
    return `<th class="${cls}${active ? " active" : ""}" data-action="files-sort" data-sort="${key}" title="Sort by ${label}">${label}${arrowHtml}</th>`;
  };
  return `<thead><tr>
    ${head("filename", "Name")}
    ${head("ext", "Extension")}
    ${head("size", "Size", "num")}
    <th class="col-actions"></th>
  </tr></thead>`;
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

  const data = await api(`/api/files?${params.toString()}`);

  const title = $("#filesPanelTitle");
  const count = $("#filesPanelCount");
  if (title) title.textContent = filesState.ext === null ? "All files" : fileExtLabel(filesState.ext);
  if (count) count.textContent = `${data.total} file(s)`;

  if (!data.items.length) {
    const msg = filesState.ext === null
      ? "No files yet. Fetch or import an archive first."
      : "No files with this extension.";
    wrap.innerHTML = `<div class="empty-state">${msg}</div>`;
    return;
  }

  wrap.innerHTML = `<table class="files-table">
    <colgroup><col><col class="col-ext"><col class="col-size"><col class="col-actions"></colgroup>
    ${filesTableHeadHtml()}
    <tbody>${data.items.map(fileRowHtml).join("")}</tbody>
  </table>` + pagination(data.total, data.page, data.per_page, "files-page");
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

async function openFileThread(emailId) {
  state.view = "thread";
  state.folder = null;
  state.selectedEmailId = null;
  await renderThread(emailId);
}
