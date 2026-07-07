(function () {
  const FIELD_SHADER = `
    struct Uniforms {
      resolution: vec2<f32>,
      time: f32,
      nodeCount: u32,
    };

    struct FieldNode {
      position: vec2<f32>,
      radius: f32,
      strength: f32,
      color: vec4<f32>,
    };

    @group(0) @binding(0) var<uniform> uniforms: Uniforms;
    @group(0) @binding(1) var<storage, read> nodes: array<FieldNode>;

    @vertex
    fn vertexMain(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
      var positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>(3.0, -1.0),
        vec2<f32>(-1.0, 3.0)
      );
      return vec4<f32>(positions[index], 0.0, 1.0);
    }

    @fragment
    fn fragmentMain(@builtin(position) fragment: vec4<f32>) -> @location(0) vec4<f32> {
      var mixedColor = vec3<f32>(0.0);
      var total = 0.0;
      var alpha = 0.0;
      for (var index = 0u; index < uniforms.nodeCount; index += 1u) {
        let node = nodes[index];
        let pulse = 1.0 + sin(uniforms.time * 0.62 + f32(index) * 1.73) * 0.045;
        let distance = length(fragment.xy - node.position);
        let influence = exp(-pow(distance / max(1.0, node.radius * pulse), 2.0) * 2.4) * node.strength;
        mixedColor += node.color.rgb * influence;
        total += influence;
        alpha += influence * 0.19;
      }
      let color = select(vec3<f32>(0.0), mixedColor / max(total, 0.0001), total > 0.0);
      let finalAlpha = min(alpha, 0.24);
      return vec4<f32>(color * finalAlpha, finalAlpha);
    }
  `;

  const blend = {
    color: { srcFactor: "one", dstFactor: "one-minus-src-alpha" },
    alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha" },
  };

  const colorContext = document.createElement("canvas").getContext("2d");

  function colorComponents(value) {
    if (colorContext) {
      colorContext.fillStyle = "#65717d";
      colorContext.fillStyle = String(value || "#65717d");
    }
    const normalizedValue = colorContext?.fillStyle || "#65717d";
    const rgb = normalizedValue.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
    if (rgb) return rgb.slice(1, 4).map((part) => Number(part) / 255);
    const hex = normalizedValue.replace("#", "");
    const normalized = hex.length === 3
      ? [...hex].map((part) => `${part}${part}`).join("")
      : hex.padEnd(6, "0").slice(0, 6);
    return [
      Number.parseInt(normalized.slice(0, 2), 16) / 255,
      Number.parseInt(normalized.slice(2, 4), 16) / 255,
      Number.parseInt(normalized.slice(4, 6), 16) / 255,
    ];
  }

  function quadraticPoint(start, control, end, progress) {
    const inverse = 1 - progress;
    return {
      x: inverse * inverse * start.x + 2 * inverse * progress * control.x + progress * progress * end.x,
      y: inverse * inverse * start.y + 2 * inverse * progress * control.y + progress * progress * end.y,
    };
  }

  function edgeControl(start, end) {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.max(1, Math.hypot(dx, dy));
    const curve = Math.min(72, length * 0.16);
    return {
      x: (start.x + end.x) / 2 - (dy / length) * curve,
      y: (start.y + end.y) / 2 + (dx / length) * curve,
    };
  }

  function hashPhase(value) {
    let hash = 2166136261;
    for (const character of String(value)) {
      hash ^= character.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return ((hash >>> 0) / 4294967295) * Math.PI * 2;
  }

  function finitePoint(point) {
    return Number.isFinite(point?.x) && Number.isFinite(point?.y);
  }

  class GraphRenderer {
    constructor(gpuCanvas, fallbackCanvas) {
      this.gpuCanvas = gpuCanvas;
      this.fallbackCanvas = fallbackCanvas;
      this.fallbackContext = this.fallbackCanvas.getContext("2d");
      this.mode = "canvas2d";
      this.latestScene = null;
      this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      this.gpuCanvas.hidden = true;
      this.fallbackCanvas.hidden = false;
      this.fallbackCanvas.dataset.renderer = "canvas2d";
      this.initialize();
    }

    async initialize() {
      if (!navigator.gpu) {
        this.useFallback();
        return;
      }
      try {
        const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
        if (!adapter) throw new Error("No WebGPU adapter");
        this.device = await adapter.requestDevice();
        this.context = this.gpuCanvas.getContext("webgpu");
        if (!this.context) throw new Error("No WebGPU canvas context");
        this.format = navigator.gpu.getPreferredCanvasFormat();
        this.createGpuResources();
        this.device.lost.then(() => this.useFallback());
        this.mode = "webgpu";
        this.gpuCanvas.hidden = false;
        this.fallbackCanvas.hidden = false;
        this.gpuCanvas.dataset.renderer = "webgpu";
        this.fallbackCanvas.dataset.renderer = "canvas2d-edges";
        if (this.latestScene) this.render(this.latestScene);
      } catch (error) {
        console.info("WebGPU unavailable, using Canvas 2D graph renderer.", error);
        this.useFallback();
      }
    }

    createGpuResources() {
      this.uniformBuffer = this.device.createBuffer({
        size: 16,
        usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
      });
      this.fieldPipeline = this.device.createRenderPipeline({
        layout: "auto",
        vertex: {
          module: this.device.createShaderModule({ code: FIELD_SHADER }),
          entryPoint: "vertexMain",
        },
        fragment: {
          module: this.device.createShaderModule({ code: FIELD_SHADER }),
          entryPoint: "fragmentMain",
          targets: [{ format: this.format, blend }],
        },
        primitive: { topology: "triangle-list" },
      });
      this.ensureFieldBuffer(1);
    }

    useFallback() {
      this.mode = "canvas2d";
      this.gpuCanvas.hidden = true;
      this.fallbackCanvas.hidden = false;
      this.fallbackCanvas.dataset.renderer = "canvas2d";
      if (this.latestScene) this.render(this.latestScene);
    }

    ensureFieldBuffer(count) {
      const size = Math.max(32, count * 32);
      if (this.fieldBuffer && this.fieldBufferSize >= size) return;
      this.fieldBuffer?.destroy();
      this.fieldBufferSize = 2 ** Math.ceil(Math.log2(size));
      this.fieldBuffer = this.device.createBuffer({
        size: this.fieldBufferSize,
        usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
      });
      this.fieldBindGroup = this.device.createBindGroup({
        layout: this.fieldPipeline.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: { buffer: this.uniformBuffer } },
          { binding: 1, resource: { buffer: this.fieldBuffer } },
        ],
      });
    }

    resizeCanvas(canvas, width, height, ratio) {
      const pixelWidth = Math.max(1, Math.round(width * ratio));
      const pixelHeight = Math.max(1, Math.round(height * ratio));
      const changed = canvas.width !== pixelWidth || canvas.height !== pixelHeight;
      if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
      if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      return changed;
    }

    screenPoint(node, scene) {
      return {
        x: node.x * scene.scale + scene.panX,
        y: node.y * scene.scale + scene.panY,
      };
    }

    render(scene) {
      this.latestScene = scene;
      if (!scene.width || !scene.height || this.mode === "pending") return;
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      if (this.mode === "webgpu") {
        this.renderWebGpu(scene, ratio);
        this.renderCanvas(scene, ratio, false);
      }
      if (this.mode === "canvas2d") this.renderCanvas(scene, ratio, true);
    }

    renderWebGpu(scene, ratio) {
      const resized = this.resizeCanvas(this.gpuCanvas, scene.width, scene.height, ratio);
      if (resized || !this.contextConfigured) {
        this.context.configure({
          device: this.device,
          format: this.format,
          alphaMode: "premultiplied",
        });
        this.contextConfigured = true;
      }

      const time = this.reducedMotion ? 0 : scene.time / 1000;
      const fieldValues = new Float32Array(scene.nodes.length * 8);
      scene.nodes.forEach((node, index) => {
        const point = this.screenPoint(node, scene);
        if (!finitePoint(point) || !Number.isFinite(node.radius) || !Number.isFinite(node.strength)) return;
        const color = colorComponents(node.color);
        fieldValues.set([
          point.x * ratio,
          point.y * ratio,
          node.radius * ratio,
          node.strength,
          color[0], color[1], color[2], 1,
        ], index * 8);
      });
      this.ensureFieldBuffer(scene.nodes.length);
      if (fieldValues.length) this.device.queue.writeBuffer(this.fieldBuffer, 0, fieldValues);

      const uniformData = new ArrayBuffer(16);
      const uniformFloats = new Float32Array(uniformData);
      const uniformIntegers = new Uint32Array(uniformData);
      uniformFloats[0] = scene.width * ratio;
      uniformFloats[1] = scene.height * ratio;
      uniformFloats[2] = time;
      uniformIntegers[3] = scene.nodes.length;
      this.device.queue.writeBuffer(this.uniformBuffer, 0, uniformData);

      const encoder = this.device.createCommandEncoder();
      const pass = encoder.beginRenderPass({
        colorAttachments: [{
          view: this.context.getCurrentTexture().createView(),
          clearValue: { r: 0, g: 0, b: 0, a: 0 },
          loadOp: "clear",
          storeOp: "store",
        }],
      });
      pass.setPipeline(this.fieldPipeline);
      pass.setBindGroup(0, this.fieldBindGroup);
      pass.draw(3);
      pass.end();
      this.device.queue.submit([encoder.finish()]);
    }

    renderCanvas(scene, ratio, drawField) {
      this.resizeCanvas(this.fallbackCanvas, scene.width, scene.height, ratio);
      const context = this.fallbackContext;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, scene.width, scene.height);
      const time = this.reducedMotion ? 0 : scene.time / 1000;

      if (drawField) {
        scene.nodes.forEach((node, index) => {
          const point = this.screenPoint(node, scene);
          if (!finitePoint(point) || !Number.isFinite(node.radius) || !Number.isFinite(node.strength)) return;
          const radius = node.radius * (1 + Math.sin(time * 0.62 + index * 1.73) * 0.045);
          const gradient = context.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius);
          const [red, green, blue] = colorComponents(node.color).map((value) => Math.round(value * 255));
          gradient.addColorStop(0, `rgba(${red}, ${green}, ${blue}, ${node.strength * 0.16})`);
          gradient.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`);
          context.fillStyle = gradient;
          context.beginPath();
          context.arc(point.x, point.y, radius, 0, Math.PI * 2);
          context.fill();
        });
      }

      scene.edges.forEach((edge, edgeIndex) => {
        if (!edge.visible) return;
        const start = this.screenPoint(edge.from, scene);
        const end = this.screenPoint(edge.to, scene);
        if (!finitePoint(start) || !finitePoint(end)) return;
        const control = edgeControl(start, end);
        context.strokeStyle = edge.color;
        context.globalAlpha = edge.muted ? 0.1 : edge.highlighted ? 0.94 : 0.72;
        context.lineWidth = edge.highlighted ? 4.2 : 2.8;
        context.lineCap = "round";
        context.beginPath();
        context.moveTo(start.x, start.y);
        context.quadraticCurveTo(control.x, control.y, end.x, end.y);
        context.stroke();

        if (!this.reducedMotion && !edge.muted) {
          const progress = ((time * 0.18 + hashPhase(edgeIndex) / (Math.PI * 2)) % 1 + 1) % 1;
          const particle = quadraticPoint(start, control, end, progress);
          context.globalAlpha = edge.highlighted ? 0.96 : 0.82;
          context.fillStyle = edge.color;
          context.beginPath();
          context.arc(particle.x, particle.y, edge.highlighted ? 3.5 : 2.6, 0, Math.PI * 2);
          context.fill();
        }
      });
      context.globalAlpha = 1;
    }
  }

  window.GraphRenderer = GraphRenderer;
}());
