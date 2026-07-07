function characterSearchValues(person) {
  return [
    person.name,
    person.id,
    person.group,
    person.characterScope,
    person.intro,
    ...characterMarkers(person),
    ...characterFactSearchValues(person),
    ...characterRelationshipSearchValues(person),
  ];
}

function characterMatchesArchiveSearch(person) {
  if (!state.characterSearch) return true;
  return matchesKeyword(characterSearchValues(person), state.characterSearch.toLowerCase());
}

function characterVisibleInArchive(person) {
  if (!characterMatchesArchiveSearch(person)) return false;
  if (state.characterShelf === "temporary") return isTemporaryCharacter(person);
  if (state.characterSearch) return true;
  return !isTemporaryCharacter(person);
}

function setCharacterShelfForPerson(person) {
  state.characterShelf = isTemporaryCharacter(person) ? "temporary" : "main";
}

function renderTemporaryCharacterToggle() {
  if (!temporaryCharacterToggle) return;
  const temporaryCount = characters.filter(isTemporaryCharacter).length;
  const mainCount = characters.length - temporaryCount;
  const active = state.characterShelf === "temporary";
  temporaryCharacterToggle.classList.toggle("is-active", active);
  temporaryCharacterToggle.setAttribute("aria-pressed", String(active));
  temporaryCharacterToggle.setAttribute("aria-label", active ? `返回长期人物列表，共 ${mainCount} 个` : `查看临时角色，共 ${temporaryCount} 个`);
  temporaryCharacterToggle.querySelector("span").textContent = active ? "返回人物" : "收纳箱";
  if (temporaryCharacterCount) temporaryCharacterCount.textContent = String(active ? mainCount : temporaryCount);
}

function renderCharacterList() {
  renderTemporaryCharacterToggle();
  const visibleCharacters = characters.filter(characterVisibleInArchive);

  if (visibleCharacters.length && !visibleCharacters.some((person) => person.id === state.selectedCharacter)) {
    state.selectedCharacter = visibleCharacters[0].id;
  }
  if (!visibleCharacters.length) {
    state.selectedCharacter = "";
  }

  characterList.innerHTML = visibleCharacters
    .map((person) => `
      <button class="character-list-item ${person.id === state.selectedCharacter ? "is-active" : ""}" data-id="${escapeHtml(person.id)}" type="button">
        <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
        <span>
          <strong>${escapeHtml(person.name)}</strong>
          <small>${escapeHtml(person.group || "未分组")} · ${escapeHtml(characterScopeLabel(person))}</small>
        </span>
      </button>
    `)
    .join("");

  if (!visibleCharacters.length) {
    characterList.innerHTML = `<p class="empty-state">${state.characterShelf === "temporary" ? "还没有收纳临时角色" : "没有找到匹配人物"}</p>`;
  }

  document.querySelectorAll(".character-list-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedCharacter = button.dataset.id;
      renderCharacterList();
      renderCharacterDetail();
      scrollPageToTop();
    });
  });
}

