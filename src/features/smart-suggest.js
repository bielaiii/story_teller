const SMART_SUGGEST_LIMIT = 8;
const SMART_SUGGEST_QUERY_LIMIT = 40;
const smartSuggestBindings = new WeakMap();
const smartSuggestPinyinCache = new Map();
let smartSuggestActive = null;
let smartSuggestPopover = null;

function smartSuggestNormalize(value) {
  return String(value || "").trim().toLocaleLowerCase("zh-CN");
}

function smartSuggestEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function smartSuggestIcon(name) {
  const paths = name === "person"
    ? '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>'
    : '<path d="M4 7h6l2 2h8v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/><path d="M4 7V5a2 2 0 0 1 2-2h4l2 2"/>';
  return `<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

function smartSuggestCandidates(trigger) {
  if (trigger === "@") {
    return characters.map((person, index) => ({
      key: `character:${person.id}`,
      kind: "character",
      id: person.id,
      name: String(person.name || "").trim(),
      aliases: (person.aliases || []).map(String).filter(Boolean),
      pinyinTerms: [person.name, ...(person.aliases || [])].map(String).filter(Boolean),
      pinyinMode: "surname",
      searchTerms: [person.name, ...(person.aliases || []), person.group, person.narrativeRole],
      type: "人物",
      detail: [person.group, person.narrativeRole, `ID ${person.id}`].filter(Boolean).join(" · "),
      order: Number(person.mainPlotImpact || 0) * -100 - index,
    })).filter((item) => item.name);
  }

  return places.map((place, index) => ({
    key: `entry:${place.id}`,
    kind: "entry",
    id: place.id,
    name: String(place.name || "").trim(),
    aliases: (place.aliases || []).map(String).filter(Boolean),
    pinyinTerms: [place.name, ...(place.aliases || [])].map(String).filter(Boolean),
    pinyinMode: "normal",
    searchTerms: [place.name, ...(place.aliases || []), place.type, place.subtype, ...(place.tags || [])],
    type: String(place.type || "设定"),
    detail: [place.type || "设定", place.subtype].filter(Boolean).join(" · "),
    order: index,
  })).filter((item) => item.name);
}

function smartSuggestPinyinValue(value, mode = "normal") {
  const cacheKey = `${mode}:${value}`;
  if (smartSuggestPinyinCache.has(cacheKey)) return smartSuggestPinyinCache.get(cacheKey);
  let result = "";
  try {
    result = window.pinyinPro?.pinyin?.(String(value || ""), {
      toneType: "none",
      mode,
      v: true,
    }) || "";
  } catch (error) {
    result = "";
  }
  result = smartSuggestNormalize(result);
  smartSuggestPinyinCache.set(cacheKey, result);
  return result;
}

function smartSuggestPinyinScore(candidate, query) {
  if (!query || !/^[a-zv]+$/i.test(query) || !window.pinyinPro?.match) return -1;
  let best = -1;
  candidate.pinyinTerms.forEach((term) => {
    try {
      const positions = window.pinyinPro.match(term, query, {
        precision: "first",
        lastPrecision: "start",
      });
      if (!positions?.length) return;
      const startsAtBeginning = positions[0] === 0;
      const isContinuous = positions.every((position, index) => index === 0 || position === positions[index - 1] + 1);
      const score = 620
        + (startsAtBeginning ? 70 : 0)
        + (isContinuous ? 25 : 0)
        - positions[0] * 4
        - positions.length;
      best = Math.max(best, score);
    } catch (error) {
      // A malformed custom term should not disable ordinary Chinese matching.
    }
  });
  return best;
}

function smartSuggestScore(candidate, query) {
  if (!query) return 1;
  const name = smartSuggestNormalize(candidate.name);
  const aliases = candidate.aliases.map(smartSuggestNormalize);
  const terms = candidate.searchTerms.map(smartSuggestNormalize).filter(Boolean);
  if (name === query) return 1000;
  if (name.startsWith(query)) return 900 - name.length;
  const exactAlias = aliases.find((term) => term === query);
  if (exactAlias) return 850;
  const aliasPrefix = aliases.find((term) => term.startsWith(query));
  if (aliasPrefix) return 800 - aliasPrefix.length;
  if (name.includes(query)) return 700 - name.indexOf(query);
  const aliasMatch = aliases.find((term) => term.includes(query));
  if (aliasMatch) return 600 - aliasMatch.indexOf(query);
  const pinyinScore = smartSuggestPinyinScore(candidate, query);
  if (pinyinScore >= 0) return pinyinScore;
  const termPrefix = terms.find((term) => term.startsWith(query));
  if (termPrefix) return 500 - termPrefix.length;
  const termMatch = terms.find((term) => term.includes(query));
  return termMatch ? 400 - termMatch.indexOf(query) : -1;
}

function smartSuggestResults(trigger, query) {
  const normalizedQuery = smartSuggestNormalize(query);
  return smartSuggestCandidates(trigger)
    .map((candidate) => ({ ...candidate, score: smartSuggestScore(candidate, normalizedQuery) }))
    .filter((candidate) => candidate.score >= 0)
    .sort((first, second) => second.score - first.score
      || first.order - second.order
      || first.name.localeCompare(second.name, "zh-CN"))
    .slice(0, SMART_SUGGEST_LIMIT);
}

function smartSuggestContext(element) {
  if (!element || element.disabled || element.readOnly) return null;
  const caret = element.selectionStart;
  if (!Number.isInteger(caret) || caret !== element.selectionEnd) return null;
  const beforeCaret = element.value.slice(0, caret);
  const atIndex = beforeCaret.lastIndexOf("@");
  const slashIndex = beforeCaret.lastIndexOf("/");
  const start = Math.max(atIndex, slashIndex);
  if (start < 0) return null;

  const trigger = beforeCaret[start];
  const query = beforeCaret.slice(start + 1);
  if (query.length > SMART_SUGGEST_QUERY_LIMIT || /[\s@/#，。！？；：、（）()【】\[\]{}<>《》“”"'`~!$%^&*+=|?,.;:\\]/.test(query)) return null;

  const previous = beforeCaret[start - 1] || "";
  if (trigger === "@" && /[a-zA-Z0-9._%+-]/.test(previous)) return null;
  if (trigger === "/" && /[a-zA-Z0-9._:/\\-]/.test(previous)) return null;
  return { trigger, query, start, end: caret };
}

