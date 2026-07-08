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
      state.characterAppearanceChapter = "all";
      renderCharacterList();
      renderCharacterDetail();
      scrollPageToTop();
    });
  });
}

function characterMentionTerms(person) {
  return [person.name, ...(person.aliases || [])]
    .map((term) => String(term || "").trim())
    .filter((term, index, terms) => term && terms.indexOf(term) === index);
}

function countTermOccurrences(text, term) {
  if (!text || !term) return 0;
  const source = String(text).toLowerCase();
  const target = String(term).toLowerCase();
  let count = 0;
  let index = source.indexOf(target);
  while (index !== -1) {
    count += 1;
    index = source.indexOf(target, index + target.length);
  }
  return count;
}

function characterPlotMentionCount(plot, person) {
  const terms = characterMentionTerms(person);
  if (!terms.length) return 0;
  const searchable = [
    plot.title,
    plot.status,
    ...(plot.tags || []),
    ...(plot.lanes || []),
    plot.text,
  ].join("\n");
  return terms.reduce((total, term) => total + countTermOccurrences(searchable, term), 0);
}

function characterPlotTitleMentioned(plot, person) {
  const title = String(plot.title || "").toLowerCase();
  return characterMentionTerms(person).some((term) => title.includes(term.toLowerCase()));
}

function characterAppearanceScore(plot, person) {
  const mentionCount = characterPlotMentionCount(plot, person);
  let score = 1 + Math.min(mentionCount, 10);
  if (characterPlotTitleMentioned(plot, person)) score += 4;
  if (plot.key) score += 3;
  if (plot.climax) score += 4;
  if (plot.status === "已接入") score += 1;
  return {
    mentionCount,
    score,
  };
}

function characterAppearanceItems(person) {
  return plots
    .filter((plot) => plot.people.includes(person.id) || person.events.includes(plot.id))
    .map((plot) => ({
      plot,
      ...characterAppearanceScore(plot, person),
    }))
    .sort((a, b) => a.plot.id - b.plot.id);
}

function characterAppearanceGroups(items) {
  const order = chapterKeys();
  const groups = new Map();
  items.forEach((item) => {
    const chapter = item.plot.chapter || "unknown";
    if (!groups.has(chapter)) groups.set(chapter, []);
    groups.get(chapter).push(item);
  });
  return [...groups.entries()]
    .sort(([first], [second]) => {
      const firstIndex = order.indexOf(first);
      const secondIndex = order.indexOf(second);
      if (firstIndex !== -1 || secondIndex !== -1) {
        return (firstIndex === -1 ? 999 : firstIndex) - (secondIndex === -1 ? 999 : secondIndex);
      }
      return String(first).localeCompare(String(second), "zh-Hans-CN");
    })
    .map(([chapter, chapterItems]) => ({
      chapter,
      label: chapterName(chapter),
      items: chapterItems.sort((a, b) => a.plot.id - b.plot.id),
    }));
}

function characterAppearanceChapterOptions(items) {
  const counts = new Map();
  items.forEach((item) => {
    const chapter = item.plot.chapter || "unknown";
    counts.set(chapter, (counts.get(chapter) || 0) + 1);
  });
  const order = chapterKeys();
  return [...counts.entries()]
    .sort(([first], [second]) => {
      const firstIndex = order.indexOf(first);
      const secondIndex = order.indexOf(second);
      if (firstIndex !== -1 || secondIndex !== -1) {
        return (firstIndex === -1 ? 999 : firstIndex) - (secondIndex === -1 ? 999 : secondIndex);
      }
      return String(first).localeCompare(String(second), "zh-Hans-CN");
    })
    .map(([chapter, count]) => ({
      chapter,
      count,
      label: chapterName(chapter),
    }));
}

