function renderPlaceList() {
  if (!placeList) return;
  const discoveredTypes = [...new Set(places.map((place) => place.type).filter(Boolean))];
  const entryTypes = [
    ...ENTRY_TYPES.filter((type) => discoveredTypes.includes(type)),
    ...discoveredTypes.filter((type) => !ENTRY_TYPES.includes(type)),
  ];
  renderChipFilter({
    container: entryTypeFilter,
    label: "类型",
    items: entryTypes,
    selected: state.entryType,
    onChange: (value) => {
      state.entryType = value;
      renderPlaceList();
      renderPlaceDetail();
    },
  });

  const entryTags = allEntryTags();
  renderChipFilter({
    container: entryTagFilter,
    label: "标签",
    items: entryTags,
    selected: state.entryTags,
    mode: "multi",
    onChange: (value) => {
      state.entryTags = nextSelectedTags(state.entryTags, entryTags, value);
      renderPlaceList();
      renderPlaceDetail();
    },
  });

  const visiblePlaces = places.filter((place) => {
    if (state.entryType !== "all" && place.type !== state.entryType) return false;
    if (!matchesSelectedTags(place.tags || [], state.entryTags, entryTags)) return false;
    if (!state.placeSearch) return true;
    const keyword = state.placeSearch.toLowerCase();
    return [
      place.name,
      place.id,
      place.type,
      place.subtype,
      place.area,
      place.intro,
      ...(place.tags || []),
      ...(place.aliases || []),
    ]
      .filter(Boolean)
      .some((text) => String(text).toLowerCase().includes(keyword));
  });

  if (visiblePlaces.length && !visiblePlaces.some((place) => place.id === state.selectedPlace)) {
    state.selectedPlace = visiblePlaces[0].id;
  }

  placeList.innerHTML = visiblePlaces
    .map((place) => `
      <button class="place-list-item ${place.id === state.selectedPlace ? "is-active" : ""}" data-id="${escapeHtml(place.id)}" type="button" style="--accent:${escapeHtml(place.accent)}">
        <span class="place-mini-symbol">${escapeHtml(place.name).slice(0, 2)}</span>
        <span>
          <strong>${escapeHtml(place.name)}</strong>
          <small>${escapeHtml(place.type || "未分类")}${place.subtype ? ` · ${escapeHtml(place.subtype)}` : ""} · ${escapeHtml(place.area || "未分区")}</small>
        </span>
      </button>
    `)
    .join("");

  if (!visiblePlaces.length) {
    placeList.innerHTML = '<p class="empty-state">没有找到匹配设定</p>';
  }

  document.querySelectorAll(".place-list-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedPlace = button.dataset.id;
      renderPlaceList();
      renderPlaceDetail();
    });
  });
}

function renderPlaceDetail() {
  if (!placeDetail) return;
  const place = getPlace(state.selectedPlace) || places[0];
  if (!place) {
    placeDetail.innerHTML = "";
    return;
  }

  const placePlots = plots.filter((plot) => (plot.entries || []).includes(place.id) || place.plots.includes(plot.id));
  const relatedPeopleIds = [...new Set([
    ...(place.people || []),
    ...placePlots.flatMap((plot) => plot.people || []),
  ])];
  const relatedPeople = relatedPeopleIds.map((id) => ({ id, person: getCharacter(id) }));

  placeDetail.innerHTML = `
    ${detailReturnButton()}
    <div class="place-hero" style="--accent:${escapeHtml(place.accent)}">
      <div class="place-symbol ${entrySymbolClass(place.type)}" aria-label="${escapeHtml(place.type || "设定")}">
        <span class="place-symbol-glyph" aria-hidden="true"></span>
        <span class="place-symbol-label">${escapeHtml(place.type || "设定")}</span>
      </div>
      <div class="character-copy">
        <p class="label">${escapeHtml(place.type || "未分类")}${place.subtype ? ` · ${escapeHtml(place.subtype)}` : ""} · ${escapeHtml(place.area || "未分区")}</p>
        <div class="entry-title-actions"><h2>${escapeHtml(place.name)}</h2><button class="entry-edit-record icon-action" type="button" aria-label="编辑${escapeHtml(place.name)}" title="编辑设定">${uiIcon("edit")}</button><button class="entry-delete-record icon-action is-danger" type="button" aria-label="删除${escapeHtml(place.name)}" title="删除设定">${uiIcon("trash")}</button></div>
        <div class="place-intro">${renderMarkdownBody(place.intro)}</div>
        <div class="place-facts">
          ${(place.tags || []).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
          ${(place.aliases || []).map((alias) => `<span>别名：${escapeHtml(alias)}</span>`).join("")}
          ${place.status ? `<span>${escapeHtml(place.status)}</span>` : ""}
        </div>
      </div>
    </div>

    <section class="character-section">
      <div class="section-title">
        <p class="label">相关人物</p>
        <h3>${relatedPeople.filter(({ person }) => person).length} 个角色</h3>
      </div>
      <div class="place-person-grid">
        ${relatedPeople.map(({ id, person }) => {
          if (!person) {
            return `
              <div class="plot-person-item">
                <span class="mini-avatar" style="--avatar-gradient:linear-gradient(135deg, #3f7fc1, #7d6bd6)">${escapeHtml(id).slice(0, 2)}</span>
                <span>
                  <strong>${escapeHtml(id)}</strong>
                  <small>未在人物列表中</small>
                </span>
              </div>
            `;
          }
          return `
            <button class="plot-person-item" data-id="${escapeHtml(person.id)}" type="button">
              <span class="mini-avatar" style="--avatar-gradient:${escapeHtml(person.gradient)}">${avatarContent(person)}</span>
              <span>
                <strong>${escapeHtml(person.name)}</strong>
                <small>${escapeHtml(person.group || "未分组")}</small>
              </span>
            </button>
          `;
        }).join("") || '<p class="empty-state">这个设定还没有关联人物。</p>'}
      </div>
    </section>

    <section class="character-section">
      <div class="section-title">
        <p class="label">出现剧情</p>
        <h3>${placePlots.length} 个剧情点</h3>
      </div>
      <div class="character-plot-list">
        ${placePlots.map((plot) => `
          <button class="${storyCardClass(plot, "character-plot detail-plot-card place-plot-card")}" data-plot-id="${escapeHtml(plot.id)}" type="button" style="--accent:${escapeHtml(plot.accent)}">
            ${renderStoryCardContent(plot, { heading: "strong", titlePrefix: `${plotSequence(plot)}. ` })}
          </button>
        `).join("") || '<p class="empty-state">这个设定还没有配置出现剧情。</p>'}
      </div>
    </section>
  `;

  document.querySelectorAll(".place-person-grid .plot-person-item[data-id]").forEach((button) => {
    button.addEventListener("click", () => openCharacterDetail(button.dataset.id, {
      preserveReturnContext: Boolean(state.detailReturnContext),
    }));
  });
  document.querySelectorAll(".place-plot-card[data-plot-id]").forEach((button) => {
    button.addEventListener("click", () => openPlotDetail(Number(button.dataset.plotId)));
  });
  placeDetail.querySelector(".return-to-plot-btn")?.addEventListener("click", returnToPlotContext);
  placeDetail.querySelector(".entry-edit-record")?.addEventListener("click", () => openContentEditor("entry", place));
  placeDetail.querySelector(".entry-delete-record")?.addEventListener("click", () => deleteContentRecord("entry", place));
}
