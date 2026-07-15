let pendingFragmentConversionId = "";
let fragmentEditorSyncedElement = null;
let fragmentEditorScrollUnlockFrame = 0;

const CONTENT_KIND_LABELS = {
  character: "人物",
  relationship: "人物关系",
  entry: "设定",
  fragment: "灵感碎片",
};

const CONTENT_MANAGER_FEATURE = "content-management-v3";

function contentManagerWritable() {
  return Boolean(
    refactorCapability?.writable
    && refactorCapability?.features?.includes(CONTENT_MANAGER_FEATURE)
  );
}

function editorListValue(values) {
  return (values || []).join("，");
}

function editorFactsValue(facts) {
  return (facts || []).map((fact) => `${fact.label}：${fact.value}`).join("\n");
}

function editorFactsObject(value) {
  const result = {};
  String(value || "").split(/\n/).forEach((line) => {
    const match = line.match(/^\s*([^:：]+)[:：]\s*(.+?)\s*$/);
    if (match) result[match[1].trim()] = match[2].trim();
  });
  return result;
}

function editorMultiOptions(records, selected, label) {
  const selectedValues = new Set((selected || []).map(String));
  return records.map((record) => `
    <option value="${escapeHtml(record.id)}" ${selectedValues.has(String(record.id)) ? "selected" : ""}>
      ${escapeHtml(label(record))}
    </option>
  `).join("");
}

