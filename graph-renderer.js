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

  const LINE_SHADER = `
    struct Uniforms {
      resolution: vec2<f32>,
      time: f32,
      nodeCount: u32,
    };

    struct VertexInput {
      @location(0) position: vec2<f32>,
      @location(1) color: vec4<f32>,
      @location(2) progress: f32,
      @location(3) phase: f32,
    };

    struct VertexOutput {
      @builtin(position) position: vec4<f32>,
      @location(0) color: vec4<f32>,
      @location(1) progress: f32,
      @location(2) phase: f32,
    };

    @group(0) @binding(0) var<uniform> uniforms: Uniforms;

    @vertex
    fn vertexMain(input: VertexInput) -> VertexOutput {
      var output: VertexOutput;
      let clip = vec2<f32>(
        input.position.x / uniforms.resolution.x * 2.0 - 1.0,
        1.0 - input.position.y / uniforms.resolution.y * 2.0
      );
      output.position = vec4<f32>(clip, 0.0, 1.0);
      output.color = input.color;
      output.progress = input.progress;
      output.phase = input.phase;
      return output;
    }

    @fragment
    fn fragmentMain(input: VertexOutput) -> @location(0) vec4<f32> {
      let wave = 0.5 + 0.5 * sin(input.progress * 24.0 - uniforms.time * 2.8 + input.phase);
      let flow = pow(wave, 12.0);
      let alpha = input.color.a * (0.56 + flow * 0.44);
      let color = mix(input.color.rgb, vec3<f32>(1.0), flow * 0.38);
      return vec4<f32>(color * alpha, alpha);
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
      this.mode = "pending";
      this.latestScene = null;
      this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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
        this.fallbackCanvas.hidden = true;
        this.gpuCanvas.dataset.renderer = "webgpu";
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
      this.linePipeline = this.device.createRenderPipeline({
        layout: "auto",
        vertex: {
          module: this.device.createShaderModule({ code: LINE_SHADER }),
          entryPoint: "vertexMain",
          buffers: [{
            arrayStride: 32,
            attributes: [
              { shaderLocation: 0, offset: 0, format: "float32x2" },
              { shaderLocation: 1, offset: 8, format: "float32x4" },
              { shaderLocation: 2, offset: 24, format: "float32" },
              { shaderLocation: 3, offset: 28, format: "float32" },
            ],
          }],
        },
        fragment: {
          module: this.device.createShaderModule({ code: LINE_SHADER }),
          entryPoint: "fragmentMain",
          targets: [{ format: this.format, blend }],
        },
        primitive: { topology: "triangle-list" },
      });
      this.ensureFieldBuffer(1);
      this.ensureLineBuffer(6);
    }

    useFallback() {
      this.mode = "canvas2d";
      this.gpuCanvas.hidden = true;
      this.fallbackCanvas.hidden = false;
      this.fallbackCanvas.dataset.renderer = "canvas2d";
      this.fallbackContext = this.fallbackCanvas.getContext("2d");
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

    ensureLineBuffer(vertexCount) {
      const size = Math.max(192, vertexCount * 32);
      if (this.lineBuffer && this.lineBufferSize >= size) return;
      this.lineBuffer?.destroy();
      this.lineBufferSize = 2 ** Math.ceil(Math.log2(size));
      this.lineBuffer = this.device.createBuffer({
        size: this.lineBufferSize,
        usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
      });
      this.lineBindGroup = this.device.createBindGroup({
        layout: this.linePipeline.getBindGroupLayout(0),
        entries: [{ binding: 0, resource: { buffer: this.uniformBuffer } }],
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

    prepareLineVertices(scene, ratio) {
      const values = [];
      scene.edges.forEach((edge, edgeIndex) => {
        if (!edge.visible) return;
        const start = this.screenPoint(edge.from, scene);
        const end = this.screenPoint(edge.to, scene);
        if (!finitePoint(start) || !finitePoint(end)) return;
        const control = edgeControl(start, end);
        const color = colorComponents(edge.color);
        const alpha = edge.muted ? 0.08 : edge.highlighted ? 0.92 : 0.58;
        const thickness = (edge.highlighted ? 3.4 : 2.35) * Math.min(1.35, Math.max(0.82, scene.scale)) * ratio;
        const phase = hashPhase(`${edge.from.id}:${edge.to.id}:${edgeIndex}`);
        const segments = 26;
        for (let index = 0; index < segments; index += 1) {
          const startProgress = index / segments;
          const endProgress = (index + 1) / segments;
          const a = quadraticPoint(start, control, end, startProgress);
          const b = quadraticPoint(start, control, end, endProgress);
          a.x *= ratio;
          a.y *= ratio;
          b.x *= ratio;
          b.y *= ratio;
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const length = Math.max(0.001, Math.hypot(dx, dy));
          const nx = (-dy / length) * thickness * 0.5;
          const ny = (dx / length) * thickness * 0.5;
          const vertex = (point, side, progress) => [
            point.x + nx * side,
            point.y + ny * side,
            color[0], color[1], color[2], alpha,
            this.reducedMotion ? 0.25 : progress,
            this.reducedMotion ? 0 : phase,
          ];
          values.push(
            ...vertex(a, -1, startProgress), ...vertex(a, 1, startProgress), ...vertex(b, -1, endProgress),
            ...vertex(b, -1, endProgress), ...vertex(a, 1, startProgress), ...vertex(b, 1, endProgress),
          );
        }
      });
      return new Float32Array(values);
    }

    render(scene) {
      this.latestScene = scene;
      if (!scene.width || !scene.height || this.mode === "pending") return;
      const ratio = Math.min(2, window.devicePixelRatio || 1);
      if (this.mode === "webgpu") this.renderWebGpu(scene, ratio);
      if (this.mode === "canvas2d") this.renderCanvas(scene, ratio);
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

      const lineVertices = this.prepareLineVertices(scene, ratio);
      const vertexCount = lineVertices.length / 8;
      this.ensureLineBuffer(vertexCount);
      if (lineVertices.length) this.device.queue.writeBuffer(this.lineBuffer, 0, lineVertices);
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
      if (vertexCount) {
        pass.setPipeline(this.linePipeline);
        pass.setBindGroup(0, this.lineBindGroup);
        pass.setVertexBuffer(0, this.lineBuffer);
        pass.draw(vertexCount);
      }
      pass.end();
      this.device.queue.submit([encoder.finish()]);
    }

    renderCanvas(scene, ratio) {
      this.resizeCanvas(this.fallbackCanvas, scene.width, scene.height, ratio);
      const context = this.fallbackContext;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, scene.width, scene.height);
      const time = this.reducedMotion ? 0 : scene.time / 1000;

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

      scene.edges.forEach((edge, edgeIndex) => {
        if (!edge.visible) return;
        const start = this.screenPoint(edge.from, scene);
        const end = this.screenPoint(edge.to, scene);
        if (!finitePoint(start) || !finitePoint(end)) return;
        const control = edgeControl(start, end);
        context.strokeStyle = edge.color;
        context.globalAlpha = edge.muted ? 0.08 : edge.highlighted ? 0.86 : 0.54;
        context.lineWidth = edge.highlighted ? 3.4 : 2.35;
        context.lineCap = "round";
        context.beginPath();
        context.moveTo(start.x, start.y);
        context.quadraticCurveTo(control.x, control.y, end.x, end.y);
        context.stroke();

        if (!this.reducedMotion && !edge.muted) {
          const progress = ((time * 0.18 + hashPhase(edgeIndex) / (Math.PI * 2)) % 1 + 1) % 1;
          const particle = quadraticPoint(start, control, end, progress);
          context.globalAlpha = edge.highlighted ? 0.92 : 0.72;
          context.fillStyle = edge.color;
          context.beginPath();
          context.arc(particle.x, particle.y, edge.highlighted ? 3.2 : 2.4, 0, Math.PI * 2);
          context.fill();
        }
      });
      context.globalAlpha = 1;
    }
  }

  window.GraphRenderer = GraphRenderer;
}());
