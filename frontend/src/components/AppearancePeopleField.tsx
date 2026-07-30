import { useMemo, useState } from "react";
import type { Character } from "../api/types";
import { Icon } from "./Icon";

const NON_REFERENCE_TERMS = new Set(["反派"]);

function characterTerms(character: Character): string[] {
  return [character.name, ...character.aliases]
    .map((term) => term.trim())
    .filter((term) => term && !NON_REFERENCE_TERMS.has(term));
}

export function detectedCharacterIds(
  characters: Character[],
  text: string,
  explicitIds: string[] = [],
): string[] {
  const owners = new Map<string, Set<string>>();
  for (const character of characters) {
    for (const term of characterTerms(character)) {
      const key = term.toLocaleLowerCase();
      owners.set(key, new Set([...(owners.get(key) || []), character.entityId]));
    }
  }
  const explicit = new Set(explicitIds);
  return characters.flatMap((character) => {
    const matched = characterTerms(character).some((term) => {
      if (!text.includes(term)) return false;
      const termOwners = owners.get(term.toLocaleLowerCase()) || new Set<string>();
      return termOwners.size === 1 || explicit.has(character.entityId);
    });
    return matched ? [character.entityId] : [];
  });
}

export function missingAppearanceNames(names: string[], text: string): string[] {
  return names.filter((name) => !text.includes(name));
}

export function AppearancePeopleField({
  characters,
  text,
  people,
  appearanceNames,
  onPeopleChange,
  onAppearanceNamesChange,
}: {
  characters: Character[];
  text: string;
  people: string[];
  appearanceNames: string[];
  onPeopleChange: (people: string[]) => void;
  onAppearanceNamesChange: (names: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const detectedIds = useMemo(
    () => detectedCharacterIds(characters, text, people),
    [characters, people, text],
  );
  const detected = detectedIds.flatMap((identifier) => {
    const character = characters.find((item) => item.entityId === identifier);
    return character ? [character] : [];
  });
  const missing = new Set(missingAppearanceNames(appearanceNames, text));

  const add = () => {
    const name = input.trim();
    if (!name) return;
    if (!text.includes(name)) {
      setError(`“${name}”没有出现在当前正文中`);
      return;
    }
    const known = characters.filter((character) =>
      characterTerms(character).includes(name)
    );
    if (known.length > 1) {
      setError(`“${name}”对应多个人物，请在正文中使用更明确的姓名或别名`);
      return;
    }
    if (known.length === 1) {
      onPeopleChange([...new Set([...people, known[0].entityId])]);
    } else {
      onAppearanceNamesChange([...new Set([...appearanceNames, name])]);
    }
    setInput("");
    setError("");
  };

  return <div className="appearance-people-field">
    <header>
      <span><Icon name="person" /></span>
      <div>
        <strong>出场人物</strong>
        <small>已有角色会按姓名和别名自动识别</small>
      </div>
      <em>{detected.length + appearanceNames.length} 人</em>
    </header>
    <div className="appearance-people-list">
      {detected.map((character) => <span key={character.entityId}>
        <i style={{ background: character.color }}>{character.name.slice(0, 1)}</i>
        <b>{character.name}</b>
        <small>已识别</small>
      </span>)}
      {appearanceNames.map((name) => <span key={name} className={missing.has(name) ? "is-invalid" : "is-new"}>
        <i><Icon name="person-add" /></i>
        <b>{name}</b>
        <small>{missing.has(name) ? "正文中未出现" : "保存后建为临时人物"}</small>
        <button type="button" aria-label={`移除${name}`} title={`移除${name}`} onClick={() => onAppearanceNamesChange(appearanceNames.filter((item) => item !== name))}><Icon name="close" /></button>
      </span>)}
      {!detected.length && !appearanceNames.length && <p>正文中暂未识别到已建人物。</p>}
    </div>
    <div className="appearance-people-input">
      <input
        value={input}
        placeholder="输入正文中出现的新姓名"
        aria-label="新增出场人物姓名"
        onChange={(event) => { setInput(event.target.value); setError(""); }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            add();
          }
        }}
      />
      <button type="button" aria-label="添加出场人物" title="添加出场人物" onClick={add}><Icon name="plus" /></button>
    </div>
    <footer>
      <small>新姓名只有确实出现在本章正文中才能保存，并会自动进入临时人物档案。</small>
      {error && <span role="alert">{error}</span>}
    </footer>
  </div>;
}