function renderCharacterDetail() {
  if (state.characterShelf === "temporary") {
    renderTemporaryCharacterArchive();
    return;
  }

  const person = state.selectedCharacter ? getCharacter(state.selectedCharacter) : null;
  if (!person) {
    characterDetail.innerHTML = `
      <div class="character-empty-detail">
        <strong>${state.characterShelf === "temporary" ? "临时角色抽屉是空的" : "没有选中人物"}</strong>
        <p>${state.characterShelf === "temporary" ? "给人物档案加上 characterScope: 一次性角色 或 待定角色 后，就会收纳到这里。" : "可以从左侧列表或顶部搜索进入人物详情。"}</p>
      </div>
    `;
    return;
  }

  const personPlots = plots.filter((plot) => plot.people.includes(person.id) || person.events.includes(plot.id));
  const personLinks = relationships.filter((link) => link.from === person.id || link.to === person.id);

  characterDetail.innerHTML = `
    ${detailReturnButton()}
    <div class="character-hero ${person.facts.length ? "has-facts" : ""}" style="--accent:${escapeHtml(person.color)}">
      <div class="character-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</div>
      <div class="character-copy">
        <p class="label">${escapeHtml(person.group || "未分组")} · ${escapeHtml(characterScopeLabel(person))}</p>
        <div class="character-title-row">
          <h2>${escapeHtml(person.name)}</h2>
          <button
            class="character-rename-trigger"
            type="button"
            aria-label="修改${escapeHtml(person.name)}的名字"
            title="修改角色名"
          >
            <span aria-hidden="true">✎</span>
          </button>
        </div>
        <div class="character-rename-editor is-hidden">
          <div class="character-rename-input-row">
            <input
              class="character-rename-input"
              type="text"
              maxlength="80"
              autocomplete="off"
              placeholder="输入新的角色名"
              aria-label="新的角色名"
            />
            <button class="character-rename-preview" type="button">预览修改</button>
            <button class="character-rename-cancel" type="button">取消</button>
          </div>
          <div class="character-rename-result" aria-live="polite"></div>
        </div>
        <p>${escapeHtml(person.intro)}</p>
        ${person.facts.length ? `
          <dl class="character-facts" aria-label="${escapeHtml(person.name)}的档案信息">
            ${person.facts.map((fact) => `
              <div class="character-fact">
                <dt>${escapeHtml(fact.label)}</dt>
                <dd>${escapeHtml(fact.value)}</dd>
              </div>
            `).join("")}
          </dl>
        ` : ""}
      </div>
      <aside class="character-marker-panel">
        ${markerBadges(person)}
        ${renderCharacterScopeTools(person)}
      </aside>
    </div>

    <section class="character-section">
      <div class="section-title">
        <p class="label">人物关系</p>
        <h3>${personLinks.length} 条关系</h3>
      </div>
      <div class="relation-list">
        ${personLinks.map((link) => {
          const perspective = relationshipPerspective(link, person.id);
          const other = getCharacter(perspective.otherId);
          return `
            <button
              class="relation-row"
              data-character-id="${escapeHtml(perspective.otherId)}"
              type="button"
              style="--accent:${escapeHtml(link.color)}"
              aria-label="查看${escapeHtml(other?.name || perspective.otherId)}的人物详情"
            >
              <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(other?.gradient || "linear-gradient(135deg, #3f7fc1, #7d6bd6)")}">
                ${other ? avatarContent(other) : escapeHtml(perspective.otherId)}
              </span>
              <span class="relation-person">
                <strong>${escapeHtml(other?.name || perspective.otherId)}</strong>
                <span class="relation-role">${escapeHtml(perspective.otherRole || "关系人物")}</span>
              </span>
              <span class="relation-meta">
                <span>${escapeHtml(link.label || "人物关系")}</span>
                <small>${escapeHtml(link.type || "未分类")}</small>
              </span>
              <span class="relation-arrow" aria-hidden="true">→</span>
            </button>
          `;
        }).join("") || '<p class="empty-state">这个人物还没有配置关系。</p>'}
      </div>
    </section>

    <section class="character-section">
      <div class="section-title">
        <p class="label">出场剧情</p>
        <h3>${personPlots.length} 个剧情点</h3>
      </div>
      <div class="character-plot-list">
        ${personPlots.map((plot) => `
          <button
            class="${storyCardClass(plot, "character-plot detail-plot-card character-plot-card")}"
            data-plot-id="${escapeHtml(plot.id)}"
            type="button"
            style="--accent:${escapeHtml(plot.accent)}"
          >
            ${renderStoryCardContent(plot, { heading: "strong", titlePrefix: `${plot.id}. ` })}
          </button>
        `).join("")}
      </div>
    </section>
  `;

  characterDetail.querySelector(".return-to-plot-btn")?.addEventListener("click", returnToPlotContext);
  characterDetail.querySelectorAll(".character-plot-card[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  bindCharacterRename(person);
  bindCharacterScopeTools(person);
}

function temporaryCharacterPlots(person) {
  return plots.filter((plot) => plot.people.includes(person.id) || person.events.includes(plot.id));
}