function ensureContentEditorDialog() {
  let dialog = document.querySelector("#contentEditorDialog");
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.id = "contentEditorDialog";
  dialog.className = "content-editor-dialog";
  dialog.innerHTML = `
    <form class="content-editor-form" id="contentEditorForm">
      <header>
        <div><p>内容管理</p><h3 id="contentEditorTitle">编辑档案</h3></div>
        <div class="content-editor-head-actions">
          <button class="content-editor-fullscreen icon-action is-hidden" id="contentEditorFullscreen" type="button" aria-label="进入沉浸写作" title="进入沉浸写作">${uiIcon("maximize")}</button>
          <button class="content-editor-close icon-action" id="contentEditorClose" type="button" aria-label="关闭" title="关闭">${uiIcon("close")}</button>
        </div>
      </header>
      <div class="content-editor-fields" id="contentEditorFields"></div>
      <footer>
        <p id="contentEditorStatus" aria-live="polite"></p>
        <div>
          <button class="content-editor-delete icon-action is-danger is-hidden" id="contentEditorDelete" type="button" aria-label="删除" title="删除">${uiIcon("trash")}</button>
          <button class="icon-action" id="contentEditorCancel" type="button" aria-label="取消" title="取消">${uiIcon("close")}</button>
          <button class="content-editor-submit icon-action is-primary" id="contentEditorSubmit" type="submit" aria-label="保存" title="保存">${uiIcon("save")}</button>
        </div>
      </footer>
    </form>
  `;
  document.body.append(dialog);
  dialog.querySelector("#contentEditorClose").addEventListener("click", () => dialog.close());
  dialog.querySelector("#contentEditorCancel").addEventListener("click", () => dialog.close());
  dialog.querySelector("#contentEditorFullscreen").addEventListener("click", () => {
    setFragmentWriterImmersive(dialog, !dialog.classList.contains("is-immersive"));
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener("cancel", (event) => {
    if (!dialog.classList.contains("is-immersive")) return;
    event.preventDefault();
    setFragmentWriterImmersive(dialog, false);
  });
  dialog.addEventListener("close", () => {
    dialog.classList.remove("is-immersive");
    resetFragmentEditorScrollSync();
  });
  return dialog;
}

function contentEditorField(id, label, value = "", options = {}) {
  const fieldLabel = `<span>${escapeHtml(label)}${options.note ? `<small>${escapeHtml(options.note)}</small>` : ""}</span>`;
  if (options.type === "textarea") {
    return `<label class="${options.wide ? "is-wide" : ""}">${fieldLabel}<textarea id="${id}" rows="${options.rows || 5}" ${options.required ? "required" : ""} ${options.readonly ? "readonly" : ""}>${escapeHtml(value)}</textarea></label>`;
  }
  if (options.type === "select") {
    return `<label>${fieldLabel}<select id="${id}" ${options.multiple ? "multiple" : ""} ${options.required ? "required" : ""}>${options.html || ""}</select></label>`;
  }
  return `<label class="${options.wide ? "is-wide" : ""}">${fieldLabel}<input id="${id}" type="${options.type || "text"}" value="${escapeHtml(value)}" ${options.required ? "required" : ""} ${options.readonly ? "readonly" : ""} ${options.min !== undefined ? `min="${options.min}"` : ""} ${options.max !== undefined ? `max="${options.max}"` : ""} /></label>`;
}

function contentEditorSelected(id) {
  return [...(document.querySelector(`#${id}`)?.selectedOptions || [])].map((item) => item.value);
}

function syncFragmentEditorScroll(source, target) {
  if (!source || !target || fragmentEditorSyncedElement === source) return;
  const sourceRange = Math.max(0, source.scrollHeight - source.clientHeight);
  const targetRange = Math.max(0, target.scrollHeight - target.clientHeight);
  fragmentEditorSyncedElement = target;
  target.scrollTop = (sourceRange > 0 ? source.scrollTop / sourceRange : 0) * targetRange;
  if (fragmentEditorScrollUnlockFrame) cancelAnimationFrame(fragmentEditorScrollUnlockFrame);
  fragmentEditorScrollUnlockFrame = requestAnimationFrame(() => {
    fragmentEditorSyncedElement = null;
    fragmentEditorScrollUnlockFrame = 0;
  });
}

function resetFragmentEditorScrollSync() {
  if (fragmentEditorScrollUnlockFrame) cancelAnimationFrame(fragmentEditorScrollUnlockFrame);
  fragmentEditorScrollUnlockFrame = 0;
  fragmentEditorSyncedElement = null;
}

function setFragmentWriterImmersive(dialog, immersive) {
  if (!dialog?.classList.contains("is-fragment-writer")) return;
  dialog.classList.toggle("is-immersive", immersive);
  setIconButton(
    dialog.querySelector("#contentEditorFullscreen"),
    immersive ? "minimize" : "maximize",
    immersive ? "退出沉浸写作" : "进入沉浸写作",
  );
  requestAnimationFrame(() => {
    syncFragmentEditorScroll(
      dialog.querySelector("#ceBody"),
      dialog.querySelector("#fragmentEditorPreview"),
    );
  });
}

function renderFragmentEditorPreview() {
  const preview = document.querySelector("#fragmentEditorPreview");
  if (!preview) return;
  const source = document.querySelector("#ceBody");
  const body = source?.value || "";
  preview.innerHTML = body.trim()
    ? renderMarkdownBody(body)
    : '<p class="fragment-editor-preview-empty">从左侧开始写，预览会同步显示在这里。</p>';
  syncFragmentEditorScroll(source, preview);
}

function clearCharacterRenamePreview(form) {
  delete form.dataset.renameOperationId;
  delete form.dataset.renamePreviewName;
  const preview = form.querySelector("#contentEditorRenamePreview");
  if (preview) {
    preview.innerHTML = "";
    preview.classList.add("is-hidden");
  }
  if (form.dataset.kind === "character" && form.dataset.creating !== "true") {
    setIconButton(form.querySelector("#contentEditorSubmit"), "save", "保存修改");
  }
}

function renderCharacterRenamePreview(form, result) {
  const preview = form.querySelector("#contentEditorRenamePreview");
  if (!preview) return;
  const moveItems = result.moves.map((move) => `
    <li><span>文件改名</span><del>${escapeHtml(move.from)}</del><ins>${escapeHtml(move.to)}</ins></li>
  `).join("");
  const sampleItems = result.samples.slice(0, 8).map((sample) => `
    <li><span>${escapeHtml(sample.file)} · 第 ${sample.line} 行</span><del>${escapeHtml(sample.before)}</del><ins>${escapeHtml(sample.after)}</ins></li>
  `).join("");
  const duplicateWarning = result.ambiguousName
    ? `<p class="content-editor-rename-warning">检测到同名人物（ID ${result.duplicateCharacterIds.map(escapeHtml).join("、")}）。下面按文件和行列出歧义引用；只勾选明确属于当前 ID 的内容。</p>`
    : "";
  const referenceItems = (result.referenceCandidates || []).map((candidate) => `
    <li class="content-editor-reference-choice">
      <label>
        <input type="checkbox" data-reference-id="${escapeHtml(candidate.id)}" />
        <span><small>${escapeHtml(candidate.file)} · 第 ${escapeHtml(candidate.line)} 行</small><del>${escapeHtml(candidate.before)}</del><ins>${escapeHtml(candidate.after)}</ins></span>
      </label>
    </li>
  `).join("");
  preview.innerHTML = `
    <div class="content-editor-rename-summary">
      <strong>${escapeHtml(result.oldName)} → ${escapeHtml(result.newName)}</strong>
      <span>将批量修改 ${result.fileCount} 个文件、${result.matchCount} 处引用${result.moves.length ? `，并重命名 ${result.moves.length} 个文件` : ""}。</span>
    </div>
    <ul>${moveItems}${sampleItems}</ul>
    ${result.samples.length > 8 ? `<p>另有 ${result.samples.length - 8} 处预览未展开。</p>` : ""}
    ${duplicateWarning}
    ${referenceItems ? `<div class="content-editor-reference-list"><strong>按 ID 迁移正文引用</strong><ul>${referenceItems}</ul></div>` : ""}
    <p class="content-editor-rename-warning">请核对以上影响范围，再点击“确认改名并保存”。</p>
  `;
  preview.classList.remove("is-hidden");
  setIconButton(form.querySelector("#contentEditorSubmit"), "save", "确认改名并保存");
  preview.scrollIntoView({ block: "nearest" });
}

async function openContentEditor(kind, record = null) {
  const dialog = ensureContentEditorDialog();
  const form = dialog.querySelector("#contentEditorForm");
  const fields = dialog.querySelector("#contentEditorFields");
  const title = dialog.querySelector("#contentEditorTitle");
  const deleteButton = dialog.querySelector("#contentEditorDelete");
  const submit = dialog.querySelector("#contentEditorSubmit");
  const creating = !record;
  form.dataset.kind = kind;
  form.dataset.creating = creating ? "true" : "false";
  form.dataset.recordId = kind === "relationship" && record ? `${record.from}__${record.to}` : (record?.id || "");
  form.dataset.sourcePath = record?.sourcePath || "";
  form.dataset.originalCharacterName = kind === "character" ? (record?.name || "") : "";
  dialog.classList.toggle("is-fragment-writer", kind === "fragment");
  dialog.classList.remove("is-immersive");
  const fullscreenButton = dialog.querySelector("#contentEditorFullscreen");
  fullscreenButton.classList.toggle("is-hidden", kind !== "fragment");
  setIconButton(fullscreenButton, "maximize", "进入沉浸写作");
  clearCharacterRenamePreview(form);
  title.textContent = `${creating ? "新建" : "编辑"}${CONTENT_KIND_LABELS[kind] || "档案"}`;
  setIconButton(submit, creating ? "add" : "save", creating ? `创建${CONTENT_KIND_LABELS[kind] || "档案"}` : "保存修改");
  setIconButton(deleteButton, "trash", `删除${CONTENT_KIND_LABELS[kind] || "档案"}`);
  deleteButton.classList.toggle("is-hidden", creating);

  if (kind === "character") {
    fields.innerHTML = `
      ${contentEditorField("ceName", "人物姓名", record?.name || "", { required: true })}
      ${contentEditorField("ceRole", "叙事定位", record?.narrativeRole || characterNarrativeRole(record), { type: "select", html: `<option>主角</option><option>配角</option>` })}
      ${contentEditorField("ceScope", "收纳状态", record?.characterScope || "常驻人物", { type: "select", html: ["主线人物", "常驻人物", "一次性角色", "待定角色"].map((value) => `<option ${value === record?.characterScope ? "selected" : ""}>${value}</option>`).join("") })}
      ${contentEditorField("ceSide", "人物阵营", record?.side || "中立", { type: "select", html: ["主角方", "中立", "反派方"].map((value) => `<option ${value === (record?.side || "中立") ? "selected" : ""}>${value}</option>`).join("") })}
      ${contentEditorField("ceGroup", "人物分组", record?.group || "")}
      ${contentEditorField("ceImpact", "主线影响", record?.mainPlotImpact ?? 50, { type: "number", min: 0, max: 100, note: "0 最小 · 100 最大" })}
      ${contentEditorField("ceColor", "人物颜色", record?.color || "#3f7fc1", { type: "color" })}
      ${contentEditorField("ceAvatar", "头像路径", record?.avatar?.replace(`${contentBasePath()}/`, "") || "")}
      ${contentEditorField("ceAliases", "别名", editorListValue(record?.aliases))}
      ${contentEditorField("ceMarkers", "人物标识", editorListValue(record?.markers))}
      ${contentEditorField("ceFacts", "档案字段（每行“名称：内容”）", editorFactsValue(record?.facts), { type: "textarea", wide: true, rows: 4 })}
      ${contentEditorField("ceIntro", "人物设定（每行一条）", record?.intro || "", { type: "textarea", wide: true, rows: 8 })}
      <label class="content-editor-check is-wide"><input id="ceGraphVisible" type="checkbox" ${record?.graphVisible === false ? "" : "checked"} /><span>在人物图谱中显示</span></label>
      ${!creating ? '<p class="content-editor-note is-wide">修改人物姓名时，系统会先列出所有受影响的文件、引用和文件改名；确认后再批量重构。</p><section class="content-editor-rename-preview is-wide is-hidden" id="contentEditorRenamePreview" aria-live="polite"></section>' : ""}
    `;
    dialog.querySelector("#ceName")?.addEventListener("input", () => {
      if (form.dataset.renamePreviewName !== dialog.querySelector("#ceName")?.value.trim()) {
        clearCharacterRenamePreview(form);
      }
    });
  } else if (kind === "relationship") {
    const from = record ? getCharacter(record.from) : null;
    const to = record ? getCharacter(record.to) : null;
    fields.innerHTML = `
      ${contentEditorField("ceRelPeople", "关系双方", record ? `${from?.name || record.from} ↔ ${to?.name || record.to}` : "", { readonly: true, wide: true })}
      ${contentEditorField("ceFirstRole", `${from?.name || "人物一"}的身份`, record?.fromRole || "", { required: true })}
      ${contentEditorField("ceSecondRole", `${to?.name || "人物二"}的身份`, record?.toRole || "", { required: true })}
      ${contentEditorField("ceLabel", "关系名称", record?.label || "", { required: true })}
      ${contentEditorField("ceType", "关系类型", record?.type || "")}
      ${contentEditorField("ceColor", "连线颜色", record?.color || "#2a9d8f", { type: "color" })}
    `;
  } else if (kind === "entry") {
    fields.innerHTML = `
      ${contentEditorField("ceId", "稳定 ID", record?.id || "", { readonly: !creating, required: true })}
      ${contentEditorField("ceName", "设定名称", record?.name || "", { readonly: !creating, required: true })}
      ${contentEditorField("ceType", "大类", record?.type || "地点", { required: true })}
      ${contentEditorField("ceSubtype", "细分类型", record?.subtype || "")}
      ${contentEditorField("ceArea", "所属区域", record?.area || "")}
      ${contentEditorField("ceStatus", "整理状态", record?.status || "草稿")}
      ${contentEditorField("ceColor", "设定颜色", record?.accent || "#3f7fc1", { type: "color" })}
      ${contentEditorField("ceAliases", "别名", editorListValue(record?.aliases))}
      ${contentEditorField("ceTags", "标签", editorListValue(record?.tags))}
      ${contentEditorField("cePeople", "强相关人物", "", { type: "select", multiple: true, html: editorMultiOptions(characters, record?.people, (person) => person.name) })}
      ${contentEditorField("cePlots", "手动补充剧情", "", { type: "select", multiple: true, html: editorMultiOptions(plots, record?.plots, (plot) => `第 ${plotSequence(plot)} 章 · ${plot.title}`) })}
      ${contentEditorField("ceBody", "设定正文", record?.intro || "", { type: "textarea", wide: true, rows: 10 })}
      ${!creating ? '<p class="content-editor-note is-wide">修改设定名称请使用检查页的安全重命名，以同步正文引用。</p>' : ""}
    `;
  } else if (kind === "fragment") {
    fields.innerHTML = `
      <div class="fragment-editor-retention is-wide">
        <strong>独立剧本草稿</strong>
        <span>保存后仍只在碎片箱中；只有主动转为剧情，才会进入剧情 Tab。</span>
      </div>
      <details class="fragment-editor-meta is-wide" ${creating ? "open" : ""}>
        <summary>
          <span><strong>碎片信息</strong><small>${escapeHtml(record?.title || "补充标题、状态和标签")}</small></span>
          <i aria-hidden="true"></i>
        </summary>
        <div class="fragment-editor-meta-fields">
          ${contentEditorField("ceId", "稳定 ID", record?.id || "", { readonly: !creating, required: true })}
          ${contentEditorField("ceTitle", "碎片标题", record?.title || "", { required: true })}
          ${contentEditorField("ceStatus", "整理状态", record?.status || "灵感", { required: true })}
          ${contentEditorField("ceColor", "碎片颜色", record?.accent || "#7d6bd6", { type: "color" })}
          ${contentEditorField("ceTags", "标签", editorListValue(record?.tags))}
        </div>
      </details>
      <div class="fragment-editor-workspace is-wide">
        <label class="fragment-editor-source">
          <span>剧本草稿<small>支持 Markdown</small></span>
          <textarea id="ceBody" required spellcheck="true">${escapeHtml(record?.text || "")}</textarea>
        </label>
        <section class="fragment-editor-preview" aria-label="碎片剧本预览">
          <div class="fragment-editor-preview-head"><span>实时预览</span><small>仅预览，不会生成剧情</small></div>
          <div class="plot-detail-body fragment-editor-preview-body" id="fragmentEditorPreview"></div>
        </section>
      </div>
      ${!creating ? `<div class="fragment-editor-convert-row is-wide"><span>准备好进入正式编排时再转换。</span><button class="content-editor-convert icon-action" id="contentEditorConvert" type="button" aria-label="转为正式剧情" title="转为正式剧情">${uiIcon("convert")}</button></div>` : ""}
    `;
    dialog.querySelector("#contentEditorConvert")?.addEventListener("click", () => convertFragmentToPlot(record));
    const fragmentBody = dialog.querySelector("#ceBody");
    const fragmentPreview = dialog.querySelector("#fragmentEditorPreview");
    fragmentBody?.addEventListener("input", renderFragmentEditorPreview);
    fragmentBody?.addEventListener("scroll", () => syncFragmentEditorScroll(fragmentBody, fragmentPreview));
    fragmentPreview?.addEventListener("scroll", () => syncFragmentEditorScroll(fragmentPreview, fragmentBody));
    resetFragmentEditorScrollSync();
    renderFragmentEditorPreview();
  }

  for (const id of ["ceRole", "ceScope", "ceSide"]) {
    const element = dialog.querySelector(`#${id}`);
    const selected = { ceRole: record?.narrativeRole || characterNarrativeRole(record), ceScope: record?.characterScope, ceSide: record?.side }[id];
    if (element && selected) element.value = selected;
  }
  dialog.querySelector("#contentEditorStatus").textContent = "";
  form.onsubmit = saveContentEditor;
  deleteButton.onclick = () => deleteContentRecord(kind, record);
  await initializeRefactorWorkspace();
  if (!contentManagerWritable()) {
    throw new Error("本地服务版本与页面不一致，请重新运行项目启动命令");
  }
  form.querySelectorAll("button, input, select, textarea").forEach((element) => {
    element.disabled = false;
  });
  dialog.showModal();
}

async function saveContentEditor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const kind = form.dataset.kind;
  const creating = form.dataset.creating === "true";
  const status = document.querySelector("#contentEditorStatus");
  const value = (id) => document.querySelector(`#${id}`)?.value.trim() || "";
  status.textContent = "正在保存…";
  form.querySelectorAll("button, input, select, textarea").forEach((element) => { element.disabled = true; });
  try {
    let path;
    let payload = { project: currentProjectId() };
    if (kind === "character") {
      const currentName = value("ceName");
      const originalName = form.dataset.originalCharacterName || "";
      if (!creating && currentName !== originalName) {
        if (!form.dataset.renameOperationId || form.dataset.renamePreviewName !== currentName) {
          clearCharacterRenamePreview(form);
          const preview = await refactorApi("/api/refactor/preview", {
            project: currentProjectId(),
            type: "character",
            id: form.dataset.recordId,
            newName: currentName,
          });
          form.dataset.renameOperationId = preview.operationId;
          form.dataset.renamePreviewName = currentName;
          renderCharacterRenamePreview(form, preview);
          status.textContent = "尚未修改：请先核对批量重构预览。";
          form.querySelectorAll("button, input, select, textarea").forEach((element) => { element.disabled = false; });
          return;
        }
        status.textContent = "正在原子保存档案、姓名和已确认引用…";
      }
      path = creating ? "/api/characters/create" : "/api/characters/update";
      payload = { ...payload, id: form.dataset.recordId, name: currentName, narrativeRole: value("ceRole"), characterScope: value("ceScope"), side: value("ceSide"), group: value("ceGroup"), mainPlotImpact: Number(value("ceImpact") || 50), color: value("ceColor"), avatar: value("ceAvatar"), aliases: commaSeparatedValues(value("ceAliases")), markers: commaSeparatedValues(value("ceMarkers")), facts: editorFactsObject(value("ceFacts")), intro: value("ceIntro"), graphVisible: Boolean(document.querySelector("#ceGraphVisible")?.checked), renameOperationId: form.dataset.renameOperationId || "", referenceIds: [...form.querySelectorAll("[data-reference-id]:checked")].map((input) => input.dataset.referenceId) };
    } else if (kind === "relationship") {
      path = "/api/relationships/update";
      payload = { ...payload, id: form.dataset.recordId, firstRole: value("ceFirstRole"), secondRole: value("ceSecondRole"), label: value("ceLabel"), type: value("ceType"), color: value("ceColor") };
    } else if (kind === "entry") {
      path = "/api/entries/save";
      payload = { ...payload, create: creating, id: value("ceId"), name: value("ceName"), type: value("ceType"), subtype: value("ceSubtype"), area: value("ceArea"), status: value("ceStatus"), accent: value("ceColor"), aliases: commaSeparatedValues(value("ceAliases")), tags: commaSeparatedValues(value("ceTags")), people: contentEditorSelected("cePeople"), plots: contentEditorSelected("cePlots"), body: value("ceBody") };
    } else if (kind === "fragment") {
      path = "/api/fragments/save";
      payload = { ...payload, create: creating, id: value("ceId"), title: value("ceTitle"), status: value("ceStatus"), accent: value("ceColor"), tags: commaSeparatedValues(value("ceTags")), body: value("ceBody") };
    }
    const result = await refactorApi(path, payload);
    status.textContent = "已保存";
    await refreshWorkspaceDataInPlace({
      characterId: kind === "character" ? result.id || form.dataset.recordId : "",
      placeId: kind === "entry" ? result.id || form.dataset.recordId : "",
    });
    ensureContentEditorDialog().close();
  } catch (error) {
    status.textContent = error.message;
    form.querySelectorAll("button, input, select, textarea").forEach((element) => { element.disabled = false; });
  }
}

async function deleteContentRecord(kind, record) {
  if (!record) return;
  const label = record.name || record.title || record.label || record.id;
  if (!window.confirm(`删除“${label}”？它会进入回收站，7 天后才永久删除。`)) return;
  const id = kind === "relationship" ? `${record.from}__${record.to}` : record.id;
  const dialog = ensureContentEditorDialog();
  const dialogWasOpen = dialog.open;
  const status = dialog.querySelector("#contentEditorStatus");
  status.textContent = "正在移入回收站…";
  try {
    await refactorApi("/api/records/delete", { project: currentProjectId(), kind, id });
    status.textContent = "已移入回收站";
    await refreshWorkspaceDataInPlace();
    if (dialogWasOpen && dialog.open) dialog.close();
    refreshPlotTrashAccess();
  } catch (error) {
    status.textContent = error.message;
    if (!dialogWasOpen) window.alert(error.message);
  }
}

function convertFragmentToPlot(fragment) {
  pendingFragmentConversionId = fragment.id;
  ensureContentEditorDialog().close();
  openPlotCreateDialog().then(() => {
    if (plotCreateName) plotCreateName.value = fragment.title || "";
    if (plotCreateBody) plotCreateBody.value = fragment.text || "";
    if (plotCreateTags) plotCreateTags.value = editorListValue(fragment.tags);
    renderPlotEditorPreview();
  });
}

function projectChapterRows() {
  return chapterKeys().map((id) => `
    <div class="project-chapter-row">
      <input class="project-chapter-id" value="${escapeHtml(id)}" ${plots.some((plot) => plot.chapter === id) ? "readonly" : ""} aria-label="篇章 ID" />
      <input class="project-chapter-label" value="${escapeHtml(chapterName(id))}" aria-label="篇章名称" />
      <button class="project-chapter-remove icon-action is-danger" type="button" aria-label="删除篇章" title="${plots.some((plot) => plot.chapter === id) ? "该篇章仍有文章" : "删除篇章"}" ${plots.some((plot) => plot.chapter === id) ? "disabled" : ""}>${uiIcon("trash")}</button>
    </div>
  `).join("");
}

async function openProjectInPlace(projectId) {
  const targetProjectId = String(projectId || "").trim();
  if (targetProjectId && targetProjectId === currentProjectId()) return;
  const previousUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const nextUrl = new URL(window.location.href);
  if (targetProjectId) nextUrl.searchParams.set("project", targetProjectId);
  else nextUrl.searchParams.delete("project");
  window.history.pushState({ project: targetProjectId }, "", `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);

  refactorCapability = null;
  refactorCapabilityProject = "";
  try {
    await loadMarkdownData();
  } catch (error) {
    window.history.replaceState({}, "", previousUrl);
    await loadMarkdownData();
    throw error;
  }

  Object.assign(state, {
    selected: "",
    selectedCharacter: (characters.find((person) => !isTemporaryCharacter(person)) || characters[0])?.id || "",
    selectedPlotId: null,
    editingPlotId: null,
    hasSelection: false,
    chapter: "all",
    plotStatus: "all",
    plotTags: allPlotTags(),
    plotShelf: "all",
    fragmentTags: allFragmentTags(),
    plotPage: 1,
    fragmentPage: 1,
    highlightPlotId: null,
    dragging: null,
    panning: null,
    graphScale: 1,
    graphPanX: 0,
    graphPanY: 0,
    search: "",
    group: "all",
    relationType: "all",
    characterSearch: "",
    characterShelf: "main",
    characterCategory: "all",
    characterGroup: "all",
    characterViewMode: "cards",
    characterAppearanceChapter: "all",
    placeSearch: "",
    entryTypes: [],
    entryTags: allEntryTags(),
    selectedPlace: places[0]?.id || "",
    globalSearch: "",
    highlightedReferenceType: "",
    highlightedReferenceId: "",
    detailReturnContext: null,
    plotReadingPositions: {},
    timelineReversed: false,
  });
  timelineModel = null;
  timelineViewportKey = "";
  graphDataDirty = true;
  renderProjectChrome();
  renderProfile();
  hideGlobalSearchResults();
  switchView("graph");
  markRelatedNodes();
  refreshPlotTrashAccess();
  refreshTimelineEditorAccess();
  refreshContentManagerAccess();
}

async function openProjectSettings() {
  const dialog = ensureContentEditorDialog();
  const form = dialog.querySelector("#contentEditorForm");
  form.dataset.kind = "project";
  form.dataset.creating = "false";
  dialog.querySelector("#contentEditorTitle").textContent = "作品与篇章";
  setIconButton(dialog.querySelector("#contentEditorSubmit"), "save", "保存作品与篇章设置");
  dialog.querySelector("#contentEditorDelete").classList.add("is-hidden");
  dialog.querySelector("#contentEditorFields").innerHTML = `
    ${contentEditorField("ceProjectTitle", "作品名称", projectConfig.title || "", { required: true })}
    ${contentEditorField("ceProjectEyebrow", "顶部名称", projectConfig.eyebrow || "Story Teller", { required: true })}
    <section class="project-chapter-editor is-wide">
      <div><strong>篇章</strong><button class="icon-action" id="projectChapterAdd" type="button" aria-label="新增篇章" title="新增篇章">${uiIcon("add")}</button></div>
      <div id="projectChapterRows">${projectChapterRows()}</div>
    </section>
    <section class="project-create-panel is-wide">
      <strong>切换作品</strong>
      <div><select id="projectSwitchSelect"></select><button class="icon-action" id="projectSwitchOpen" type="button" aria-label="打开所选作品" title="打开所选作品">${uiIcon("folder")}</button></div>
    </section>
    <section class="project-create-panel is-wide">
      <strong>创建另一部作品</strong>
      <div><input id="newProjectId" placeholder="项目 ID，例如 new-story" /><input id="newProjectTitle" placeholder="作品名称" /><button class="icon-action" id="newProjectCreate" type="button" aria-label="创建并打开作品" title="创建并打开作品">${uiIcon("add")}</button></div>
    </section>
  `;
  const rows = dialog.querySelector("#projectChapterRows");
  const bindRemove = () => rows.querySelectorAll(".project-chapter-remove").forEach((button) => {
    button.onclick = () => button.closest(".project-chapter-row")?.remove();
  });
  bindRemove();
  dialog.querySelector("#projectChapterAdd").onclick = () => {
    const number = rows.children.length + 1;
    rows.insertAdjacentHTML("beforeend", `<div class="project-chapter-row"><input class="project-chapter-id" value="act${number}" aria-label="篇章 ID" /><input class="project-chapter-label" value="第${number}篇" aria-label="篇章名称" /><button class="project-chapter-remove icon-action is-danger" type="button" aria-label="删除篇章" title="删除篇章">${uiIcon("trash")}</button></div>`);
    bindRemove();
  };
  dialog.querySelector("#newProjectCreate").onclick = async () => {
    const id = dialog.querySelector("#newProjectId").value.trim();
    const title = dialog.querySelector("#newProjectTitle").value.trim();
    const status = dialog.querySelector("#contentEditorStatus");
    try {
      await refactorApi("/api/projects/create", { id, title });
      status.textContent = "正在打开新作品…";
      await openProjectInPlace(id);
      dialog.close();
    } catch (error) {
      status.textContent = error.message;
    }
  };
  const projectResult = await refactorApi("/api/projects");
  const projectSelect = dialog.querySelector("#projectSwitchSelect");
  projectSelect.innerHTML = projectResult.items.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === currentProjectId() ? "selected" : ""}>${escapeHtml(item.title)}（${escapeHtml(item.id)}）</option>`).join("");
  dialog.querySelector("#projectSwitchOpen").onclick = async () => {
    const status = dialog.querySelector("#contentEditorStatus");
    status.textContent = "正在切换作品…";
    try {
      await openProjectInPlace(projectSelect.value);
      dialog.close();
    } catch (error) {
      status.textContent = error.message;
    }
  };
  form.onsubmit = async (event) => {
    event.preventDefault();
    const status = dialog.querySelector("#contentEditorStatus");
    const chapters = [...rows.querySelectorAll(".project-chapter-row")].map((row) => ({ id: row.querySelector(".project-chapter-id").value.trim(), label: row.querySelector(".project-chapter-label").value.trim() }));
    status.textContent = "正在保存作品设置…";
    try {
      await refactorApi("/api/project/update", { project: currentProjectId(), title: dialog.querySelector("#ceProjectTitle").value.trim(), eyebrow: dialog.querySelector("#ceProjectEyebrow").value.trim(), chapters });
      status.textContent = "已保存";
      await refreshWorkspaceDataInPlace();
      dialog.close();
    } catch (error) {
      status.textContent = error.message;
    }
  };
  await initializeRefactorWorkspace();
  dialog.querySelector("#contentEditorStatus").textContent = "";
  dialog.showModal();
}

async function openGraphSettings() {
  const dialog = ensureContentEditorDialog();
  const form = dialog.querySelector("#contentEditorForm");
  form.dataset.kind = "graph";
  dialog.querySelector("#contentEditorTitle").textContent = "人物图谱布局";
  setIconButton(dialog.querySelector("#contentEditorSubmit"), "save", "保存图谱布局");
  dialog.querySelector("#contentEditorDelete").classList.add("is-hidden");
  dialog.querySelector("#contentEditorFields").innerHTML = `
    ${contentEditorField("ceNodeSpacing", "节点最小间距", graphLayoutConfig.nodeSpacing || 116, { type: "number", min: 80, max: 260 })}
    ${contentEditorField("ceRelationDistance", "普通关系长度", graphLayoutConfig.relationshipDistance || 250, { type: "number", min: 120, max: 600 })}
    ${contentEditorField("ceLeafExtra", "外围人物延伸", graphLayoutConfig.leafDistanceExtra || 48, { type: "number", min: 0, max: 300 })}
    ${contentEditorField("ceCenterStrength", "自动居中力度", graphLayoutConfig.centerStrength || 1, { type: "number", min: 0, max: 3 })}
    ${contentEditorField("ceGroupStrength", "人物分组力度", graphLayoutConfig.groupStrength || 1, { type: "number", min: 0, max: 3 })}
    ${contentEditorField("ceLeafStrength", "外围延伸力度", graphLayoutConfig.leafStrength || 1, { type: "number", min: 0, max: 3 })}
    <p class="content-editor-note is-wide">当前拖动过的人物位置会一起保存。以后拖动节点后，再点击这里保存即可。</p>
  `;
  form.onsubmit = async (event) => {
    event.preventDefault();
    const number = (id) => Number(dialog.querySelector(`#${id}`).value);
    const anchors = characters.filter((person) => Number.isFinite(person.manualAnchorX) && Number.isFinite(person.manualAnchorY)).map((person) => ({ id: person.id, x: person.manualAnchorX, y: person.manualAnchorY }));
    const status = dialog.querySelector("#contentEditorStatus");
    status.textContent = "正在保存图谱布局…";
    try {
      await refactorApi("/api/graph-layout/update", { project: currentProjectId(), nodeSpacing: number("ceNodeSpacing"), relationshipDistance: number("ceRelationDistance"), leafDistanceExtra: number("ceLeafExtra"), centerStrength: number("ceCenterStrength"), groupStrength: number("ceGroupStrength"), leafStrength: number("ceLeafStrength"), anchors });
      status.textContent = `已保存 ${anchors.length} 个人物位置。`;
      await refreshWorkspaceDataInPlace();
      dialog.close();
    } catch (error) {
      status.textContent = error.message;
    }
  };
  await initializeRefactorWorkspace();
  dialog.querySelector("#contentEditorStatus").textContent = "";
  dialog.showModal();
}

async function repairProjectDiagnostics() {
  if (!window.confirm("安全修复会整理文章顺序并修正人物、关系文件名。稳定 ID 和正文不会改变，是否继续？")) return;
  const button = document.querySelector("#diagnosticRepairTrigger");
  button.disabled = true;
  setIconButton(button, "restore", "正在安全修复…");
  try {
    const result = await refactorApi("/api/diagnostics/repair", { project: currentProjectId() });
    await refreshWorkspaceDataInPlace();
    button.disabled = false;
    setIconButton(button, "repair", "安全修复");
    window.alert(result.changeCount ? `已完成 ${result.changeCount} 项安全修复。` : "没有需要自动修复的项目。");
  } catch (error) {
    window.alert(error.message);
    button.disabled = false;
    setIconButton(button, "repair", "安全修复");
  }
}

function installContentManagerActions() {
  const addButton = (container, id, label, icon, handler) => {
    if (!container || document.querySelector(`#${id}`)) return;
    const button = document.createElement("button");
    button.id = id;
    button.className = "content-manager-action icon-action";
    button.type = "button";
    setIconButton(button, icon, label);
    button.addEventListener("click", handler);
    if (id === "entryCreateTrigger" && document.querySelector("#placeSearch")) {
      document.querySelector("#placeSearch").before(button);
    } else {
      container.append(button);
    }
  };
  addButton(document.querySelector('[data-page="places"] .place-rail'), "entryCreateTrigger", "新建设定", "add", () => openContentEditor("entry"));
  addButton(document.querySelector('[data-page="fragments"] .topbar'), "fragmentCreateTrigger", "新建碎片", "add", () => openContentEditor("fragment"));
  addButton(document.querySelector('[data-page="story"] .story-head-actions'), "projectSettingsTrigger", "作品与篇章", "layout", openProjectSettings);
  addButton(document.querySelector('[data-page="graph"] .graph-tools'), "graphSettingsTrigger", "布局设置", "layout", openGraphSettings);
  addButton(document.querySelector('[data-page="diagnostics"] .topbar'), "diagnosticRepairTrigger", "安全修复", "repair", repairProjectDiagnostics);
}

async function refreshContentManagerAccess() {
  try {
    await initializeRefactorWorkspace();
    document.body.classList.toggle("is-content-writable", contentManagerWritable());
  } catch {
    document.body.classList.remove("is-content-writable");
  }
}

installContentManagerActions();
