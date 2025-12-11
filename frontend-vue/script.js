const { createApp, ref, reactive, watch, computed, onMounted, onUnmounted, nextTick } = Vue;

// Enable GFM tables and line breaks for marked, and keep default renderer methods
let markedRenderer = null;
if (window.marked?.setOptions) {
  markedRenderer = new window.marked.Renderer();
  markedRenderer.table = (header, body) => {
    const h = typeof header === "string" ? header : (header?.text ?? "");
    const b = typeof body === "string" ? body : (body?.text ?? "");
    return `<table class="gh-table"><thead>${h}</thead><tbody>${b}</tbody></table>`;
  };
  window.marked.setOptions({
    gfm: true,
    breaks: true,
    tables: true,
    smartLists: true,
    renderer: markedRenderer,
  });
}

function safeMarkdown(html) {
  const src = convertPipeTables((html || "").toString());
  try {
    return window.marked.parse(src, { renderer: markedRenderer });
  } catch (e) {
    console.error("markdown parse failed", e);
    return src;
  }
}

function normalizeText(val) {
  if (typeof val === "string") return val;
  if (val === null || val === undefined) return "";
  try {
    return JSON.stringify(val, null, 2);
  } catch {
    return String(val);
  }
}

function wrapHtmlBody(body) {
  return `
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body { font-family: "Arial","Helvetica","Noto Sans","Noto Sans TC","Microsoft JhengHei",sans-serif; white-space: pre-wrap; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #888; padding: 6px; vertical-align: top; }
    th { background: #eef3fb; }
  </style>
</head>
<body>${body}</body>
</html>`;
}

async function buildDocxFromHtml(htmlContent) {
  const html = wrapHtmlBody(htmlContent || "");
  const zip = new JSZip();
  zip.file(
    "[Content_Types].xml",
    `<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/afchunk.html" ContentType="application/xhtml+xml"/>
</Types>`
  );
  zip.folder("_rels")?.file(
    ".rels",
    `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`
  );
  zip.folder("word/_rels")?.file(
    "document.xml.rels",
    `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHtml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk" Target="afchunk.html"/>
</Relationships>`
  );
  zip.folder("word")?.file(
    "document.xml",
    `<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/2006/wordml"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 mc:Ignorable="w14 wp14">
  <w:body>
    <w:altChunk r:id="rIdHtml"/>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>`
  );
  zip.folder("word")?.file("afchunk.html", html);
  return zip.generateAsync({ type: "blob" });
}

function toPlainTextFromMarkdown(md) {
  const div = document.createElement("div");
  div.innerHTML = safeMarkdown(md);
  return div.textContent || div.innerText || "";
}