function representativeAppearanceItems(items) {
  const picked = new Map();
  const pick = (item) => {
    if (item) picked.set(item.plot.id, item);
  };
  const groups = characterAppearanceGroups(items);
  groups.forEach((group) => {
    pick(group.items[0]);
  });
  items
    .filter((item) => item.plot.key || item.plot.climax)
    .forEach(pick);
  items
    .slice()
    .sort((a, b) => b.score - a.score || a.plot.id - b.plot.id)
    .slice(0, 4)
    .forEach(pick);
  pick(items[items.length - 1]);
  return [...picked.values()]
    .sort((a, b) => a.plot.id - b.plot.id)
    .slice(0, 8);
}

function renderCharacterDensityMap(items) {
  const groups = characterAppearanceGroups(items);
  const maxScore = Math.max(1, ...items.map((item) => item.score));
  return `
    <div class="character-density-map" aria-label="出场分布密度条">
      ${groups.map((group) => `
        <div class="character-density-row">
          <div class="character-density-label">
            <strong>${escapeHtml(group.label)}</strong>
            <span>${group.items.length} 个</span>
          </div>
          <div class="character-density-strip">
            ${group.items.map((item) => {
              const level = Math.max(0.18, Math.min(1, item.score / maxScore));
              const height = Math.round(8 + level * 22);
              const opacity = (0.44 + level * 0.46).toFixed(2);
              return `
                <button
                  class="character-density-segment"
                  data-plot-id="${escapeHtml(item.plot.id)}"
                  type="button"
                  style="--accent:${escapeHtml(item.plot.accent)}; --bar-height:${height}px; --bar-opacity:${opacity}"
                  title="${escapeHtml(`${group.label} · ${item.plot.id}. ${item.plot.title}`)}"
                  aria-label="打开${escapeHtml(item.plot.title)}"
                >
                  <span class="character-density-bar" aria-hidden="true"></span>
                  <span class="character-density-id">${escapeHtml(item.plot.id)}</span>
                </button>
              `;
            }).join("")}
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderCharacterAppearanceSummary(person, items) {
  if (!items.length) return '<p class="empty-state">这个人物还没有出现在剧情里。</p>';
  const groups = characterAppearanceGroups(items);
  const first = items[0]?.plot;
  const latest = items[items.length - 1]?.plot;
  const strongest = items.slice().sort((a, b) => b.score - a.score || a.plot.id - b.plot.id)[0];
  return `
    <div class="character-appearance-overview">
      <div class="character-appearance-count">
        <span>出场剧情</span>
        <strong>${items.length}</strong>
        <small>个剧情点</small>
      </div>
      <div class="character-appearance-facts">
        <div>
          <span>覆盖篇章</span>
          <strong>${groups.length} 个</strong>
        </div>
        <div>
          <span>首次出场</span>
          <strong>${escapeHtml(chapterName(first.chapter))} · ${escapeHtml(first.id)}</strong>
        </div>
        <div>
          <span>最近出场</span>
          <strong>${escapeHtml(chapterName(latest.chapter))} · ${escapeHtml(latest.id)}</strong>
        </div>
        ${strongest ? `
          <div>
            <span>高密度剧情</span>
            <strong>${escapeHtml(strongest.plot.id)} · ${escapeHtml(strongest.plot.title)}</strong>
          </div>
        ` : ""}
      </div>
    </div>
  `;
}

function renderRepresentativeAppearances(items) {
  const representatives = representativeAppearanceItems(items);
  if (!representatives.length) return "";
  return `
    <div class="character-appearance-highlights">
      ${representatives.map((item) => `
        <button
          class="character-appearance-card character-appearance-plot"
          data-plot-id="${escapeHtml(item.plot.id)}"
          type="button"
          style="--accent:${escapeHtml(item.plot.accent)}"
        >
          ${renderCardRibbon(item.plot)}
          <span>${escapeHtml(chapterName(item.plot.chapter))} · ${escapeHtml(item.plot.id)} · ${item.mentionCount ? `提及 ${item.mentionCount} 次` : "自动关联"}</span>
          <strong>${escapeHtml(item.plot.title)}</strong>
          <p>${escapeHtml(plotExcerpt(item.plot))}</p>
        </button>
      `).join("")}
    </div>
  `;
}

function renderAllAppearanceList(items) {
  if (items.length <= 8) return "";
  return `
    <details class="character-appearance-all">
      <summary>查看全部 ${items.length} 个出场剧情</summary>
      <div class="character-appearance-all-list">
        ${items.map((item) => `
          <button
            class="character-appearance-row character-appearance-plot"
            data-plot-id="${escapeHtml(item.plot.id)}"
            type="button"
            style="--accent:${escapeHtml(item.plot.accent)}"
          >
            <span>${escapeHtml(item.plot.id)}</span>
            <strong>${escapeHtml(item.plot.title)}</strong>
            <small>${escapeHtml(chapterName(item.plot.chapter))}${item.mentionCount ? ` · 提及 ${item.mentionCount} 次` : ""}</small>
          </button>
        `).join("")}
      </div>
    </details>
  `;
}

function renderCharacterAppearances(person, items) {
  const options = characterAppearanceChapterOptions(items);
  const activeChapter = options.some((option) => option.chapter === state.characterAppearanceChapter)
    ? state.characterAppearanceChapter
    : "all";
  state.characterAppearanceChapter = activeChapter;
  const scopedItems = activeChapter === "all"
    ? items
    : items.filter((item) => (item.plot.chapter || "unknown") === activeChapter);
  return `
    ${options.length > 1 ? `
      <div class="character-appearance-tabs" aria-label="按篇章查看出场统计">
        <button class="character-appearance-tab ${activeChapter === "all" ? "is-active" : ""}" data-chapter="all" type="button">
          <span>全部视角</span>
          <strong>${items.length}</strong>
        </button>
        ${options.map((option) => `
          <button class="character-appearance-tab ${activeChapter === option.chapter ? "is-active" : ""}" data-chapter="${escapeHtml(option.chapter)}" type="button">
            <span>${escapeHtml(option.label)}</span>
            <strong>${option.count}</strong>
          </button>
        `).join("")}
      </div>
    ` : ""}
    ${renderCharacterAppearanceSummary(person, scopedItems)}
    ${scopedItems.length ? renderCharacterDensityMap(scopedItems) : ""}
    ${renderRepresentativeAppearances(scopedItems)}
    ${renderAllAppearanceList(scopedItems)}
  `;
}

function openPlotFromCharacterDetail(plotId, characterId = state.selectedCharacter) {
  const person = getCharacter(characterId);
  if (!person) {
    openPlotDetail(Number(plotId));
    return;
  }
  state.detailReturnContext = {
    source: "character",
    characterId: person.id,
    scrollY: window.scrollY,
  };
  openPlotDetail(Number(plotId), { preserveReturnContext: true });
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

  const appearanceItems = characterAppearanceItems(person);
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
        <h3>自动统计</h3>
      </div>
      <div class="character-appearance-panel">
        ${renderCharacterAppearances(person, appearanceItems)}
      </div>
    </section>
  `;

  characterDetail.querySelector(".return-to-plot-btn")?.addEventListener("click", returnToPlotContext);
  characterDetail.querySelectorAll(".character-appearance-tab[data-chapter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.characterAppearanceChapter = button.dataset.chapter || "all";
      renderCharacterDetail();
    });
  });
  characterDetail.querySelectorAll(".character-appearance-plot[data-plot-id], .character-density-segment[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotFromCharacterDetail(Number(button.dataset.plotId), person.id));
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
      state.characterAppearanceChapter = "all";
      renderCharacterList();
      renderTemporaryCharacterArchive();
    });
  });
  characterDetail.querySelectorAll(".temporary-character-plot[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const characterId = button.closest(".temporary-character-card")?.dataset.characterId || state.selectedCharacter;
      openPlotFromCharacterDetail(Number(button.dataset.plotId), characterId);
    });
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
