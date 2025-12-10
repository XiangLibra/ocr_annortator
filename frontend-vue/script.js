const { createApp, ref, reactive, watch, computed, onMounted, onUnmounted, nextTick } = Vue;

// ---- helpers shared between components ----
function stampOriginalOrder(items) {
  items.forEach(fr => {
    fr.pages.forEach(p => {
      p.words.forEach((w, idx) => {
        if (w._origOrder === undefined) w._origOrder = idx;
      });
    });
  });
}

function isOriginalWord(w) {
  return w._origOrder !== undefined && !w.isNew;
}

function sortWordsReadingOrder(words) {
  if (!words || !words.length) return [];
  const avgH = words.reduce((s, w) => s + (w.bbox?.h || 0), 0) / Math.max(1, words.length);
  const tolY = Math.max(10, avgH * 0.6);
  return [...words].sort((a, b) => {
    const aOrig = a._origOrder;
    const bOrig = b._origOrder;
    const aIsOrig = aOrig !== undefined && !a.isNew && !a._moved;
    const bIsOrig = bOrig !== undefined && !b.isNew && !b._moved;
    if (aIsOrig && bIsOrig) return aOrig - bOrig;
    const ay = (a.bbox?.y || 0) + (a.bbox?.h || 0) / 2;
    const by = (b.bbox?.y || 0) + (b.bbox?.h || 0) / 2;
    if (Math.abs(ay - by) > tolY) return ay - by;
    const ax = a.bbox?.x || 0;
    const bx = b.bbox?.x || 0;
    if (ax !== bx) return ax - bx;
    const aTie = aOrig ?? Number.POSITIVE_INFINITY;
    const bTie = bOrig ?? Number.POSITIVE_INFINITY;
    return aTie - bTie;
  });
}

function buildBeforeForDiff(fr) {
  const pagesText = [];
  fr.pages.forEach(p => {
    const originals = p.words.filter(w => isOriginalWord(w));
    const ordered = [...originals].sort((a, b) => (a._origOrder ?? 0) - (b._origOrder ?? 0));
    pagesText.push(ordered.map(w => w.text).join(" "));
  });
  return pagesText.join("\n");
}

function buildAfterForDiff(fr) {
  const pagesText = [];
  if (fr.correctedFullText && fr.correctedFullText.trim().length) {
    return fr.correctedFullText;
  }
  fr.pages.forEach(p => {
    const ordered = sortWordsReadingOrder(p.words);
    pagesText.push(ordered.map(w => (w._edited ? w._newText : w.text)).join(" "));
  });
  return pagesText.join("\n");
}

function buildHumanReadableText(fr) {
  const lines = [];
  fr.pages.forEach(p => {
    const ordered = sortWordsReadingOrder(p.words);
    const txt = ordered.map(w => (w._edited ? w._newText : w.text) || "").join(" ").trim();
    lines.push(txt);
  });
  return lines.join("\n");
}

function buildExportText(fr) {
  const lines = [];
  fr.pages.forEach(p => {
    const ordered = sortWordsReadingOrder(p.words);
    ordered.forEach(w => {
      const txt = (w._edited ? w._newText : w.text) || "";
      if (!txt.length) return;
      const x = w.bbox.x, y = w.bbox.y, ww = w.bbox.w, hh = w.bbox.h;
      const pageH = p.height;
      const cw = ww / Math.max(1, txt.length);
      for (let i = 0; i < txt.length; i++) {
        const ch = txt[i];
        const left = Math.round(x + i * cw);
        const right = Math.round(x + (i + 1) * cw);
        const top = Math.round(pageH - y);
        const bottom = Math.round(pageH - (y + hh));
        lines.push(`${ch} ${left} ${bottom} ${right} ${top} ${p.pageIndex}`);
      }
    });
  });
  return lines.join("\n");
}

async function dataUrlToBlob(dataUrl) {
  const res = await fetch(dataUrl);
  return await res.blob();
}