function smartSuggestPhysicalLetter(event) {
  if (event.metaKey || event.ctrlKey || event.altKey) return "";
  if (/^[a-z]$/i.test(String(event.key || ""))) return event.key.toLocaleLowerCase("en-US");
  const match = /^Key([A-Z])$/.exec(String(event.code || ""));
  return match ? match[1].toLocaleLowerCase("en-US") : "";
}

function replaceSmartSuggestText(element, start, end, text, inputType = "insertText") {
  element.setRangeText(text, start, end, "end");
  element.dispatchEvent(new InputEvent("input", {
    bubbles: true,
    inputType,
    data: text || null,
  }));
}

function smartSuggestCaretRect(element) {
  const rect = element.getBoundingClientRect();
  const computed = getComputedStyle(element);
  const caret = element.selectionStart || 0;

  if (element instanceof HTMLInputElement) {
    const canvas = smartSuggestCaretRect.canvas || (smartSuggestCaretRect.canvas = document.createElement("canvas"));
    const context = canvas.getContext("2d");
    context.font = computed.font;
    const textWidth = context.measureText(element.value.slice(0, caret)).width;
    const left = rect.left + parseFloat(computed.borderLeftWidth || 0) + parseFloat(computed.paddingLeft || 0) + textWidth - element.scrollLeft;
    return { left, top: rect.bottom, bottom: rect.bottom };
  }

  const mirror = document.createElement("div");
  const marker = document.createElement("span");
  const properties = [
    "boxSizing", "width", "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "fontStyle", "fontVariant", "fontWeight",
    "fontStretch", "fontSize", "fontFamily", "lineHeight", "letterSpacing", "textTransform", "textAlign",
    "textIndent", "textDecoration", "wordSpacing", "tabSize", "direction", "wordBreak", "overflowWrap",
  ];
  mirror.style.position = "fixed";
  mirror.style.left = `${rect.left}px`;
  mirror.style.top = `${rect.top}px`;
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.overflow = "hidden";
  properties.forEach((property) => { mirror.style[property] = computed[property]; });
  mirror.textContent = element.value.slice(0, caret);
  marker.textContent = element.value.slice(caret, caret + 1) || "\u200b";
  mirror.append(marker);
  document.body.append(mirror);
  const markerRect = marker.getBoundingClientRect();
  mirror.remove();
  const top = markerRect.top - element.scrollTop;
  return { left: markerRect.left - element.scrollLeft, top, bottom: top + parseFloat(computed.lineHeight || computed.fontSize || 18) };
}

