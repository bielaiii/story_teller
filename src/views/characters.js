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

function characterNarrativeRole(person) {
  const configuredRole = String(person?.narrativeRole || "").trim();
  if (configuredRole) return configuredRole;
  const markers = new Set(characterMarkers(person));
  return ["男主", "女主", "主角", "主角团"].some((marker) => markers.has(marker)) ? "主角" : "配角";
}

function characterArchiveCategory(person) {
  return isTemporaryCharacter(person) ? characterScopeLabel(person) : characterNarrativeRole(person);
}

function characterArchiveCounts(person) {
  return {
    plots: plots.filter((plot) => plot.people.includes(person.id) || person.events.includes(plot.id)).length,
    relationships: relationships.filter((link) => link.from === person.id || link.to === person.id).length,
  };
}

function characterMatchesArchiveSearch(person) {
  if (!state.characterSearch) return true;
  return matchesKeyword(characterSearchValues(person), state.characterSearch.toLowerCase());
}

function characterVisibleInArchive(person) {
  if (!characterMatchesArchiveSearch(person)) return false;
  const shelfMatch = state.characterShelf === "temporary" ? isTemporaryCharacter(person) : !isTemporaryCharacter(person);
  const categoryMatch = state.characterCategory === "all" || characterArchiveCategory(person) === state.characterCategory;
  const groupMatch = state.characterGroup === "all" || person.group === state.characterGroup;
  return shelfMatch && categoryMatch && groupMatch;
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

function renderCharacterOverview() {
  if (!characterOverview) return;
  const mainCharacters = characters.filter((person) => !isTemporaryCharacter(person));
  const temporaryCharacters = characters.filter(isTemporaryCharacter);
  const leadCount = mainCharacters.filter((person) => characterNarrativeRole(person) === "主角").length;
  const supportingCount = mainCharacters.length - leadCount;
  const undecidedCount = temporaryCharacters.filter((person) => characterScopeLabel(person) === "待定角色").length;
  const stats = [
    { label: "全部人物", value: characters.length, note: "当前内容包", tone: "teal" },
    { label: "主角", value: leadCount, note: "核心叙事人物", tone: "blue" },
    { label: "配角", value: supportingCount, note: "长期参与人物", tone: "rose" },
    { label: "收纳角色", value: temporaryCharacters.length, note: `${undecidedCount} 个仍待确定`, tone: "gold" },
  ];
  characterOverview.innerHTML = stats.map((item) => `
    <article class="character-overview-card is-${item.tone}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${item.value}</strong>
      <small>${escapeHtml(item.note)}</small>
    </article>
  `).join("");
}

function renderCharacterManagerFilters() {
  const shelfCharacters = characters.filter((person) => (
    state.characterShelf === "temporary" ? isTemporaryCharacter(person) : !isTemporaryCharacter(person)
  ));
  const categories = state.characterShelf === "temporary"
    ? ["一次性角色", "待定角色"]
    : ["主角", "配角"];
  if (!categories.includes(state.characterCategory)) state.characterCategory = "all";
  if (characterCategoryFilter) {
    characterCategoryFilter.innerHTML = ["all", ...categories].map((category) => {
      const label = category === "all" ? "全部" : category;
      const count = category === "all"
        ? shelfCharacters.length
        : shelfCharacters.filter((person) => characterArchiveCategory(person) === category).length;
      return `<button class="${state.characterCategory === category ? "is-active" : ""}" data-category="${escapeHtml(category)}" type="button"><span>${escapeHtml(label)}</span><strong>${count}</strong></button>`;
    }).join("");
    characterCategoryFilter.querySelectorAll("button[data-category]").forEach((button) => {
      button.addEventListener("click", () => {
        const selectedCharacter = state.selectedCharacter;
        state.characterCategory = button.dataset.category || "all";
        characterCategoryFilter.querySelectorAll("button[data-category]").forEach((item) => {
          item.classList.toggle("is-active", item === button);
        });
        renderCharacterList({ renderChrome: false });
        if (state.selectedCharacter !== selectedCharacter) renderCharacterDetail();
      });
    });
  }

  const groups = [...new Set(shelfCharacters.map((person) => person.group).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  if (!groups.includes(state.characterGroup)) state.characterGroup = "all";
  if (characterGroupArchiveFilter) {
    characterGroupArchiveFilter.innerHTML = '<option value="all">全部分组</option>' + groups
      .map((group) => `<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`)
      .join("");
    characterGroupArchiveFilter.value = state.characterGroup;
    characterGroupArchiveFilter.onchange = () => {
      const selectedCharacter = state.selectedCharacter;
      state.characterGroup = characterGroupArchiveFilter.value;
      renderCharacterList({ renderChrome: false });
      if (state.selectedCharacter !== selectedCharacter) renderCharacterDetail();
    };
  }

  characterViewSwitch?.querySelectorAll("button[data-mode]").forEach((button) => {
    const active = button.dataset.mode === state.characterViewMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
    button.onclick = () => {
      state.characterViewMode = button.dataset.mode || "cards";
      characterViewSwitch.querySelectorAll("button[data-mode]").forEach((item) => {
        const itemActive = item === button;
        item.classList.toggle("is-active", itemActive);
        item.setAttribute("aria-pressed", String(itemActive));
      });
      renderCharacterList({ renderChrome: false });
    };
  });
  if (characterLibraryTitle) characterLibraryTitle.textContent = state.characterShelf === "temporary" ? "临时角色收纳箱" : "长期人物库";
}

function syncCharacterListSelection() {
  characterList?.querySelectorAll(".character-list-item").forEach((button) => {
    const active = button.dataset.id === state.selectedCharacter;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "true" : "false");
  });
}

function renderCharacterList({ renderChrome = true } = {}) {
  if (renderChrome) {
    renderTemporaryCharacterToggle();
    renderCharacterOverview();
    renderCharacterManagerFilters();
  }
  const visibleCharacters = characters.filter(characterVisibleInArchive);

  if (visibleCharacters.length && !visibleCharacters.some((person) => person.id === state.selectedCharacter)) {
    state.selectedCharacter = visibleCharacters[0].id;
  }
  if (!visibleCharacters.length) {
    state.selectedCharacter = "";
  }

  if (characterVisibleCount) characterVisibleCount.textContent = String(visibleCharacters.length);
  characterList.classList.toggle("is-card-view", state.characterViewMode === "cards");
  characterList.classList.toggle("is-list-view", state.characterViewMode === "list");
  characterList.innerHTML = visibleCharacters
    .map((person) => {
      const counts = characterArchiveCounts(person);
      const category = characterArchiveCategory(person);
      return `
      <button class="character-list-item ${person.id === state.selectedCharacter ? "is-active" : ""}" data-id="${escapeHtml(person.id)}" type="button" style="--accent:${escapeHtml(person.color)}; --impact:${normalizeMainPlotImpact(person.mainPlotImpact)}%">
        <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
        <span class="character-list-copy">
          <span class="character-list-kicker"><i>${escapeHtml(category)}</i><small>ID ${escapeHtml(person.id)}</small></span>
          <strong>${escapeHtml(person.name)}</strong>
          <small>${escapeHtml(person.group || "未分组")} · ${escapeHtml(characterScopeLabel(person))}</small>
          <span class="character-list-metrics"><i>${counts.plots} 剧情</i><i>${counts.relationships} 关系</i></span>
          <span class="character-impact-track" title="主线影响 ${normalizeMainPlotImpact(person.mainPlotImpact)}"><i></i></span>
        </span>
      </button>
    `;})
    .join("");

  if (!visibleCharacters.length) {
    characterList.innerHTML = `<p class="empty-state">${state.characterShelf === "temporary" ? "当前筛选下没有临时角色" : "当前筛选下没有找到人物"}</p>`;
  }

  document.querySelectorAll(".character-list-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedCharacter = button.dataset.id;
      state.characterAppearanceChapter = "all";
      syncCharacterListSelection();
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
    .sort((a, b) => comparePlotSequence(a.plot, b.plot));
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
      items: chapterItems.sort((a, b) => comparePlotSequence(a.plot, b.plot)),
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
    .sort((a, b) => b.score - a.score || comparePlotSequence(a.plot, b.plot))
    .slice(0, 4)
    .forEach(pick);
  pick(items[items.length - 1]);
  return [...picked.values()]
    .sort((a, b) => comparePlotSequence(a.plot, b.plot))
    .slice(0, 8);
}

function renderCharacterDensityMap(items) {
  const groups = characterAppearanceGroups(items);
  const maxScore = Math.max(1, ...items.map((item) => item.score));
  return `
    <div class="character-density-head">
      <div>
        <strong>剧情参与密度</strong>
        <span>柱高综合正文提及、标题出现、关键剧情和高潮权重</span>
      </div>
      <div class="character-density-legend" aria-label="密度从低到高">
        <span>低</span><i></i><i></i><i></i><i></i><span>高</span>
      </div>
    </div>
    <div class="character-density-map" aria-label="出场剧情参与密度图">
      ${groups.map((group) => {
        const chapterDensity = group.items.reduce((total, item) => total + item.score, 0);
        const chapterHeight = Math.min(176, 78 + chapterDensity * 8);
        return `
        <div class="character-density-row">
          <div class="character-density-label">
            <strong>${escapeHtml(group.label)}</strong>
            <span>${group.items.length} 个剧情 · 篇章密度 ${chapterDensity}</span>
          </div>
          <div class="character-density-strip" style="--chapter-height:${chapterHeight}px; --chapter-density:${Math.min(100, chapterDensity * 9)}%">
            ${group.items.map((item) => {
              const level = Math.max(0.18, Math.min(1, item.score / maxScore));
              const height = Math.round(14 + level * chapterHeight * 0.44);
              const opacity = (0.44 + level * 0.46).toFixed(2);
              const densityLabel = `强度 ${item.score}${item.mentionCount ? ` · 提及 ${item.mentionCount} 次` : " · 自动关联"}`;
              return `
                <button
                  class="character-density-segment"
                  data-plot-id="${escapeHtml(item.plot.id)}"
                  data-density-title="${escapeHtml(item.plot.title)}"
                  data-density-label="${escapeHtml(densityLabel)}"
                  type="button"
                  style="--accent:${escapeHtml(item.plot.accent)}; --bar-height:${height}px; --bar-opacity:${opacity}"
                  title="${escapeHtml(`${group.label} · 第 ${plotSequence(item.plot)} 章 · ${item.plot.title} · ${densityLabel}`)}"
                  aria-label="${escapeHtml(item.plot.title)}，${escapeHtml(densityLabel)}，点击打开"
                >
                  <span class="character-density-bar" aria-hidden="true"></span>
                  <span class="character-density-id">${escapeHtml(plotSequence(item.plot))}</span>
                </button>
              `;
            }).join("")}
          </div>
        </div>
      `;}).join("")}
    </div>
  `;
}

function ensureCharacterDensityFloat() {
  let float = document.querySelector("#characterDensityFloat");
  if (float) return float;
  float = document.createElement("div");
  float.id = "characterDensityFloat";
  float.className = "character-density-float is-hidden";
  float.setAttribute("role", "tooltip");
  float.innerHTML = '<strong></strong><span></span>';
  document.body.append(float);
  return float;
}

function showCharacterDensityFloat(target) {
  const float = ensureCharacterDensityFloat();
  const rect = target.getBoundingClientRect();
  float.querySelector("strong").textContent = target.dataset.densityTitle || "剧情参与密度";
  float.querySelector("span").textContent = target.dataset.densityLabel || "";
  float.classList.remove("is-hidden");
  float.style.setProperty("--density-color", target.style.getPropertyValue("--accent") || "#3f7fc1");
  const floatRect = float.getBoundingClientRect();
  const gap = 9;
  const left = Math.max(gap, Math.min(window.innerWidth - floatRect.width - gap, rect.left + rect.width / 2 - floatRect.width / 2));
  const preferredTop = rect.top - floatRect.height - gap;
  const top = preferredTop >= gap ? preferredTop : Math.min(window.innerHeight - floatRect.height - gap, rect.bottom + gap);
  float.style.left = `${Math.round(left)}px`;
  float.style.top = `${Math.round(top)}px`;
}

function hideCharacterDensityFloat() {
  document.querySelector("#characterDensityFloat")?.classList.add("is-hidden");
}

function bindCharacterDensityFloat() {
  characterDetail.querySelectorAll(".character-density-segment").forEach((segment) => {
    segment.addEventListener("pointerenter", () => showCharacterDensityFloat(segment));
    segment.addEventListener("pointerleave", hideCharacterDensityFloat);
    segment.addEventListener("focus", () => showCharacterDensityFloat(segment));
    segment.addEventListener("blur", hideCharacterDensityFloat);
  });
}

function commaSeparatedValues(value) {
  return String(value || "")
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter((item, index, items) => item && items.indexOf(item) === index);
}

function setCharacterCreateBusy(busy) {
  characterCreateForm?.querySelectorAll("input, select, textarea, button").forEach((element) => {
    element.disabled = busy;
  });
  if (characterCreateClose) characterCreateClose.disabled = busy;
  if (characterCreateCancel) characterCreateCancel.disabled = busy;
}

function setCharacterCreateStatus(message = "", type = "") {
  if (!characterCreateStatus) return;
  characterCreateStatus.textContent = message;
  characterCreateStatus.className = type ? `is-${type}` : "";
}

async function openCharacterCreateDialog() {
  if (!characterCreateDialog || !characterCreateForm) return;
  characterCreateForm.reset();
  if (characterCreateImpact) characterCreateImpact.value = "50";
  if (characterCreateColor) characterCreateColor.value = "#3f7fc1";
  if (characterGroupSuggestions) {
    const groups = [...new Set(characters.map((person) => person.group).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-CN"));
    characterGroupSuggestions.innerHTML = groups.map((group) => `<option value="${escapeHtml(group)}"></option>`).join("");
  }
  setCharacterCreateStatus("正在连接本地内容库…");
  setCharacterCreateBusy(true);
  characterCreateDialog.showModal();
  try {
    await initializeRefactorWorkspace();
    if (!refactorCapability?.writable) throw new Error("当前页面是只读模式，请用 run.sh 启动本地服务");
    setCharacterCreateBusy(false);
    setCharacterCreateStatus("人物 ID 和文件名将在保存时自动生成。");
    characterCreateName?.focus();
  } catch (error) {
    setCharacterCreateStatus(error.message, "error");
    if (characterCreateClose) characterCreateClose.disabled = false;
    if (characterCreateCancel) characterCreateCancel.disabled = false;
  }
}

function closeCharacterCreateDialog() {
  if (!characterCreateDialog?.open) return;
  characterCreateDialog.close();
  setCharacterCreateStatus();
  setCharacterCreateBusy(false);
}

async function createCharacterFromDialog(event) {
  event.preventDefault();
  if (!characterCreateForm?.reportValidity()) return;
  setCharacterCreateBusy(true);
  setCharacterCreateStatus("正在创建人物档案…");
  try {
    const result = await refactorApi("/api/characters/create", {
      project: currentProjectId(),
      name: characterCreateName?.value.trim() || "",
      narrativeRole: characterCreateRole?.value || "配角",
      characterScope: characterCreateScope?.value || "常驻人物",
      side: characterCreateSide?.value || "中立",
      group: characterCreateGroup?.value.trim() || "",
      mainPlotImpact: Number(characterCreateImpact?.value || 50),
      color: characterCreateColor?.value || "#3f7fc1",
      aliases: commaSeparatedValues(characterCreateAliases?.value),
      markers: commaSeparatedValues(characterCreateMarkers?.value),
      intro: characterCreateIntro?.value.trim() || "",
    });
    setCharacterCreateStatus(`已创建 ${result.name}（ID ${result.id}）`, "success");
    await refreshWorkspaceDataInPlace({ characterId: result.id });
    closeCharacterCreateDialog();
  } catch (error) {
    setCharacterCreateStatus(error.message, "error");
    setCharacterCreateBusy(false);
  }
}

function renderCharacterAppearanceSummary(person, items) {
  if (!items.length) return '<p class="empty-state">这个人物还没有出现在剧情里。</p>';
  const groups = characterAppearanceGroups(items);
  const first = items[0]?.plot;
  const latest = items[items.length - 1]?.plot;
  const strongest = items.slice().sort((a, b) => b.score - a.score || comparePlotSequence(a.plot, b.plot))[0];
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
          <strong>${escapeHtml(chapterName(first.chapter))} · 第 ${escapeHtml(plotSequence(first))} 章</strong>
        </div>
        <div>
          <span>最近出场</span>
          <strong>${escapeHtml(chapterName(latest.chapter))} · 第 ${escapeHtml(plotSequence(latest))} 章</strong>
        </div>
        ${strongest ? `
          <div>
            <span>高密度剧情</span>
            <strong>第 ${escapeHtml(plotSequence(strongest.plot))} 章 · ${escapeHtml(strongest.plot.title)}</strong>
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
          <span>${escapeHtml(chapterName(item.plot.chapter))} · 第 ${escapeHtml(plotSequence(item.plot))} 章 · ${item.mentionCount ? `提及 ${item.mentionCount} 次` : "自动关联"}</span>
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
            <span>${escapeHtml(plotSequence(item.plot))}</span>
            <strong>${escapeHtml(item.plot.title)}</strong>
            <small>${escapeHtml(chapterName(item.plot.chapter))}${item.mentionCount ? ` · 提及 ${item.mentionCount} 次` : ""}</small>
          </button>
        `).join("")}
      </div>
    </details>
  `;
}

function characterAppearanceView(items) {
  const options = characterAppearanceChapterOptions(items);
  const activeChapter = options.some((option) => option.chapter === state.characterAppearanceChapter)
    ? state.characterAppearanceChapter
    : "all";
  state.characterAppearanceChapter = activeChapter;
  const scopedItems = activeChapter === "all"
    ? items
    : items.filter((item) => (item.plot.chapter || "unknown") === activeChapter);
  return { options, activeChapter, scopedItems };
}

function renderCharacterAppearanceContent(person, scopedItems) {
  return `
    ${renderCharacterAppearanceSummary(person, scopedItems)}
    ${scopedItems.length ? renderCharacterDensityMap(scopedItems) : ""}
    ${renderRepresentativeAppearances(scopedItems)}
    ${renderAllAppearanceList(scopedItems)}
  `;
}

function renderCharacterAppearances(person, items) {
  const { options, activeChapter, scopedItems } = characterAppearanceView(items);
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
    <div class="character-appearance-content">
      ${renderCharacterAppearanceContent(person, scopedItems)}
    </div>
  `;
}

function bindCharacterAppearanceContent(person) {
  characterDetail.querySelectorAll(".character-appearance-plot[data-plot-id], .character-density-segment[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => {
      hideCharacterDensityFloat();
      openPlotFromCharacterDetail(Number(button.dataset.plotId), person.id);
    });
  });
  bindCharacterDensityFloat();
}

function updateCharacterAppearancePanel(person) {
  const items = characterAppearanceItems(person);
  const { activeChapter, scopedItems } = characterAppearanceView(items);
  characterDetail.querySelectorAll(".character-appearance-tab[data-chapter]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.chapter === activeChapter);
    button.setAttribute("aria-pressed", String(button.dataset.chapter === activeChapter));
  });
  const content = characterDetail.querySelector(".character-appearance-content");
  if (content) content.innerHTML = renderCharacterAppearanceContent(person, scopedItems);
  bindCharacterAppearanceContent(person);
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
  hideCharacterDensityFloat();
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
        <p class="label">${escapeHtml(characterNarrativeRole(person))} · ${escapeHtml(person.group || "未分组")} · ${escapeHtml(characterScopeLabel(person))}</p>
        <div class="character-title-row">
          <h2>${escapeHtml(person.name)}</h2>
          <button class="character-edit-record icon-action" type="button" aria-label="编辑${escapeHtml(person.name)}的档案" title="编辑档案">${uiIcon("edit")}</button>
          <button class="character-delete-record icon-action is-danger" type="button" aria-label="删除${escapeHtml(person.name)}" title="删除人物">${uiIcon("trash")}</button>
        </div>
        ${renderBulletNotes(person.intro, "character-intro-list")}
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
            <div class="relation-row-wrap">
            <button class="relation-row" data-character-id="${escapeHtml(perspective.otherId)}" type="button" style="--accent:${escapeHtml(link.color)}" aria-label="查看${escapeHtml(other?.name || perspective.otherId)}的人物详情">
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
            <button class="relation-edit-record icon-action" data-from="${escapeHtml(link.from)}" data-to="${escapeHtml(link.to)}" type="button" aria-label="编辑与${escapeHtml(other?.name || perspective.otherId)}的关系" title="编辑人物关系">${uiIcon("edit")}</button>
            </div>
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
      updateCharacterAppearancePanel(person);
    });
  });
  bindCharacterAppearanceContent(person);
  bindCharacterScopeTools(person);
  characterDetail.querySelector(".character-edit-record")?.addEventListener("click", () => openContentEditor("character", person));
  characterDetail.querySelector(".character-delete-record")?.addEventListener("click", () => deleteContentRecord("character", person));
  characterDetail.querySelectorAll(".relation-edit-record").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const link = relationships.find((item) => item.from === button.dataset.from && item.to === button.dataset.to);
      if (link) openContentEditor("relationship", link);
    });
  });
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
      syncCharacterListSelection();
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
    renderNodes({ animate: false });
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
