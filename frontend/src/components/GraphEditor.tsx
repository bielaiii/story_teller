import { useMemo, useState } from "react";
import { useProjectMutation, useRuntime } from "../api/runtime";
import type { GraphCluster, GraphDistance, GraphNode, GraphSettings } from "../api/types";
import { Icon } from "./Icon";

const defaultSettings: Required<Pick<GraphSettings,
  "node_spacing" | "initial_jitter" | "relationship_distance" | "leaf_distance_extra"
  | "center_strength" | "group_strength" | "leaf_strength"
>> = {
  node_spacing: 116,
  initial_jitter: 38,
  relationship_distance: 250,
  leaf_distance_extra: 48,
  center_strength: 1,
  group_strength: 1,
  leaf_strength: 1,
};

function optionalNumber(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

function nodeDraft(characterId: string, item?: GraphNode): GraphNode {
  return item ? { ...item } : {
    character_id: characterId,
    orbit_of: null,
    orbit_distance: null,
    orbit_angle: null,
    strength: null,
    anchor_x: null,
    anchor_y: null,
  };
}

export function GraphEditor({ onClose }: { onClose: () => void }) {
  const { snapshot } = useRuntime();
  const mutation = useProjectMutation();
  const [settings, setSettings] = useState(() => ({ ...defaultSettings, ...snapshot.graph.settings }));
  const [nodes, setNodes] = useState<GraphNode[]>(() => snapshot.characters.map((character) =>
    nodeDraft(character.entityId, snapshot.graph.nodes.find((item) => item.character_id === character.entityId)),
  ));
  const [distances, setDistances] = useState<GraphDistance[]>(() => snapshot.graph.distances.map((item) => ({ ...item })));
  const [clusters, setClusters] = useState<GraphCluster[]>(() => snapshot.graph.clusters.map((item) => ({ ...item, members: [...item.members] })));
  const [selectedNodeId, setSelectedNodeId] = useState(snapshot.characters[0]?.entityId || "");
  const [message, setMessage] = useState("");
  const characterName = useMemo(() => new Map(snapshot.characters.map((item) => [item.entityId, item.name])), [snapshot.characters]);
  const selectedNode = nodes.find((item) => item.character_id === selectedNodeId);

  const updateSetting = (key: keyof typeof defaultSettings, value: number) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };
  const updateNode = (key: keyof GraphNode, value: GraphNode[keyof GraphNode]) => {
    setNodes((current) => current.map((item) => item.character_id === selectedNodeId ? { ...item, [key]: value } : item));
  };
  const addDistance = () => {
    const available = snapshot.characters.map((item) => item.entityId);
    const pair = available.flatMap((from) => available.map((to) => [from, to] as const)).find(([from, to]) =>
      from !== to && !distances.some((item) => item.from_character_id === from && item.to_character_id === to),
    );
    if (pair) setDistances((current) => [...current, { from_character_id: pair[0], to_character_id: pair[1], distance: 250, strength: 1 }]);
  };
  const addCluster = () => setClusters((current) => [...current, {
    id: `cluster-${Date.now().toString(36)}`,
    label: `新分组 ${current.length + 1}`,
    centerX: null,
    centerY: null,
    radius: null,
    strength: 1,
    members: [],
  }]);
  const save = async () => {
    if (mutation.isPending) return;
    setMessage("");
    try {
      const result = await mutation.mutateAsync({
        path: "/graph",
        method: "PUT",
        payload: {
          nodeSpacing: settings.node_spacing,
          initialJitter: settings.initial_jitter,
          relationshipDistance: settings.relationship_distance,
          leafDistanceExtra: settings.leaf_distance_extra,
          centerStrength: settings.center_strength,
          groupStrength: settings.group_strength,
          leafStrength: settings.leaf_strength,
          nodes: nodes.map((item) => ({
            characterId: item.character_id,
            orbitOf: item.orbit_of,
            orbitDistance: item.orbit_distance,
            orbitAngle: item.orbit_angle,
            strength: item.strength,
            anchorX: item.anchor_x,
            anchorY: item.anchor_y,
          })),
          distances: distances.map((item) => ({
            fromCharacterId: item.from_character_id,
            toCharacterId: item.to_character_id,
            distance: item.distance,
            strength: item.strength,
          })),
          clusters,
        },
      });
      setMessage(result.operation.id ? "图谱布局已保存" : "图谱布局没有变化");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  };

  return <div className="dialog-backdrop editor-backdrop">
    <section className="graph-editor-dialog" role="dialog" aria-modal="true" aria-label="编辑人物图谱">
      <header><div><small>Graph Layout</small><h2>编辑人物图谱</h2><p>布局、人物锚点、距离约束与分组统一保存在 SQLite。</p></div><button className="icon-button" aria-label="关闭图谱编辑" title="关闭" onClick={onClose}><Icon name="close" /></button></header>
      <div className="graph-editor-scroll">
        <details open>
          <summary>自动布局参数</summary>
          <div className="graph-setting-grid">
            <label><span>节点间距</span><input type="number" min="40" max="500" value={settings.node_spacing} onChange={(event) => updateSetting("node_spacing", Number(event.target.value))} /></label>
            <label><span>初始扰动</span><input type="number" min="0" max="300" value={settings.initial_jitter} onChange={(event) => updateSetting("initial_jitter", Number(event.target.value))} /></label>
            <label><span>关系距离</span><input type="number" min="40" max="1000" value={settings.relationship_distance} onChange={(event) => updateSetting("relationship_distance", Number(event.target.value))} /></label>
            <label><span>叶节点追加距离</span><input type="number" min="0" max="500" value={settings.leaf_distance_extra} onChange={(event) => updateSetting("leaf_distance_extra", Number(event.target.value))} /></label>
            <label><span>中心吸引</span><input type="number" min="0" max="5" step="0.1" value={settings.center_strength} onChange={(event) => updateSetting("center_strength", Number(event.target.value))} /></label>
            <label><span>分组吸引</span><input type="number" min="0" max="5" step="0.1" value={settings.group_strength} onChange={(event) => updateSetting("group_strength", Number(event.target.value))} /></label>
            <label><span>叶节点吸引</span><input type="number" min="0" max="5" step="0.1" value={settings.leaf_strength} onChange={(event) => updateSetting("leaf_strength", Number(event.target.value))} /></label>
          </div>
        </details>
        <details open>
          <summary>人物位置与环绕</summary>
          <div className="graph-node-editor">
            <aside>{snapshot.characters.map((character) => <button key={character.entityId} className={selectedNodeId === character.entityId ? "is-active" : undefined} onClick={() => setSelectedNodeId(character.entityId)}><span style={{ background: character.color }} />{character.name}</button>)}</aside>
            {selectedNode && <div className="graph-node-fields">
              <label className="wide"><span>环绕人物</span><select value={selectedNode.orbit_of || ""} onChange={(event) => updateNode("orbit_of", event.target.value || null)}><option value="">不环绕其他人物</option>{snapshot.characters.filter((item) => item.entityId !== selectedNodeId).map((item) => <option key={item.entityId} value={item.entityId}>{item.name}</option>)}</select></label>
              <label><span>环绕距离</span><input type="number" value={selectedNode.orbit_distance ?? ""} placeholder="自动" onChange={(event) => updateNode("orbit_distance", optionalNumber(event.target.value))} /></label>
              <label><span>环绕角度（度）</span><input type="number" value={selectedNode.orbit_angle ?? ""} placeholder="自动" onChange={(event) => updateNode("orbit_angle", optionalNumber(event.target.value))} /></label>
              <label><span>锚点 X</span><input type="number" value={selectedNode.anchor_x ?? ""} placeholder="自动" onChange={(event) => updateNode("anchor_x", optionalNumber(event.target.value))} /></label>
              <label><span>锚点 Y</span><input type="number" value={selectedNode.anchor_y ?? ""} placeholder="自动" onChange={(event) => updateNode("anchor_y", optionalNumber(event.target.value))} /></label>
              <label><span>约束强度</span><input type="number" min="0" max="5" step="0.1" value={selectedNode.strength ?? ""} placeholder="默认" onChange={(event) => updateNode("strength", optionalNumber(event.target.value))} /></label>
              <button className="icon-button" aria-label={`清除${characterName.get(selectedNodeId)}的位置覆盖`} title="恢复自动布局" onClick={() => setNodes((current) => current.map((item) => item.character_id === selectedNodeId ? nodeDraft(selectedNodeId) : item))}><Icon name="restore" /></button>
            </div>}
          </div>
        </details>
        <details>
          <summary>人物距离约束 <small>{distances.length}</small></summary>
          <div className="graph-constraint-list">
            {distances.map((item, index) => <article key={`${item.from_character_id}-${item.to_character_id}-${index}`}>
              <select aria-label={`距离约束 ${index + 1} 起点`} value={item.from_character_id} onChange={(event) => setDistances((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, from_character_id: event.target.value } : entry))}>{snapshot.characters.map((character) => <option key={character.entityId} value={character.entityId} disabled={character.entityId === item.to_character_id}>{character.name}</option>)}</select>
              <select aria-label={`距离约束 ${index + 1} 终点`} value={item.to_character_id} onChange={(event) => setDistances((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, to_character_id: event.target.value } : entry))}>{snapshot.characters.map((character) => <option key={character.entityId} value={character.entityId} disabled={character.entityId === item.from_character_id}>{character.name}</option>)}</select>
              <input aria-label={`距离约束 ${index + 1} 距离`} type="number" min="20" max="2000" value={item.distance} onChange={(event) => setDistances((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, distance: Number(event.target.value) } : entry))} />
              <input aria-label={`距离约束 ${index + 1} 强度`} type="number" min="0" max="5" step="0.1" value={item.strength} onChange={(event) => setDistances((current) => current.map((entry, itemIndex) => itemIndex === index ? { ...entry, strength: Number(event.target.value) } : entry))} />
              <button className="icon-button is-danger" aria-label={`删除距离约束 ${index + 1}`} title="删除约束" onClick={() => setDistances((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Icon name="trash" /></button>
            </article>)}
            <button className="icon-button" aria-label="添加人物距离约束" title="添加距离约束" onClick={addDistance}><Icon name="plus" /></button>
          </div>
        </details>
        <details>
          <summary>视觉分组 <small>{clusters.length}</small></summary>
          <div className="graph-cluster-list">
            {clusters.map((cluster, index) => <article key={cluster.id}>
              <header><input aria-label={`分组 ${index + 1} 名称`} value={cluster.label} onChange={(event) => setClusters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, label: event.target.value } : item))} /><button className="icon-button is-danger" aria-label={`删除分组${cluster.label}`} title="删除分组" onClick={() => setClusters((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Icon name="trash" /></button></header>
              <div className="graph-cluster-numbers">
                {(["centerX", "centerY", "radius", "strength"] as const).map((key) => <label key={key}><span>{{ centerX: "中心 X", centerY: "中心 Y", radius: "半径", strength: "强度" }[key]}</span><input type="number" value={cluster[key] ?? ""} placeholder="自动" onChange={(event) => setClusters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: optionalNumber(event.target.value) } : item))} /></label>)}
              </div>
              <div className="graph-cluster-members">{snapshot.characters.map((character) => <label key={character.entityId}><input type="checkbox" checked={cluster.members.includes(character.entityId)} onChange={(event) => setClusters((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, members: event.target.checked ? [...item.members, character.entityId] : item.members.filter((id) => id !== character.entityId) } : item))} />{character.name}</label>)}</div>
            </article>)}
            <button className="icon-button" aria-label="添加图谱分组" title="添加分组" onClick={addCluster}><Icon name="plus" /></button>
          </div>
        </details>
      </div>
      <footer><span>{message || "所有调整会在一次事务中保存"}</span><button className="icon-button is-primary" aria-label="保存图谱布局" title="保存图谱布局" disabled={mutation.isPending} onClick={save}><Icon name="save" /></button></footer>
    </section>
  </div>;
}