function smartSuggestHost(element) {
  return element.closest("dialog") || document.body;
}

function ensureSmartSuggestPopover(element) {
  if (!smartSuggestPopover) {
    smartSuggestPopover = document.createElement("section");
    smartSuggestPopover.id = "smartSuggestPopover";
    smartSuggestPopover.className = "smart-suggest-popover";
    smartSuggestPopover.setAttribute("role", "listbox");
    smartSuggestPopover.setAttribute("aria-label", "智能提示");
    smartSuggestPopover.setAttribute("tabindex", "-1");
    smartSuggestPopover.addEventListener("keydown", handleSmartSuggestCaptureKey);
  }
  const host = smartSuggestHost(element);
  if (smartSuggestPopover.parentElement !== host) host.append(smartSuggestPopover);
  return smartSuggestPopover;
}

function positionSmartSuggestPopover(element) {
  if (!smartSuggestPopover || smartSuggestPopover.hidden) return;
  const caret = smartSuggestCaretRect(element);
  const margin = 12;
  const gap = 7;
  smartSuggestPopover.style.left = "0px";
  smartSuggestPopover.style.top = "0px";
  const menuRect = smartSuggestPopover.getBoundingClientRect();
  let left = Math.min(caret.left, window.innerWidth - menuRect.width - margin);
  let top = caret.bottom + gap;
  if (top + menuRect.height > window.innerHeight - margin) top = caret.top - menuRect.height - gap;
  left = Math.max(margin, left);
  top = Math.max(margin, Math.min(top, window.innerHeight - menuRect.height - margin));
  smartSuggestPopover.style.left = `${left}px`;
  smartSuggestPopover.style.top = `${top}px`;
}

function closeSmartSuggestions(element = smartSuggestActive?.element) {
  if (smartSuggestPopover) {
    smartSuggestPopover.hidden = true;
    smartSuggestPopover.innerHTML = "";
  }
  if (element) {
    element.classList.remove("is-smart-suggest-capturing");
    element.setAttribute("aria-expanded", "false");
    element.removeAttribute("aria-activedescendant");
  }
  smartSuggestPopover?.removeAttribute("aria-activedescendant");
  smartSuggestActive = null;
}

function smartSuggestMatchedAlias(candidate, query) {
  const normalized = smartSuggestNormalize(query);
  if (!normalized) return "";
  return candidate.aliases.find((alias) => smartSuggestNormalize(alias).includes(normalized)) || "";
}

function smartSuggestMatchDetail(candidate, query) {
  const alias = smartSuggestMatchedAlias(candidate, query);
  if (alias) return `别名：${alias}`;
  if (/^[a-zv]+$/i.test(String(query || "")) && smartSuggestPinyinScore(candidate, smartSuggestNormalize(query)) >= 0) {
    const pinyin = smartSuggestPinyinValue(candidate.name, candidate.pinyinMode);
    if (pinyin) return `拼音：${pinyin}`;
  }
  return candidate.detail;
}