function renderTemporaryCharacterArchive() {
  const visibleCharacters = characters.filter(characterVisibleInArchive);
  if (visibleCharacters.length && !visibleCharacters.some((person) => person.id === state.selectedCharacter)) {
    state.selectedCharacter = visibleCharacters[0].id;
  }

  if (!visibleCharacters.length) {
    characterDetail.innerHTML = `
      <div class="character-empty-detail">
        <strong>临时角色抽屉是空的</strong>
        <p>给人物档案加上 characterScope: 一次性角色 或 待定角色 后，就会收纳到这里。</p>
      </div>
    `;
    return;
  }

  characterDetail.innerHTML = `
    ${detailReturnButton()}
    <section class="temporary-character-archive">
      <div class="temporary-character-summary">
        <div>
          <p class="label">Temporary Cast</p>
          <h3>临时角色收纳箱</h3>
        </div>
        <span>${visibleCharacters.length} 个角色</span>
      </div>
      <div class="temporary-character-grid">
        ${visibleCharacters.map((person) => {
          const personPlots = temporaryCharacterPlots(person);
          const personLinks = relationships.filter((link) => link.from === person.id || link.to === person.id);
          return `
            <article
              class="temporary-character-card ${person.id === state.selectedCharacter ? "is-active" : ""}"
              data-character-id="${escapeHtml(person.id)}"
              style="--accent:${escapeHtml(person.color)}; --avatar-gradient:${escapeHtml(person.gradient)}"
            >
              <button class="temporary-character-select" data-character-id="${escapeHtml(person.id)}" type="button">
                <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
                <span>
                  <strong>${escapeHtml(person.name)}</strong>
                  <small>${escapeHtml(person.group || "未分组")} · ${escapeHtml(characterScopeLabel(person))}</small>
                </span>
              </button>
              <p>${escapeHtml(markdownExcerpt(person.intro, 74))}</p>
              <div class="temporary-character-meta">
                <span>${personPlots.length} 个剧情</span>
                <span>${personLinks.length} 条关系</span>
              </div>
              ${(person.aliases || []).length ? `
                <div class="temporary-character-aliases">
                  ${person.aliases.slice(0, 4).map((alias) => `<span>${escapeHtml(alias)}</span>`).join("")}
                </div>
              ` : ""}
              <div class="temporary-character-plots">
                ${personPlots.slice(0, 3).map((plot) => `
                  <button class="temporary-character-plot" data-plot-id="${escapeHtml(plot.id)}" type="button" style="--accent:${escapeHtml(plot.accent)}">
                    ${escapeHtml(plot.title)}
                  </button>
                `).join("") || '<span>还没有剧情引用</span>'}
              </div>
              <div class="temporary-character-actions">
                ${CHARACTER_SCOPE_OPTIONS
                  .filter((scope) => scope !== characterScopeLabel(person))
                  .map((scope) => `
                    <button
                      class="temporary-scope-action"
                      data-character-id="${escapeHtml(person.id)}"
                      data-scope="${escapeHtml(scope)}"
                      type="button"
                    >${escapeHtml(scope)}</button>
                  `).join("")}
              </div>
              <p class="temporary-scope-status" aria-live="polite"></p>
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `;

  characterDetail.querySelector(".return-to-plot-btn")?.addEventListener("click", returnToPlotContext);
  bindTemporaryCharacterArchive();
}

function bindTemporaryCharacterArchive() {
  characterDetail.querySelectorAll(".temporary-character-select").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedCharacter = button.dataset.characterId;
      renderCharacterList();
      renderTemporaryCharacterArchive();
    });
  });
  characterDetail.querySelectorAll(".temporary-character-plot[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  characterDetail.querySelectorAll(".temporary-scope-action").forEach((button) => {
    button.addEventListener("click", () => {
      const person = getCharacter(button.dataset.characterId);
      if (!person) return;
      const card = button.closest(".temporary-character-card");
      const status = card?.querySelector(".temporary-scope-status");
      const buttons = [...(card?.querySelectorAll(".temporary-scope-action") || [])];
      updateCharacterScope(person, button.dataset.scope || "", status, buttons);
    });
  });
}

function renderCharacterScopeTools(person) {
  const currentScope = characterScopeLabel(person);
  return `
    <div class="character-scope-tools" aria-label="${escapeHtml(person.name)}的收纳状态">
      <span class="character-scope-current">${escapeHtml(currentScope)}</span>
      <div class="character-scope-actions">
        ${CHARACTER_SCOPE_OPTIONS
          .filter((scope) => scope !== currentScope)
          .map((scope) => `
            <button
              class="character-scope-action"
              data-scope="${escapeHtml(scope)}"
              type="button"
            >${escapeHtml(scope)}</button>
          `).join("")}
      </div>
      <p class="character-scope-status" aria-live="polite"></p>
    </div>
  `;
}

async function updateCharacterScope(person, scope, status, buttons) {
  buttons.forEach((button) => {
    button.disabled = true;
  });
  if (status) {
    status.textContent = "正在更新…";
    status.className = status.classList.contains("temporary-scope-status")
      ? "temporary-scope-status"
      : "character-scope-status";
  }
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    await refactorApi("/api/characters/scope", {
      project: currentProjectId(),
      id: person.id,
      scope,
    });
    person.characterScope = scope;
    setCharacterShelfForPerson(person);
    state.selectedCharacter = person.id;
    if (status) {
      status.textContent = "已更新";
      status.className = status.classList.contains("temporary-scope-status")
        ? "temporary-scope-status is-success"
        : "character-scope-status is-success";
    }
    renderCharacterList();
    renderCharacterDetail();
    renderGraphFilters();
    renderNodes();
    renderLinks();
    markRelatedNodes();
  } catch (error) {
    if (status) {
      status.textContent = error.message;
      status.className = status.classList.contains("temporary-scope-status")
        ? "temporary-scope-status is-error"
        : "character-scope-status is-error";
    }
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

function bindCharacterScopeTools(person) {
  const scopeTools = characterDetail.querySelector(".character-scope-tools");
  if (!scopeTools) return;
  const status = scopeTools.querySelector(".character-scope-status");
  const buttons = [...scopeTools.querySelectorAll(".character-scope-action")];

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      updateCharacterScope(person, button.dataset.scope || "", status, buttons);
    });
  });
}

function bindCharacterRename(person) {
  const trigger = characterDetail.querySelector(".character-rename-trigger");
  const editor = characterDetail.querySelector(".character-rename-editor");
  const input = characterDetail.querySelector(".character-rename-input");
  const previewButton = characterDetail.querySelector(".character-rename-preview");
  const cancelButton = characterDetail.querySelector(".character-rename-cancel");
  const result = characterDetail.querySelector(".character-rename-result");
  if (!trigger || !editor || !input || !previewButton || !cancelButton || !result) return;

  const reset = () => {
    refactorOperationId = "";
    input.value = "";
    result.innerHTML = "";
    editor.classList.add("is-hidden");
    trigger.setAttribute("aria-expanded", "false");
  };

  const setBusy = (busy) => {
    input.disabled = busy;
    previewButton.disabled = busy;
    cancelButton.disabled = busy;
    result.querySelector(".character-rename-apply")?.toggleAttribute("disabled", busy);
  };

  const showError = (message) => {
    refactorOperationId = "";
    result.innerHTML = `<p class="character-rename-error">${escapeHtml(message)}</p>`;
  };

  const preview = async () => {
    const newName = input.value.trim();
    if (!newName) {
      showError("请先输入新的角色名");
      input.focus();
      return;
    }
    setBusy(true);
    try {
      await initializeRefactorWorkspace();
      if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
      const previewResult = await refactorApi("/api/refactor/preview", {
        project: currentProjectId(),
        type: "character",
        id: person.id,
        newName,
      });
      refactorOperationId = previewResult.operationId;
      result.innerHTML = `
        <div class="character-rename-confirm">
          <span>
            <strong>${escapeHtml(previewResult.oldName)} → ${escapeHtml(previewResult.newName)}</strong>
            将修改 ${previewResult.fileCount} 个文件、${previewResult.matchCount} 处引用${previewResult.moves.length ? `，并重命名 ${previewResult.moves.length} 个文件` : ""}
          </span>
          <button class="character-rename-apply" type="button">确认应用</button>
        </div>
      `;
      result.querySelector(".character-rename-apply")?.addEventListener("click", async (event) => {
        event.currentTarget.disabled = true;
        setBusy(true);
        try {
          await refactorApi("/api/refactor/apply", { operationId: refactorOperationId });
          window.location.reload();
        } catch (error) {
          showError(error.message);
          setBusy(false);
        }
      });
    } catch (error) {
      showError(error.message);
    } finally {
      setBusy(false);
    }
  };

  trigger.setAttribute("aria-expanded", "false");
  trigger.addEventListener("click", () => {
    const opening = editor.classList.contains("is-hidden");
    if (!opening) {
      reset();
      return;
    }
    editor.classList.remove("is-hidden");
    trigger.setAttribute("aria-expanded", "true");
    input.focus();
  });
  input.addEventListener("input", () => {
    refactorOperationId = "";
    result.innerHTML = "";
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") preview();
    if (event.key === "Escape") reset();
  });
  previewButton.addEventListener("click", preview);
  cancelButton.addEventListener("click", reset);
}
