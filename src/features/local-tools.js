function renderDiagnostics() {
  if (!diagnosticSummary || !diagnosticList) return;
  const errors = configDiagnostics.filter((item) => item.level === "error").length;
  const warnings = configDiagnostics.filter((item) => item.level === "warning").length;

  if (diagnosticNavCount) {
    diagnosticNavCount.textContent = String(configDiagnostics.length);
    diagnosticNavCount.classList.toggle("is-hidden", configDiagnostics.length === 0);
  }

  diagnosticSummary.innerHTML = `
    <div class="diagnostic-stat is-total">
      <span>检查结果</span>
      <strong>${configDiagnostics.length ? `${configDiagnostics.length} 项` : "全部正常"}</strong>
    </div>
    <div class="diagnostic-stat is-error">
      <span>需要修复</span>
      <strong>${errors}</strong>
    </div>
    <div class="diagnostic-stat is-warning">
      <span>需要确认</span>
      <strong>${warnings}</strong>
    </div>
  `;

  diagnosticList.innerHTML = configDiagnostics.length
    ? configDiagnostics.map((item) => `
        <article class="diagnostic-item is-${item.level}">
          <span class="diagnostic-level">${item.level === "error" ? "错误" : "提醒"}</span>
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.detail)}</p>
          </div>
          <small>${escapeHtml(item.source)}</small>
        </article>
      `).join("")
    : `
      <div class="diagnostic-clean">
        <strong>配置关系完整</strong>
        <p>没有发现重复编号、失效引用、歧义称呼或缺失档案。</p>
      </div>
    `;
}

function refactorRecords() {
  return refactorType?.value === "entry" ? places : characters;
}

function setRefactorBusy(busy) {
  [refactorType, refactorTarget, refactorNewName, refactorPreviewBtn, refactorUndoBtn, refactorCancelBtn, refactorApplyBtn]
    .filter(Boolean)
    .forEach((element) => {
      element.disabled = busy
        || (!refactorCapability?.writable && element !== refactorCancelBtn)
        || (element === refactorApplyBtn && !refactorOperationId);
    });
}

function setRelationshipCreatorBusy(busy) {
  [
    relationshipFirstPerson,
    relationshipFirstRole,
    relationshipSecondPerson,
    relationshipSecondRole,
    relationshipLabel,
    relationshipType,
    relationshipColor,
    relationshipCreateBtn,
  ].filter(Boolean).forEach((element) => {
    element.disabled = busy || !refactorCapability?.writable || characters.length < 2;
  });
}

function setRelationshipCreateStatus(message = "", type = "") {
  if (!relationshipCreateStatus) return;
  relationshipCreateStatus.textContent = message;
  relationshipCreateStatus.className = type ? `is-${type}` : "";
}

function updateRelationshipPairState() {
  const firstId = relationshipFirstPerson?.value || "";
  const secondId = relationshipSecondPerson?.value || "";
  let message = "关系会保存为一份 Markdown，并自动加入图谱。";
  let error = false;
  if (firstId && firstId === secondId) {
    message = "请选择两个不同的人物";
    error = true;
  } else if (firstId && secondId && relationshipPairExists(firstId, secondId)) {
    message = "这两个人物已经存在关系，请直接编辑原关系文件";
    error = true;
  }
  setRelationshipCreateStatus(message, error ? "error" : "");
  if (relationshipCreateBtn) {
    relationshipCreateBtn.disabled = error
      || !refactorCapability?.writable
      || characters.length < 2;
  }
}