function renderSmartSuggestions(element, context, results, activeIndex = 0) {
  const popover = ensureSmartSuggestPopover(element);
  const hasResults = results.length > 0;
  const safeIndex = hasResults ? Math.max(0, Math.min(activeIndex, results.length - 1)) : -1;
  const label = context.trigger === "@" ? "人物" : "设定与名词";
  popover.innerHTML = `
    <header class="smart-suggest-head">
      <span><kbd>${smartSuggestEscape(context.trigger)}</kbd>${label}</span>
      <small>直接输入拼音 · 空格/Enter 插入</small>
    </header>
    <div class="smart-suggest-options">
      ${hasResults ? results.map((candidate, index) => {
        const detail = smartSuggestMatchDetail(candidate, context.query);
        return `
          <div class="smart-suggest-option ${index === safeIndex ? "is-active" : ""}" id="smart-suggest-option-${index}" role="option" aria-selected="${index === safeIndex}" data-smart-suggest-index="${index}">
            <span class="smart-suggest-icon">${smartSuggestIcon(candidate.kind === "character" ? "person" : "entry")}</span>
            <span class="smart-suggest-copy"><strong>${smartSuggestEscape(candidate.name)}</strong><small>${smartSuggestEscape(detail)}</small></span>
            <span class="smart-suggest-type">${smartSuggestEscape(candidate.type)}</span>
          </div>
        `;
      }).join("") : '<p class="smart-suggest-empty">没有匹配项，退格可继续修改</p>'}
    </div>
  `;
  popover.hidden = false;
  element.classList.add("is-smart-suggest-capturing");
  element.setAttribute("aria-expanded", "true");
  element.setAttribute("aria-controls", popover.id);
  if (hasResults) {
    element.setAttribute("aria-activedescendant", `smart-suggest-option-${safeIndex}`);
    popover.setAttribute("aria-activedescendant", `smart-suggest-option-${safeIndex}`);
  } else {
    element.removeAttribute("aria-activedescendant");
    popover.removeAttribute("aria-activedescendant");
  }
  smartSuggestActive = { element, context, results, activeIndex: safeIndex };
  popover.querySelectorAll("[data-smart-suggest-index]").forEach((option) => {
    option.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      selectSmartSuggestion(Number(option.dataset.smartSuggestIndex));
    });
  });
  positionSmartSuggestPopover(element);
  popover.focus({ preventScroll: true });
}

function updateSmartSuggestions(element) {
  const binding = smartSuggestBindings.get(element);
  const captureFocused = smartSuggestActive?.element === element && document.activeElement === smartSuggestPopover;
  if (!binding || binding.composing || (document.activeElement !== element && !captureFocused)) return;
  const context = smartSuggestContext(element);
  if (!context) {
    if (smartSuggestActive?.element === element) closeSmartSuggestions(element);
    return;
  }
  const results = smartSuggestResults(context.trigger, context.query);
  renderSmartSuggestions(element, context, results, 0);
}

function syncSmartSuggestionReference(element, candidate) {
  const form = element.closest("form");
  if (!form) return;
  let select = null;
  if (form.id === "plotCreateForm") {
    select = form.querySelector(candidate.kind === "character" ? "#plotCreatePeople" : "#plotCreateEntries");
  } else if (form.id === "contentEditorForm" && form.dataset.kind === "entry" && candidate.kind === "character") {
    select = form.querySelector("#cePeople");
  }
  const option = [...(select?.options || [])].find((item) => String(item.value) === String(candidate.id));
  if (!option) return;
  option.selected = true;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function selectSmartSuggestion(index = smartSuggestActive?.activeIndex ?? 0) {
  if (!smartSuggestActive) return;
  const { element, context, results } = smartSuggestActive;
  const candidate = results[index];
  if (!candidate) return;
  const before = element.value.slice(0, context.start);
  const after = element.value.slice(context.end);
  element.value = `${before}${candidate.name}${after}`;
  const caret = before.length + candidate.name.length;
  element.setSelectionRange(caret, caret);
  syncSmartSuggestionReference(element, candidate);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new CustomEvent("smart-suggest-select", {
    bubbles: true,
    detail: { kind: candidate.kind, id: candidate.id, name: candidate.name },
  }));
  closeSmartSuggestions(element);
  element.focus({ preventScroll: true });
}