async function downloadZip(fr) {
  const zip = new JSZip();
  const base = fr.filename.replace(/\.[^.]+$/, "");
  zip.file(`${base}.txt`, buildExportText(fr));
  zip.file(`${base}_readable.txt`, buildHumanReadableText(fr));
  const imgFolder = zip.folder("images");
  if (imgFolder) {
    for (const p of fr.pages) {
      const blob = await dataUrlToBlob(p.imageDataUrl);
      imgFolder.file(`${base}_p${p.pageIndex}.png`, blob);
    }
  }
  const zipBlob = await zip.generateAsync({ type: "blob" });
  const url = URL.createObjectURL(zipBlob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${base}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

const TextDiff = {
  name: "TextDiff",
  props: { before: String, after: String },
  setup(props) {
    const parts = computed(() => {
      const before = props.before || "";
      const after = props.after || "";
      return Diff.diffWordsWithSpace(before, after);
    });
    return () =>
      Vue.h(
        "pre",
        { class: "text-diff gh-diff" },
        parts.value.map((p, idx) => {
          if (p.added) return Vue.h("span", { key: idx, class: "gh-inline-add" }, p.value);
          if (p.removed) return Vue.h("span", { key: idx, class: "gh-inline-del" }, p.value);
          return Vue.h("span", { key: idx, class: "gh-inline-ctx" }, p.value);
        })
      );
  },
};

const PageCanvas = {
  name: "PageCanvas",
  props: { page: { type: Object, required: true } },
  setup(props, { emit }) {
    const wrapRef = ref(null);
    const stageHost = ref(null);
    const isAdding = ref(false);
    const isModifying = ref(false);
    const selectedId = ref(null);
    const draftRect = ref(null);
    const editing = ref(null);
    const editorRef = ref(null);
    const pendingNew = ref(null);
    const containerW = ref(800);
    let stage, imageLayer, shapeLayer, uiLayer, imageNode, resizeObs;
    const rectRefs = new Map();
    let startPos = null;

    const scale = computed(() => containerW.value / props.page.width);

    function updateCursor() {
      if (!stage) return;
      stage.container().style.cursor = isModifying.value ? "move" : (isAdding.value ? "crosshair" : "default");
    }

    function updateStageSize() {
      if (!stage || !wrapRef.value) return;
      const w = wrapRef.value.clientWidth || 800;
      containerW.value = w;
      stage.width(w);
      stage.height(props.page.height * scale.value);
      if (imageNode) {
        imageNode.width(props.page.width * scale.value);
        imageNode.height(props.page.height * scale.value);
      }
      renderShapes();
    }

    function loadImage() {
      const img = new Image();
      img.src = props.page.imageDataUrl;
      img.onload = () => {
        imageNode = new Konva.Image({
          image: img,
          width: props.page.width * scale.value,
          height: props.page.height * scale.value,
        });
        imageLayer.destroyChildren();
        imageLayer.add(imageNode);
        imageLayer.draw();
      };
    }

    function openEditor(word) {
      if (!wrapRef.value) return;
      const rect = wrapRef.value.getBoundingClientRect();
      const left = rect.left + word.bbox.x * scale.value;
      const top = rect.top + word.bbox.y * scale.value;
      editing.value = {
        word,
        left,
        top,
        value: word._edited ? word._newText : word.text
      };
      nextTick(() => {
        if (editorRef.value) editorRef.value.focus();
      });
    }

    function commitDrag(word, node) {
      word.bbox.x = Math.round(node.x() / scale.value);
      word.bbox.y = Math.round(node.y() / scale.value);
      word._moved = true;
      emit("edited");
    }

    function commitTransform(word, node) {
      const sX = node.scaleX();
      const sY = node.scaleY();
      const newW = Math.max(4, node.width() * sX);
      const newH = Math.max(4, node.height() * sY);
      node.scaleX(1);
      node.scaleY(1);
      node.width(newW);
      node.height(newH);
      word.bbox.x = Math.round(node.x() / scale.value);
      word.bbox.y = Math.round(node.y() / scale.value);
      word.bbox.w = Math.max(1, Math.round(newW / scale.value));
      word.bbox.h = Math.max(1, Math.round(newH / scale.value));
      word._moved = true;
      emit("edited");
    }

    function textPos(word, displayText) {
      const x = word.bbox.x * scale.value;
      const y = word.bbox.y * scale.value;
      const ww = word.bbox.w * scale.value;
      const hh = word.bbox.h * scale.value;
      const stageW = props.page.width * scale.value;
      const fontSize = Math.max(9, Math.round(12 * scale.value));
      const roughCharW = 6 * Math.max(1, scale.value);
      const estimated = Math.max(16, (displayText || "").length * roughCharW);
      let tx = x + ww + 4;
      if (tx + estimated > stageW - 6) {
        tx = Math.max(4, x - estimated - 4);
      }
      const ty = y + hh / 2 - fontSize / 2;
      return { x: tx, y: ty, fontSize };
    }

    function renderShapes() {
      if (!shapeLayer) return;
      shapeLayer.destroyChildren();
      uiLayer.destroyChildren();
      rectRefs.clear();

      props.page.words.forEach(w => {
        const displayText = (w._edited && w._newText !== undefined) ? w._newText : w.text;
        const pos = textPos(w, displayText);
        const rect = new Konva.Rect({
          x: w.bbox.x * scale.value,
          y: w.bbox.y * scale.value,
          width: w.bbox.w * scale.value,
          height: w.bbox.h * scale.value,
          stroke: "red",
          strokeWidth: 2,
          draggable: isModifying.value,
        });
        rect.on("click", () => {
          if (isModifying.value) {
            selectedId.value = w.id;
            attachTransformer();
          } else {
            openEditor(w);
          }
        });
        rect.on("dragend", () => {
          if (isModifying.value) {
            commitDrag(w, rect);
            renderShapes();
          }
        });
        rect.on("transformend", () => {
          if (isModifying.value) {
            commitTransform(w, rect);
            renderShapes();
          }
        });
        rectRefs.set(w.id, rect);
        shapeLayer.add(rect);

        const text = new Konva.Text({
          text: displayText,
          x: pos.x,
          y: pos.y,
          fontSize: pos.fontSize,
          fill: "red",
        });
        text.on("click", () => openEditor(w));
        shapeLayer.add(text);
      });

      if (draftRect.value) {
        const pos = draftRect.value;
        const placeholder = textPos({
          bbox: { x: pos.x / scale.value, y: pos.y / scale.value, w: pos.w / scale.value, h: pos.h / scale.value }
        }, "(新增文字…)");
        const dash = new Konva.Rect({
          x: pos.x, y: pos.y, width: pos.w, height: pos.h,
          stroke: "red", dash: [6, 4], strokeWidth: 2
        });
        const text = new Konva.Text({
          text: "(新增文字…)",
          x: placeholder.x,
          y: placeholder.y,
          fontSize: placeholder.fontSize,
          fill: "red",
        });
        shapeLayer.add(dash);
        shapeLayer.add(text);
      }

      attachTransformer();
      updateCursor();
      shapeLayer.draw();
      uiLayer.draw();
    }

    function attachTransformer() {
      uiLayer.destroyChildren();
      if (isModifying.value && selectedId.value && rectRefs.get(selectedId.value)) {
        const tr = new Konva.Transformer({
          rotateEnabled: false,
          anchorSize: 7,
          boundBoxFunc: (oldBox, newBox) => {
            if (newBox.width < 6 || newBox.height < 6) return oldBox;
            return newBox;
          }
        });
        uiLayer.add(tr);
        tr.nodes([rectRefs.get(selectedId.value)]);
        uiLayer.draw();
      }
    }

    function bindStageEvents() {
      stage.on("mousedown", (e) => {
        if (e.target === stage) {
          if (isModifying.value) {
            selectedId.value = null;
            attachTransformer();
          }
        }
        if (!isAdding.value) return;
        const pos = stage.getPointerPosition();
        if (!pos) return;
        startPos = { x: pos.x, y: pos.y };
        draftRect.value = { x: pos.x, y: pos.y, w: 0, h: 0 };
      });

      stage.on("mousemove", (e) => {
        if (!isAdding.value || !startPos) return;
        const pos = stage.getPointerPosition();
        if (!pos) return;
        const sx = startPos.x;
        const sy = startPos.y;
        draftRect.value = {
          x: Math.min(sx, pos.x),
          y: Math.min(sy, pos.y),
          w: Math.abs(pos.x - sx),
          h: Math.abs(pos.y - sy),
        };
        renderShapes();
      });

      stage.on("mouseup", () => {
        if (!isAdding.value || !startPos || !draftRect.value) return;
        const bbox = {
          x: Math.round(draftRect.value.x / scale.value),
          y: Math.round(draftRect.value.y / scale.value),
          w: Math.max(1, Math.round(draftRect.value.w / scale.value)),
          h: Math.max(1, Math.round(draftRect.value.h / scale.value)),
        };
        draftRect.value = null;
        startPos = null;
        const tempWord = {
          id: `new_${Date.now()}`,
          text: "",
          conf: -1,
          bbox,
          isNew: true
        };
        pendingNew.value = tempWord;
        openEditor(tempWord);
      });
    }

    watch(() => props.page.words, () => renderShapes(), { deep: true });
    watch(() => isModifying.value, () => renderShapes());

    onMounted(() => {
      stage = new Konva.Stage({
        container: stageHost.value,
        width: containerW.value,
        height: props.page.height * scale.value,
      });
      imageLayer = new Konva.Layer();
      shapeLayer = new Konva.Layer();
      uiLayer = new Konva.Layer();
      stage.add(imageLayer);
      stage.add(shapeLayer);
      stage.add(uiLayer);
      loadImage();
      bindStageEvents();
      renderShapes();
      nextTick(updateStageSize);
      if (window.ResizeObserver) {
        resizeObs = new ResizeObserver(() => updateStageSize());
        if (wrapRef.value) resizeObs.observe(wrapRef.value);
      }
    });

    onUnmounted(() => {
      if (resizeObs) resizeObs.disconnect();
      if (stage) stage.destroy();
    });

    return {
      wrapRef,
      stageHost,
      isAdding,
      isModifying,
      selectedId,
      editing,
      editorRef,
      toggleAdd() {
        isAdding.value = !isAdding.value;
        if (isAdding.value) {
          isModifying.value = false;
          selectedId.value = null;
        }
        renderShapes();
      },
      toggleModify() {
        isModifying.value = !isModifying.value;
        if (isModifying.value) {
          isAdding.value = false;
          draftRect.value = null;
        } else {
          selectedId.value = null;
        }
        renderShapes();
      },
      draftRect,
      saveEdit(event) {
        if (!editing.value) return;
        const value = (event.target.value || "").trim();
        const word = editing.value.word;
        if (pendingNew.value === word) {
          if (value) {
            word.text = value;
            props.page.words.push(word);
            emit("edited");
          }
          pendingNew.value = null;
        } else {
          word._edited = true;
          word._newText = value;
          emit("edited");
        }
        editing.value = null;
        renderShapes();
      },
      cancelEdit() {
        editing.value = null;
        pendingNew.value = null;
        renderShapes();
      }
    };
  },
  template: `
    <div class="page-canvas" ref="wrapRef">
      <div class="page-toolbar">
        <button type="button" @click="toggleAdd" :class="{active:isAdding}">
          {{ isAdding ? "🟥 新增框（開啟）" : "🟥 新增框" }}
        </button>
        <button type="button" @click="toggleModify" :class="{active:isModifying}">
          {{ isModifying ? "🛠 修改框（開啟）" : "🛠 修改框" }}
        </button>
        <span class="hint">
          {{ isModifying ? "拖動或縮放紅框；點框可選取後再拖曳。"
                         : "開啟後在畫面拖曳即可畫出新紅框並輸入文字。" }}
        </span>
      </div>
      <div class="stage-box" ref="stageHost" style="min-height: 60px;"></div>
      <input
        v-if="editing"
        ref="editorRef"
        class="floating-input"
        :style="{ left: editing.left + 'px', top: (editing.top - 30) + 'px' }"
        :value="editing.value"
        @blur="saveEdit"
        @keydown.enter.prevent="saveEdit"
        @keydown.esc.prevent="cancelEdit"
      />
    </div>
  `
};

// ---- root app ----
createApp({
  components: { PageCanvas, TextDiff },
  setup() {
    const apiBase = ref("http://127.0.0.1:8000");
    const language = ref("繁體中文");
    const loading = ref(false);
    const items = ref([]);
    const baselines = ref({});
    const diffs = ref({});
    const exportReady = ref({});
    const fileInput = ref(null);

    async function handleUpload() {
      if (!fileInput.value || !fileInput.value.files.length) return;
      const data = new FormData();
      for (const f of fileInput.value.files) data.append("files", f);
      data.append("language", language.value);
      loading.value = true;
      try {
        const res = await axios.post(apiBase.value + "/api/ocr", data);
        const list = JSON.parse(JSON.stringify(res.data.items || []));
        const initialDiffs = {};
        stampOriginalOrder(list);
        list.forEach(fr => {
          fr.correctedFullText = null;
          const base = buildBeforeForDiff(fr);
          baselines.value[fr.fileId] = base;
          initialDiffs[fr.fileId] = { before: base, after: base };
        });
        items.value = list;
        diffs.value = initialDiffs;
        exportReady.value = {};
      } finally {
        loading.value = false;
      }
    }

    function updateDiff(fr) {
      const before = baselines.value[fr.fileId] ?? buildBeforeForDiff(fr);
      const after = buildAfterForDiff(fr);
      diffs.value = {
        ...diffs.value,
        [fr.fileId]: { before: String(before), after: String(after) }
      };
    }

    async function handleSave(fr) {
      const edits = [];
      fr.pages.forEach(p => p.words.forEach(w => {
        if (w._edited && w._newText !== w.text) {
          edits.push({ wordId: w.id, newText: w._newText });
        }
      }));
      const form = new FormData();
      form.append("fileId", fr.fileId);
      if (fr.correctedFullText) form.append("correctedFullText", fr.correctedFullText);
      if (edits.length) form.append("wordEdits", JSON.stringify(edits));
      const res = await axios.post(apiBase.value + "/api/save", form);
      const ok = res.data?.ok;
      alert(ok ? "已儲存成功" : "儲存失敗");
      if (ok) {
        updateDiff(fr);
        exportReady.value = { ...exportReady.value, [fr.fileId]: true };
      }
    }

    async function handleDownload(fr) {
      await downloadZip(fr);
    }

    return {
      apiBase,
      language,
      loading,
      items,
      diffs,
      exportReady,
      fileInput,
      handleUpload,
      handleSave,
      handleDownload,
      updateDiff
    };
  }
}).mount("#app");