function refreshRelationshipCreator() {
  if (!relationshipWorkspace || !relationshipFirstPerson || !relationshipSecondPerson) return;
  const previousFirst = relationshipFirstPerson.value;
  const previousSecond = relationshipSecondPerson.value;
  const options = characters
    .map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}（ID ${escapeHtml(person.id)}）</option>`)
    .join("");
  relationshipFirstPerson.innerHTML = options;
  relationshipSecondPerson.innerHTML = options;

  const ids = characters.map((person) => String(person.id));
  let suggestedPair = [];
  for (let firstIndex = 0; firstIndex < ids.length && !suggestedPair.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < ids.length; secondIndex += 1) {
      if (!relationshipPairExists(ids[firstIndex], ids[secondIndex])) {
        suggestedPair = [ids[firstIndex], ids[secondIndex]];
        break;
      }
    }
  }
  relationshipFirstPerson.value = ids.includes(previousFirst)
    ? previousFirst
    : suggestedPair[0] || ids[0] || "";
  relationshipSecondPerson.value = ids.includes(previousSecond) && previousSecond !== relationshipFirstPerson.value
    ? previousSecond
    : (
      ids.find((id) => id !== relationshipFirstPerson.value && !relationshipPairExists(relationshipFirstPerson.value, id))
      || suggestedPair[1]
      || ids.find((id) => id !== relationshipFirstPerson.value)
      || ""
    );
  if (characters.length < 2) {
    setRelationshipCreateStatus("至少需要两个人物档案才能创建关系", "error");
  } else if (!refactorCapability?.writable) {
    setRelationshipCreateStatus("公开部署只读，请使用 run.sh 启动本地服务", "error");
  }
  setRelationshipCreatorBusy(false);
  if (characters.length >= 2 && refactorCapability?.writable) updateRelationshipPairState();
  renderRelationshipManager();
}

function renderRelationshipManager() {
  if (!relationshipManagerList) return;
  relationshipManagerList.innerHTML = relationships.length ? `
    <div class="relationship-manager-head"><strong>已有关系</strong><span>${relationships.length} 条</span></div>
    ${relationships.map((link, index) => {
      const from = getCharacter(link.from);
      const to = getCharacter(link.to);
      return `<article><div><strong>${escapeHtml(link.label || "未命名关系")}</strong><span>${escapeHtml(from?.name || link.from || "失效人物")} ↔ ${escapeHtml(to?.name || link.to || "失效人物")}</span></div><div><button class="relationship-manage-edit icon-action" data-index="${index}" type="button" aria-label="编辑${escapeHtml(link.label || "人物关系")}" title="编辑人物关系">${uiIcon("edit")}</button><button class="relationship-manage-delete icon-action is-danger" data-index="${index}" type="button" aria-label="删除${escapeHtml(link.label || "人物关系")}" title="删除人物关系">${uiIcon("trash")}</button></div></article>`;
    }).join("")}
  ` : '<div class="relationship-manager-head"><strong>已有关系</strong><span>暂无</span></div>';
  relationshipManagerList.querySelectorAll(".relationship-manage-edit").forEach((button) => button.addEventListener("click", () => openContentEditor("relationship", relationships[Number(button.dataset.index)])));
  relationshipManagerList.querySelectorAll(".relationship-manage-delete").forEach((button) => button.addEventListener("click", () => deleteContentRecord("relationship", relationships[Number(button.dataset.index)])));
}

function relationshipPairExists(firstId, secondId) {
  return relationships.some((link) => {
    const endpoints = [String(link.from), String(link.to)];
    return endpoints.includes(firstId) && endpoints.includes(secondId);
  });
}

async function createRelationship(event) {
  event.preventDefault();
  if (!relationshipCreateForm?.reportValidity()) return;
  const firstId = relationshipFirstPerson?.value || "";
  const secondId = relationshipSecondPerson?.value || "";
  if (firstId === secondId) {
    setRelationshipCreateStatus("请选择两个不同的人物", "error");
    relationshipSecondPerson?.focus();
    return;
  }
  if (relationshipPairExists(firstId, secondId)) {
    setRelationshipCreateStatus("这两个人物已经存在关系，请直接编辑原关系文件", "error");
    return;
  }

  setRelationshipCreatorBusy(true);
  setRelationshipCreateStatus("正在创建关系…");
  try {
    const result = await refactorApi("/api/relationships/create", {
      project: currentProjectId(),
      firstId,
      firstRole: relationshipFirstRole?.value.trim() || "",
      secondId,
      secondRole: relationshipSecondRole?.value.trim() || "",
      label: relationshipLabel?.value.trim() || "",
      type: relationshipType?.value.trim() || "",
      color: relationshipColor?.value || "",
    });
    setRelationshipCreateStatus(`已创建“${result.label}”`, "success");
    await refreshWorkspaceDataInPlace();
    refreshRelationshipCreator();
  } catch (error) {
    setRelationshipCreateStatus(error.message, "error");
    setRelationshipCreatorBusy(false);
  }
}

function closeRefactorPreview() {
  refactorOperationId = "";
  refactorPreview?.classList.add("is-hidden");
  if (refactorPreviewSummary) refactorPreviewSummary.innerHTML = "";
  if (refactorChangeList) refactorChangeList.innerHTML = "";
}

function refreshRefactorTargets() {
  if (!refactorTarget) return;
  const records = [...refactorRecords()].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  refactorTarget.innerHTML = records
    .map((record) => `<option value="${escapeHtml(record.id)}">${escapeHtml(record.name)}</option>`)
    .join("");
  refactorTarget.disabled = !refactorCapability?.writable || records.length === 0;
  if (refactorNewName) {
    refactorNewName.value = "";
    refactorNewName.placeholder = records.length ? `将“${records[0].name}”改为…` : "当前类型没有档案";
  }
  closeRefactorPreview();
}

function updateRefactorTargetHint() {
  const selected = refactorRecords().find((record) => String(record.id) === refactorTarget?.value);
  if (refactorNewName) {
    refactorNewName.value = "";
    refactorNewName.placeholder = selected ? `将“${selected.name}”改为…` : "输入新名称";
  }
  closeRefactorPreview();
}

function setRefactorUnavailable(message) {
  refactorCapability = null;
  refactorCapabilityProject = currentProjectId();
  if (refactorMode) {
    refactorMode.textContent = "只读模式";
    refactorMode.className = "refactor-mode is-readonly";
  }
  if (refactorPreviewSummary) {
    refactorPreviewSummary.innerHTML = `<strong>无法修改本地文件</strong><span>${escapeHtml(message)}</span>`;
  }
  refactorPreview?.classList.remove("is-hidden");
  refactorChangeList?.replaceChildren();
  refactorUndoBtn?.classList.add("is-hidden");
  setRefactorBusy(false);
  refreshRelationshipCreator();
}

async function refactorApi(path, body, retryAuthorization = true) {
  const options = body
    ? {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Story-Teller-Token": refactorCapability?.token || "",
        },
        body: JSON.stringify(body),
      }
    : {};
  const response = await fetch(path, options);
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("当前是公开只读部署；请使用项目自带的本地启动命令");
  }
  const result = await response.json();
  if (response.status === 403 && body && retryAuthorization) {
    refactorCapability = null;
    refactorCapabilityProject = "";
    await initializeRefactorWorkspace(true);
    return refactorApi(path, body, false);
  }
  if (response.status === 404 && result.error === "未知接口") {
    throw new Error("本地服务版本与页面不一致，请重新运行项目启动命令");
  }
  if (!response.ok || !result.ok) throw new Error(result.error || "本地操作失败");
  return result;
}

async function initializeRefactorWorkspace(force = false) {
  if (!refactorWorkspace) return;
  const project = currentProjectId();
  if (!force && refactorCapability?.writable && refactorCapabilityProject === project) {
    refreshRelationshipCreator();
    return;
  }
  if (refactorMode) {
    refactorMode.textContent = "正在连接本地服务";
    refactorMode.className = "refactor-mode";
  }
  setRefactorBusy(true);
  try {
    const capability = await refactorApi(`/api/capabilities?project=${encodeURIComponent(project)}`);
    refactorCapability = capability;
    refactorCapabilityProject = project;
    if (refactorMode) {
      refactorMode.textContent = "本地可写";
      refactorMode.className = "refactor-mode is-writable";
    }
    refactorUndoBtn?.classList.toggle("is-hidden", !capability.canUndo);
    if (refactorUndoBtn && capability.undoLabel) {
      setIconButton(refactorUndoBtn, "restore", `撤销：${capability.undoLabel}`);
    }
    refreshRefactorTargets();
    setRefactorBusy(false);
    refreshRelationshipCreator();
  } catch (error) {
    setRefactorUnavailable(error.message);
  }
}

function renderRefactorError(message) {
  if (refactorPreviewSummary) {
    refactorPreviewSummary.innerHTML = `<strong>没有应用任何修改</strong><span>${escapeHtml(message)}</span>`;
  }
  refactorChangeList?.replaceChildren();
  refactorPreview?.classList.remove("is-hidden");
}

async function previewRefactor() {
  const newName = refactorNewName?.value.trim() || "";
  if (!newName) {
    renderRefactorError("请先输入新名称");
    refactorNewName?.focus();
    return;
  }
  setRefactorBusy(true);
  try {
    const result = await refactorApi("/api/refactor/preview", {
      project: currentProjectId(),
      type: refactorType.value,
      id: refactorTarget.value,
      newName,
    });
    refactorOperationId = result.operationId;
    const duplicateScope = result.ambiguousName
      ? `；检测到同名人物（ID ${result.duplicateCharacterIds.map(escapeHtml).join("、")}），请逐条选择属于当前 ID 的正文引用`
      : "";
    refactorPreviewSummary.innerHTML = `
      <strong>${escapeHtml(result.oldName)} → ${escapeHtml(result.newName)}</strong>
      <span>${result.fileCount} 个文件，${result.matchCount} 处修改${result.moves.length ? `，${result.moves.length} 个文件改名` : ""}${duplicateScope}</span>
    `;
    const moveItems = result.moves.map((move) => `
      <article class="refactor-change is-file-move">
        <small>文件重命名</small>
        <del>${escapeHtml(move.from)}</del>
        <ins>${escapeHtml(move.to)}</ins>
      </article>
    `).join("");
    const contentItems = result.samples.map((sample) => `
          <article class="refactor-change">
            <small>${escapeHtml(sample.file)} · 第 ${sample.line} 行</small>
            <del>${escapeHtml(sample.before)}</del>
            <ins>${escapeHtml(sample.after)}</ins>
          </article>
        `).join("");
    const referenceItems = (result.referenceCandidates || []).map((candidate) => `
      <article class="refactor-change refactor-reference-choice">
        <label>
          <input type="checkbox" data-reference-id="${escapeHtml(candidate.id)}" />
          <span><small>${escapeHtml(candidate.file)} · 第 ${escapeHtml(candidate.line)} 行</small><del>${escapeHtml(candidate.before)}</del><ins>${escapeHtml(candidate.after)}</ins></span>
        </label>
      </article>
    `).join("");
    refactorChangeList.innerHTML = moveItems || contentItems || referenceItems
      ? moveItems + contentItems + referenceItems
      : '<p class="refactor-no-change">没有找到需要修改的引用。</p>';
    refactorPreview.classList.remove("is-hidden");
  } catch (error) {
    refactorOperationId = "";
    renderRefactorError(error.message);
  } finally {
    setRefactorBusy(false);
  }
}

async function applyRefactor() {
  if (!refactorOperationId) return;
  const oldName = refactorRecords().find((record) => String(record.id) === refactorTarget?.value)?.name || "档案";
  const newName = refactorNewName?.value.trim() || "新名称";
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  setRefactorBusy(true);
  try {
    const referenceIds = [...(refactorChangeList?.querySelectorAll("[data-reference-id]:checked") || [])]
      .map((input) => input.dataset.referenceId);
    await refactorApi("/api/refactor/apply", { operationId: refactorOperationId, referenceIds });
    await refreshWorkspaceDataInPlace();
    await initializeRefactorWorkspace(true);
    refactorOperationId = "";
    if (refactorPreviewSummary) {
      refactorPreviewSummary.innerHTML = `<strong>重命名已完成</strong><span>${escapeHtml(oldName)} → ${escapeHtml(newName)}</span>`;
    }
    refactorChangeList?.replaceChildren();
    refactorPreview?.classList.remove("is-hidden");
    setRefactorBusy(false);
    window.requestAnimationFrame(() => window.scrollTo({ left: scrollX, top: scrollY, behavior: "instant" }));
  } catch (error) {
    renderRefactorError(error.message);
    setRefactorBusy(false);
  }
}

async function undoRefactor() {
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  setRefactorBusy(true);
  try {
    await refactorApi("/api/refactor/undo", { project: currentProjectId() });
    await refreshWorkspaceDataInPlace();
    await initializeRefactorWorkspace(true);
    if (refactorPreviewSummary) {
      refactorPreviewSummary.innerHTML = "<strong>已撤销上次重命名</strong><span>档案和引用已经原地恢复。</span>";
    }
    refactorChangeList?.replaceChildren();
    refactorPreview?.classList.remove("is-hidden");
    setRefactorBusy(false);
    window.requestAnimationFrame(() => window.scrollTo({ left: scrollX, top: scrollY, behavior: "instant" }));
  } catch (error) {
    renderRefactorError(error.message);
    setRefactorBusy(false);
  }
}

async function requestDiagnosticsRender({ preserveExisting = false } = {}) {
  if (!timelineConfigLoaded && diagnosticList && !preserveExisting) {
    diagnosticList.innerHTML = '<div class="diagnostic-clean"><strong>正在检查配置</strong><p>时间线配置会在这里按需加载。</p></div>';
  }
  try {
    await Promise.all([ensureTimelineConfig(), initializeRefactorWorkspace()]);
    if (state.view === "diagnostics") renderDiagnostics();
  } catch (error) {
    if (diagnosticList) {
      diagnosticList.innerHTML = `<div class="diagnostic-clean"><strong>配置检查失败</strong><p>${escapeHtml(error.message)}</p></div>`;
    }
  }
}