function escapeXml(s) {
  return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

async function buildDocxBlob(text) {
  const zip = new JSZip();
  zip.file(
    "[Content_Types].xml",
    `<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`
  );
  zip.folder("_rels")?.file(
    ".rels",
    `<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`
  );
  const paragraphs = (text || "").split(/\r?\n/).map(line => `<w:p><w:r><w:t>${escapeXml(line || "")}</w:t></w:r></w:p>`).join("");
  zip.folder("word")?.file(
    "document.xml",
    `<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 mc:Ignorable="w14 wp14">
  <w:body>
    ${paragraphs}
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>`
  );
  return await zip.generateAsync({ type: "blob" });
}

// Fallback: convert pipe-style tables to HTML before marked 渲染，避免模型輸出未被解析
function convertPipeTables(md) {
  const lines = (md || "").split(/\r?\n/);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const next = lines[i + 1] || "";
    const isTableStart = /^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*-[-\s|]+\|\s*$/.test(next);
    if (isTableStart) {
      // 解析表頭
      const headerCells = line.split("|").map(s => s.trim()).filter(Boolean);
      i++; // skip separator
      const rows = [];
      while (i + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[i + 1])) {
        i++;
        const cells = lines[i].split("|").map(s => s.trim()).filter(Boolean);
        rows.push(cells);
      }
      const headerHtml = headerCells.map(c => `<th>${c}</th>`).join("");
      const bodyHtml = rows
        .map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`)
        .join("");
      out.push(`<table class="gh-table"><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`);
    } else {
      out.push(line);
    }
  }
  return out.join("\n");
}

// 漸進式顯示 AI 回覆，模擬逐字輸出
function typeOutMessage(msgRef, fullText, step = 3, interval = 25) {
  if (!msgRef) return;
  const chars = Array.from(fullText || "");
  let idx = 0;
  msgRef.text = "...";
  msgRef.html = "";
  const timer = setInterval(() => {
    idx = Math.min(chars.length, idx + step);
    msgRef.text = chars.slice(0, idx).join("");
    msgRef.html = safeMarkdown(msgRef.text);
    if (idx >= chars.length) {
      clearInterval(timer);
      msgRef.streaming = false;
    }
  }, interval);
}

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
    const agents = ref([]);
    const agentMeta = reactive({});
    const compareSelected = ref([]);
    const compareResult = ref(null);
    const compareLoading = ref(false);
    const compareOriginalFinal = ref("");
    const compareEditedFinal = ref("");
    const compareEditing = ref(false);
    const compareFinalText = computed(() => normalizeText(compareEditedFinal.value || compareOriginalFinal.value || ""));
    const comparePairs = computed(() => {
      if (!compareSelected.value || compareSelected.value.length < 2) return [];
      const ids = compareSelected.value.slice(0, 2);
      return ids
        .map(id => {
          const fr = items.value.find(x => x.fileId === id);
          if (!fr) return null;
          return { name: fr.filename, text: buildAfterForDiff(fr) };
        })
        .filter(Boolean);
    });
    const uploadedNames = ref([]);
    const dropHint = ref("拖曳檔案到此（最多 2 個 PDF/圖片），或點下方按鈕選擇");
    const chatInput = ref("");
    const chatStrategy = ref("auto");
    const chatAgents = ref([]);
    const chatResult = ref(null);
    const chatUseCompare = ref(true);
    const chatContextNote = ref("");
    const chatHistory = ref([]);
    const chatSending = ref(false);
    const advancedOpen = ref(false);
    const advancedUseCustom = ref(true);
    const advancedCustomName = ref("__custom_adv_agent");
    const advancedModel = ref("gemma:1b");
    const advancedTemp = ref(0.1);
    const advancedPrompt = ref("");
    const advancedOrder = ref("文件摘要專家 - 差異分析專家 - 結構化分析專家");
    const compareDiffParts = computed(() => Diff.diffWordsWithSpace(compareOriginalFinal.value || "", compareEditedFinal.value || ""));
    const compareRendered = computed(() => safeMarkdown((compareFinalText.value || "").trim()));
    const mermaidSvg = ref("");
    const dagEdges = ref([]);
    const dagEntry = ref([]);
    const dagOutputs = ref([]);
    const dagEdgeSrc = ref("");
    const dagEdgeDst = ref("");
    const dagMermaidText = ref("");
    const dagMermaidSvg = ref("");
    let mermaidDagInited = false;
    const mermaidPreview = computed(() => {
      const steps = resolveOrder();
      if (!steps.length) return "flowchart TD\n  A[未指定]";
      if (steps.length === 1) return `flowchart TD\n  A["${steps[0]}"]`;
      const nodes = steps.map((s, i) => `  A${i}["${s}"]`).join("\n");
      const links = steps
        .slice(0, -1)
        .map((_, i) => `  A${i} --> A${i + 1}`)
        .join("\n");
      return `flowchart TD\n${nodes}\n${links}`;
    });

    let mermaidInited = false;
    function renderMermaid() {
      if (!window.mermaid) return;
      nextTick(async () => {
        try {
          if (!mermaidInited) {
            window.mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
            mermaidInited = true;
          }
          const id = `m-${Date.now()}`;
          const { svg } = await window.mermaid.render(id, mermaidPreview.value);
          mermaidSvg.value = svg;
        } catch (e) {
          console.error(e);
        }
      });
    }

    function buildDagMermaidText() {
      const lines = ["flowchart LR", "  START([入口])"];
      const idMap = new Map();
      const getId = (name) => {
        if (idMap.has(name)) return idMap.get(name);
        const id = `N${idMap.size}`;
        idMap.set(name, id);
        return id;
      };
      const allNames = new Set();
      (dagEntry.value || []).forEach(n => allNames.add(n));
      (dagOutputs.value || []).forEach(n => allNames.add(n));
      (dagEdges.value || []).forEach(e => { allNames.add(e.src); allNames.add(e.dst); });
      allNames.forEach(n => {
        const id = getId(n);
        lines.push(`  ${id}["${n}"]`);
      });
      (dagEntry.value || []).forEach(e => {
        const id = getId(e);
        lines.push(`  START --> ${id}`);
      });
      (dagEdges.value || []).forEach(e => {
        const src = getId(e.src);
        const dst = getId(e.dst);
        lines.push(`  ${src} --> ${dst}`);
      });
      if (dagOutputs.value?.length) lines.push("  END([出口])");
      (dagOutputs.value || []).forEach(o => {
        const id = getId(o);
        lines.push(`  ${id} --> END`);
      });
      if (lines.length === 2) {
        lines.push('  EMPTY["尚未新增邊"]');
        lines.push("  START --> EMPTY");
      }
      return lines.join("\n");
    }

    async function renderDagMermaid(text) {
      if (!window.mermaid) return;
      const source = text || buildDagMermaidText();
      dagMermaidText.value = source;
      nextTick(async () => {
        try {
          if (!mermaidDagInited) {
            window.mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "loose" });
            mermaidDagInited = true;
          }
          const { svg } = await window.mermaid.render(`dag-${Date.now()}`, source);
          dagMermaidSvg.value = svg;
        } catch (e) {
          console.error(e);
          dagMermaidSvg.value = `<pre style="color:#fff;">${source}</pre>`;
        }
      });
    }

    async function processFiles(fileList) {
      const files = Array.from(fileList || []);
      if (!files.length) return;
      if (files.length > 2) return alert("一次最多上傳 2 個檔案");
      const data = new FormData();
      files.forEach(f => data.append("files", f));
      data.append("language", language.value);
      uploadedNames.value = files.map(f => f.name);
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
        // 預設勾選前兩個檔案以便快速比對
        autoSelectFirstTwo(list);
      } finally {
        loading.value = false;
      }
    }

    async function handleUpload() {
      if (!fileInput.value || !fileInput.value.files.length) return;
      await processFiles(fileInput.value.files);
    }

    async function handleDrop(e) {
      e.preventDefault();
      if (e.dataTransfer?.files?.length) {
        await processFiles(e.dataTransfer.files);
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

    async function fetchAgents() {
      try {
        const res = await axios.get(apiBase.value + "/api/agents");
        agents.value = res.data || [];
        (agents.value || []).forEach(a => {
          if (!agentMeta[a.name]) {
            agentMeta[a.name] = {
              expanded: false,
              edit: {
                model: a.model,
                temperature: a.temperature,
                system_prompt: a.system_prompt
              }
            };
          } else {
            agentMeta[a.name].edit.model = a.model;
            agentMeta[a.name].edit.temperature = a.temperature;
            agentMeta[a.name].edit.system_prompt = a.system_prompt;
          }
        });
      } catch (e) {
        console.error(e);
      }
    }

    function toggleAgent(name) {
      if (!agentMeta[name]) {
        agentMeta[name] = { expanded: false, edit: { model: "llama3.2:3b", temperature: 0.1, system_prompt: "" } };
      }
      agentMeta[name].expanded = !agentMeta[name].expanded;
    }

    async function saveAgentConfig(name) {
      const meta = agentMeta[name];
      if (!meta) return;
      try {
        await axios.put(apiBase.value + `/api/agents/${encodeURIComponent(name)}`, {
          model: meta.edit.model,
          temperature: meta.edit.temperature,
          system_prompt: meta.edit.system_prompt
        });
        await fetchAgents();
        alert(`已更新 ${name}`);
      } catch (e) {
        alert("更新失敗，請稍後再試");
      }
    }

    function resolveOrder() {
      const text = advancedOrder.value || "";
      const parts = text
        .split(/->|,|-/)
        .map(s => s.trim())
        .filter(Boolean);
      if (advancedUseCustom.value && advancedPrompt.value.trim()) {
        const customName = advancedCustomName.value || "__custom_adv_agent";
        if (!parts.includes(customName)) parts.unshift(customName);
      }
      return parts;
    }

    async function ensureCustomAgent() {
      if (!advancedUseCustom.value || !advancedPrompt.value.trim()) return;
      const name = advancedCustomName.value || "__custom_adv_agent";
      try {
        if (agents.value.find(a => a.name === name)) {
          await axios.put(apiBase.value + `/api/agents/${encodeURIComponent(name)}`, {
            system_prompt: advancedPrompt.value,
            model: advancedModel.value,
            temperature: advancedTemp.value
          });
        } else {
          await axios.post(apiBase.value + "/api/agents", {
            name,
            system_prompt: advancedPrompt.value,
            model: advancedModel.value,
            temperature: advancedTemp.value
          });
        }
        await fetchAgents();
      } catch (e) {
        console.error(e);
      }
    }

    async function compareFiles() {
      if (compareSelected.value.length < 2) return alert("請至少選兩個 OCR 檔案");
      await ensureCustomAgent();
      compareLoading.value = true;
      try {
        const overrides = compareSelected.value
          .map(id => {
            const fr = items.value.find(x => x.fileId === id);
            if (!fr) return null;
            const txt = buildAfterForDiff(fr);
            return { fileId: fr.fileId, filename: fr.filename, text: txt };
          })
          .filter(Boolean);

        const res = await axios.post(apiBase.value + "/api/compare_ocr", {
          fileIds: compareSelected.value,
          overrides,
          agents: resolveOrder(),
          strategy: chatStrategy.value
        });
        compareResult.value = res.data;
        const finalTxt = res.data?.payload?.final_result ?? res.data?.payload?.result ?? "";
        compareOriginalFinal.value = finalTxt;
        compareEditedFinal.value = compareOriginalFinal.value;
        compareEditing.value = false;
      } catch (e) {
        alert("比對失敗，請稍後再試");
      } finally {
        compareLoading.value = false;
      }
    }

    async function runChat() {
      if (!chatInput.value.trim()) return alert("請輸入內容");
      try {
        await ensureCustomAgent();
        const order = resolveOrder();
        const ctx = {};
        if (chatUseCompare.value && compareResult.value) {
          ctx.compare_final = compareFinalText.value;
          ctx.compare_files = comparePairs.value?.map(p => p.name) || [];
        }
        if (chatContextNote.value?.trim()) {
          ctx.note = chatContextNote.value;
        }
        chatSending.value = true;

        // 先把使用者訊息與待回覆的 AI 氣泡放上去，避免卡住看不到
        const userMsg = { role: "user", text: chatInput.value };
        const aiMsg = { role: "ai", text: "...", html: "", streaming: true };
        chatHistory.value = [...chatHistory.value, userMsg, aiMsg];
        const userInputBackup = chatInput.value;
        chatInput.value = "";

        const res = await axios.post(apiBase.value + "/api/run", {
          input_text: userInputBackup,
          strategy: chatStrategy.value,
          agents: order.length ? order : chatAgents.value,
          context: Object.keys(ctx).length ? ctx : undefined,
        });
        chatResult.value = res.data;
        const aiText = res.data?.payload?.final_result || res.data?.payload?.result || "";
        typeOutMessage(aiMsg, aiText);
      } catch (e) {
        // 回退剛剛的 AI 氣泡內容，提示失敗
        const last = chatHistory.value[chatHistory.value.length - 1];
        if (last && last.role === "ai") {
          last.text = "⚠️ 執行失敗，請稍後再試";
          last.html = "";
          last.streaming = false;
        }
        alert("執行失敗，請稍後再試");
      } finally {
        chatSending.value = false;
      }
    }

    watch(apiBase, () => {
      fetchAgents();
    });
    function autoSelectFirstTwo(list) {
      const arr = list || [];
      if (!arr.length) return;
      compareSelected.value = arr.slice(0, 2).map(f => f.fileId);
    }
    async function loadDag() {
      try {
        const res = await axios.get(apiBase.value + "/api/dag");
        dagEdges.value = (res.data?.edges || []).map(e => ({ src: e[0], dst: e[1] }));
        dagEntry.value = res.data?.entry || [];
        dagOutputs.value = res.data?.outputs || [];
        await renderDagMermaid(res.data?.mermaid);
      } catch (e) {
        console.error(e);
      }
    }

    async function saveDag() {
      const payload = {
        edges: dagEdges.value.map(e => [e.src, e.dst]),
        entry: dagEntry.value,
        outputs: dagOutputs.value
      };
      try {
        const res = await axios.put(apiBase.value + "/api/dag", payload);
        await renderDagMermaid(res.data?.mermaid);
        alert("DAG 已儲存");
      } catch (e) {
        alert("儲存 DAG 失敗");
      }
    }

    function addDagEdge() {
      if (!dagEdgeSrc.value || !dagEdgeDst.value) return;
      const exists = dagEdges.value.some(e => e.src === dagEdgeSrc.value && e.dst === dagEdgeDst.value);
      if (exists) return;
      dagEdges.value = [...dagEdges.value, { src: dagEdgeSrc.value, dst: dagEdgeDst.value }];
      dagEdgeSrc.value = "";
      dagEdgeDst.value = "";
      renderDagMermaid();
    }

    function removeDagEdge(idx) {
      dagEdges.value.splice(idx, 1);
      dagEdges.value = [...dagEdges.value];
      renderDagMermaid();
    }

    function getCompareText() {
      const payload = compareResult.value?.payload || {};
      return normalizeText(payload.final_result || payload.result || "");
    }

    async function downloadCompare(type = "docx") {
      const text = getCompareText();
      if (!text.trim()) return alert("沒有可下載的內容");
      const htmlBody = safeMarkdown(text);
      const plain = toPlainTextFromMarkdown(text);

      if (type === "pdf" && window.jspdf?.jsPDF) {
        try {
          const { jsPDF } = window.jspdf;
          // 直接用 html2canvas 轉圖，避免字型缺失造成亂碼
          if (window.html2canvas) {
            const tmp = document.createElement("div");
            tmp.style.position = "fixed";
            tmp.style.left = "-9999px";
            tmp.style.top = "0";
            tmp.style.width = "800px";
            tmp.innerHTML = wrapHtmlBody(htmlBody);
            document.body.appendChild(tmp);
            const canvas = await window.html2canvas(tmp, { scale: 2 });
            document.body.removeChild(tmp);
            const imgData = canvas.toDataURL("image/png");
            const pdf = new jsPDF("p", "pt", "a4");
            const pageWidth = pdf.internal.pageSize.getWidth();
            const pageHeight = pdf.internal.pageSize.getHeight();
            const imgWidth = pageWidth - 60;
            const imgHeight = (canvas.height * imgWidth) / canvas.width;
            let y = 30;
            pdf.addImage(imgData, "PNG", 30, y, imgWidth, imgHeight);
            pdf.save("compare_output.pdf");
          } else {
            // fallback 純文字
            const doc = new jsPDF({ unit: "pt", format: "a4" });
            let y = 40;
            doc.setFont("helvetica", "normal");
            doc.setFontSize(12);
            plain.split(/\r?\n/).forEach(line => {
              const wrapped = doc.splitTextToSize(line || " ", 500);
              wrapped.forEach(part => {
                if (y > 780) { doc.addPage(); y = 40; }
                doc.text(part, 40, y);
                y += 18;
              });
            });
            doc.save("compare_output.pdf");
          }
          return;
        } catch (err) {
          console.error("pdf export failed", err);
          // fallback 純文字
          try {
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF({ unit: "pt", format: "a4" });
            let y = 40;
            doc.setFont("helvetica", "normal");
            doc.setFontSize(12);
            plain.split(/\r?\n/).forEach(line => {
              const wrapped = doc.splitTextToSize(line || " ", 500);
              wrapped.forEach(part => {
                if (y > 780) { doc.addPage(); y = 40; }
                doc.text(part, 40, y);
                y += 18;
              });
            });
            doc.save("compare_output.pdf");
            return;
          } catch (fallbackErr) {
            console.error("pdf fallback failed", fallbackErr);
          }
        }
      }

      // Word (docx via altChunk HTML)
      buildDocxFromHtml(htmlBody).then(blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "compare_output.docx";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      });
    }

    function downloadComparePdf() {
      downloadCompare("pdf");
    }

    watch([dagEdges, dagEntry, dagOutputs], () => renderDagMermaid(), { deep: true });
    watch(mermaidPreview, () => renderMermaid(), { flush: "post", immediate: true });
    watch(advancedOpen, (v) => { if (v) { renderMermaid(); renderDagMermaid(); } }, { flush: "post" });
    onMounted(() => { renderMermaid(); loadDag(); });
    fetchAgents();

    return {
      apiBase,
      language,
      loading,
      items,
      diffs,
      exportReady,
      fileInput,
      uploadedNames,
      dropHint,
      agents,
      compareSelected,
      compareResult,
      compareLoading,
      compareOriginalFinal,
      compareEditedFinal,
      compareEditing,
      compareFinalText,
      compareDiffParts,
      compareRendered,
      comparePairs,
      mermaidSvg,
      chatInput,
      chatStrategy,
      chatAgents,
      chatResult,
      chatUseCompare,
      chatContextNote,
      chatHistory,
      agentMeta,
      advancedOpen,
      advancedModel,
      advancedCustomName,
      advancedUseCustom,
      advancedTemp,
      advancedPrompt,
      advancedOrder,
      mermaidPreview,
      handleUpload,
      handleDrop,
      handleSave,
      handleDownload,
      updateDiff,
      compareFiles,
      runChat,
      ensureCustomAgent,
      resolveOrder,
      renderMermaid,
      toggleAgent,
      saveAgentConfig,
      downloadCompare,
      downloadComparePdf,
      addDagEdge,
      dagEdgeDst,
      dagEdgeSrc,
      dagEdges,
      dagEntry,
      dagOutputs,
      removeDagEdge,
      saveDag,
      loadDag,
      dagMermaidText,
      dagMermaidSvg
    };
  }
}).mount("#app");