function moveSmartSuggestionSelection(offset) {
  if (!smartSuggestActive) return;
  const { element, context, results, activeIndex } = smartSuggestActive;
  if (!results.length) return;
  const nextIndex = (activeIndex + offset + results.length) % results.length;
  renderSmartSuggestions(element, context, results, nextIndex);
  smartSuggestPopover?.querySelector(`#smart-suggest-option-${nextIndex}`)?.scrollIntoView({ block: "nearest" });
}

function restoreSmartSuggestEditorFocus(element) {
  element.focus({ preventScroll: true });
}

function handleSmartSuggestCaptureKey(event) {
  if (!smartSuggestActive || event.currentTarget !== smartSuggestPopover) return;
  const { element, context, results } = smartSuggestActive;
  const physicalLetter = smartSuggestPhysicalLetter(event);
  if (physicalLetter) {
    event.preventDefault();
    replaceSmartSuggestText(element, context.end, context.end, physicalLetter);
    return;
  }
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    moveSmartSuggestionSelection(event.key === "ArrowDown" ? 1 : -1);
    return;
  }
  if ((event.key === "Enter" || event.key === " " || event.key === "Tab") && results.length) {
    event.preventDefault();
    selectSmartSuggestion();
    return;
  }
  if (event.key === "Backspace") {
    event.preventDefault();
    const removeStart = context.query ? context.end - 1 : context.start;
    replaceSmartSuggestText(element, removeStart, context.end, "", "deleteContentBackward");
    if (!context.query) restoreSmartSuggestEditorFocus(element);
    return;
  }
  if (event.key === "Escape" || event.key === "Tab") {
    event.preventDefault();
    closeSmartSuggestions(element);
    restoreSmartSuggestEditorFocus(element);
    return;
  }
  if (!event.metaKey && !event.ctrlKey && !event.altKey && event.key.length === 1) {
    event.preventDefault();
    closeSmartSuggestions(element);
    replaceSmartSuggestText(element, context.end, context.end, event.key);
    restoreSmartSuggestEditorFocus(element);
  }
}

function attachSmartSuggestions(element) {
  if (!element || smartSuggestBindings.has(element)) return;
  const binding = { composing: false };
  smartSuggestBindings.set(element, binding);
  element.setAttribute("autocomplete", "off");
  element.setAttribute("aria-autocomplete", "list");
  element.setAttribute("aria-expanded", "false");
  element.addEventListener("compositionstart", () => {
    binding.composing = true;
    if (smartSuggestActive?.element === element) closeSmartSuggestions(element);
  });
  element.addEventListener("compositionend", () => {
    binding.composing = false;
    queueMicrotask(() => updateSmartSuggestions(element));
  });
  element.addEventListener("input", () => updateSmartSuggestions(element));
  element.addEventListener("click", () => updateSmartSuggestions(element));
  element.addEventListener("keyup", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) updateSmartSuggestions(element);
  });
  element.addEventListener("keydown", (event) => {
    if (smartSuggestActive?.element !== element) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSmartSuggestionSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSmartSuggestionSelection(-1);
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      selectSmartSuggestion();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeSmartSuggestions(element);
    }
  });
  element.addEventListener("scroll", () => {
    if (smartSuggestActive?.element === element) positionSmartSuggestPopover(element);
  }, { passive: true });
  element.addEventListener("blur", () => {
    window.setTimeout(() => {
      const captureFocused = document.activeElement === smartSuggestPopover;
      if (document.activeElement !== element && !captureFocused && smartSuggestActive?.element === element) closeSmartSuggestions(element);
    }, 0);
  });
}

function enableSmartSuggestions(root = document) {
  if (root.matches?.("[data-smart-suggest]")) attachSmartSuggestions(root);
  root.querySelectorAll?.("[data-smart-suggest]").forEach(attachSmartSuggestions);
}

window.addEventListener("resize", () => {
  if (smartSuggestActive) positionSmartSuggestPopover(smartSuggestActive.element);
});
document.addEventListener("pointerdown", (event) => {
  if (!smartSuggestActive || smartSuggestPopover?.contains(event.target) || event.target === smartSuggestActive.element) return;
  closeSmartSuggestions();
});
