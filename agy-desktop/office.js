// Fast document generation for the agent: a finished .pptx / .docx in seconds,
// instead of clicking through PowerPoint/WPS. Same file is used by Stella Cloud and Stella on the PC.
const fs = require('fs');
const path = require('path');

const THEMES = {
  stella: { bg: 'FFFFFF', title: '1D1C1A', text: '3A3833', accent: 'D97757', soft: 'F7F6F3', font: 'Segoe UI' },
  dark: { bg: '1C1B19', title: 'F4F3EF', text: 'D8D6D0', accent: 'E8906F', soft: '262523', font: 'Segoe UI' },
  blue: { bg: 'FFFFFF', title: '14213D', text: '33415C', accent: '2563EB', soft: 'EEF3FF', font: 'Segoe UI' },
  green: { bg: 'FFFFFF', title: '123524', text: '2F4F3E', accent: '16A34A', soft: 'ECFDF3', font: 'Segoe UI' }
};

const safeName = s => String(s || 'Документ').replace(/[\\/:*?"<>|\r\n]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || 'Документ';
function uniquePath(dir, base, ext) {
  fs.mkdirSync(dir, { recursive: true });
  let p = path.join(dir, base + ext), i = 2;
  while (fs.existsSync(p)) p = path.join(dir, `${base} (${i++})${ext}`);
  return p;
}
const list = v => Array.isArray(v) ? v.map(x => String(x)).filter(Boolean) : (v ? String(v).split('\n').map(s => s.replace(/^\s*[-•*]\s*/, '').trim()).filter(Boolean) : []);

/* ------------------------------------------------------------------ */
/* presentation                                                         */
/* ------------------------------------------------------------------ */
async function createPresentation(spec, dir) {
  const PptxGenJS = require('pptxgenjs');
  const t = THEMES[spec.theme] || THEMES.stella;
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_WIDE';                       // 13.33 x 7.5 in
  pptx.title = spec.title || 'Презентация';
  pptx.author = spec.author || 'Stella';

  // title slide
  const s0 = pptx.addSlide();
  s0.background = { color: t.bg };
  s0.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 0.35, h: 7.5, fill: { color: t.accent } });
  s0.addText(spec.title || 'Презентация', { x: 0.9, y: 2.3, w: 11.5, h: 1.6, fontFace: t.font, fontSize: 44, bold: true, color: t.title, valign: 'bottom' });
  if (spec.subtitle) s0.addText(spec.subtitle, { x: 0.9, y: 4.0, w: 11.5, h: 0.9, fontFace: t.font, fontSize: 22, color: t.text });
  if (spec.author) s0.addText(spec.author, { x: 0.9, y: 6.3, w: 11.5, h: 0.5, fontFace: t.font, fontSize: 14, color: t.accent });

  const slides = Array.isArray(spec.slides) ? spec.slides.slice(0, 60) : [];
  slides.forEach((sl, i) => {
    const s = pptx.addSlide();
    s.background = { color: t.bg };
    s.addShape(pptx.ShapeType.rect, { x: 0.6, y: 0.55, w: 0.12, h: 0.75, fill: { color: t.accent } });
    s.addText(sl.title || `Слайд ${i + 1}`, { x: 0.9, y: 0.45, w: 11.8, h: 0.95, fontFace: t.font, fontSize: 30, bold: true, color: t.title, valign: 'middle' });
    const bullets = list(sl.bullets || sl.points || sl.text);
    const twoCols = bullets.length > 7;
    const make = arr => arr.map(b => ({ text: b, options: { bullet: { code: '25CF' }, paraSpaceAfter: 10 } }));
    if (twoCols) {
      const half = Math.ceil(bullets.length / 2);
      s.addText(make(bullets.slice(0, half)), { x: 0.9, y: 1.65, w: 5.8, h: 5.2, fontFace: t.font, fontSize: 18, color: t.text, valign: 'top' });
      s.addText(make(bullets.slice(half)), { x: 6.9, y: 1.65, w: 5.8, h: 5.2, fontFace: t.font, fontSize: 18, color: t.text, valign: 'top' });
    } else if (bullets.length) {
      s.addText(make(bullets), { x: 0.9, y: 1.65, w: sl.highlight ? 7.6 : 11.8, h: 5.2, fontFace: t.font, fontSize: bullets.length > 5 ? 20 : 24, color: t.text, valign: 'top' });
    }
    if (sl.highlight) {                                // a callout box: key number / quote / conclusion
      s.addShape(pptx.ShapeType.roundRect, { x: 8.8, y: 1.9, w: 3.9, h: 3.2, fill: { color: t.soft }, line: { color: t.accent, width: 1.5 }, rectRadius: 0.15 });
      s.addText(String(sl.highlight), { x: 9.0, y: 2.0, w: 3.5, h: 3.0, fontFace: t.font, fontSize: 20, bold: true, color: t.accent, align: 'center', valign: 'middle' });
    }
    s.addText(String(i + 2), { x: 12.3, y: 6.9, w: 0.6, h: 0.4, fontFace: t.font, fontSize: 11, color: t.accent, align: 'right' });
    if (sl.notes) s.addNotes(String(sl.notes));
  });

  if (spec.closing !== false) {
    const e = pptx.addSlide();
    e.background = { color: t.accent };
    e.addText(spec.closing || 'Спасибо за внимание!', { x: 0.5, y: 2.8, w: 12.3, h: 1.6, fontFace: t.font, fontSize: 40, bold: true, color: 'FFFFFF', align: 'center' });
  }
  const file = uniquePath(dir, safeName(spec.title || 'Презентация'), '.pptx');
  await pptx.writeFile({ fileName: file });
  return { file, slides: slides.length + 1 + (spec.closing !== false ? 1 : 0) };
}

/* ------------------------------------------------------------------ */
/* document (project work, essay, report, letter)                       */
/* ------------------------------------------------------------------ */
async function createDocument(spec, dir) {
  const D = require('docx');
  const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, TableOfContents, PageBreak, Footer, PageNumber } = D;
  const font = 'Times New Roman';
  const children = [];
  // title page
  if (spec.title_page !== false) {
    if (spec.organization) children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 2400 }, children: [new TextRun({ text: spec.organization, size: 28, font })] }));
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: spec.organization ? 0 : 3000, after: 300 }, children: [new TextRun({ text: spec.kind || 'Проектная работа', size: 28, font })] }));
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 2000 }, children: [new TextRun({ text: spec.title || 'Без названия', bold: true, size: 40, font })] }));
    if (spec.author) children.push(new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: 'Выполнил(а): ' + spec.author, size: 28, font })] }));
    if (spec.supervisor) children.push(new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: 'Руководитель: ' + spec.supervisor, size: 28, font })] }));
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400 }, children: [new TextRun({ text: (spec.city ? spec.city + ', ' : '') + (spec.year || new Date().getFullYear()), size: 28, font })] }));
    children.push(new Paragraph({ children: [new PageBreak()] }));
  }
  if (spec.toc !== false && (spec.sections || []).length > 2) {
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: 'Содержание', font })] }));
    children.push(new TableOfContents('Содержание', { hyperlink: true, headingStyleRange: '1-2' }));
    children.push(new Paragraph({ children: [new PageBreak()] }));
  }
  for (const sec of (spec.sections || []).slice(0, 80)) {
    if (sec.heading) children.push(new Paragraph({ heading: sec.level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_1, spacing: { before: 240, after: 160 }, children: [new TextRun({ text: String(sec.heading), font })] }));
    for (const p of list(sec.paragraphs || sec.text)) children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { firstLine: 709 }, spacing: { line: 360, after: 120 }, children: [new TextRun({ text: p, size: 28, font })] }));
    for (const b of list(sec.bullets)) children.push(new Paragraph({ bullet: { level: 0 }, spacing: { line: 360 }, children: [new TextRun({ text: b, size: 28, font })] }));
  }
  if (list(spec.references).length) {
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 160 }, children: [new TextRun({ text: 'Список литературы', font })] }));
    list(spec.references).forEach((r, i) => children.push(new Paragraph({ spacing: { line: 360 }, children: [new TextRun({ text: `${i + 1}. ${r}`, size: 28, font })] })));
  }
  const doc = new Document({
    creator: spec.author || 'Stella', title: spec.title || 'Документ',
    features: { updateFields: true },
    styles: {
      default: { document: { run: { font, size: 28 } } },
      paragraphStyles: [
        { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font, size: 32, bold: true, color: '000000' }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 240, after: 160 } } },
        { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font, size: 28, bold: true, color: '000000' }, paragraph: { spacing: { before: 200, after: 120 } } }
      ]
    },
    sections: [{
      properties: { page: { margin: { top: 1134, bottom: 1134, left: 1701, right: 850 } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font, size: 24 })] })] }) },
      children
    }]
  });
  const file = uniquePath(dir, safeName(spec.title || 'Документ'), '.docx');
  fs.writeFileSync(file, await Packer.toBuffer(doc));
  return { file, sections: (spec.sections || []).length };
}

// JSON schemas the agent sees (shared by both MCP servers)
const SCHEMAS = {
  create_presentation: {
    description: 'FAST: generate a finished PowerPoint (.pptx) in 1–2 seconds from a plan and open it — never build slides by clicking in PowerPoint/WPS. Write the full content yourself: 6–12 slides, 3–6 short bullets each, notes = what to say.',
    inputSchema: { type: 'object', properties: {
      title: { type: 'string' }, subtitle: { type: 'string' }, author: { type: 'string' },
      theme: { type: 'string', enum: ['stella', 'dark', 'blue', 'green'] },
      slides: { type: 'array', items: { type: 'object', properties: { title: { type: 'string' }, bullets: { type: 'array', items: { type: 'string' } }, highlight: { type: 'string', description: 'key number / quote shown in a box' }, notes: { type: 'string' } }, required: ['title'] } },
      closing: { type: 'string' }, open: { type: 'boolean', description: 'open it on the screen (default true)' }
    }, required: ['title', 'slides'] }
  },
  create_document: {
    description: 'FAST: generate a finished Word document (.docx): project work / essay / report with title page, table of contents, sections and references (GOST-like formatting: Times New Roman 14, 1.5 spacing). Write the full text yourself.',
    inputSchema: { type: 'object', properties: {
      title: { type: 'string' }, kind: { type: 'string', description: 'e.g. "Проектная работа", "Реферат", "Доклад"' },
      author: { type: 'string' }, supervisor: { type: 'string' }, organization: { type: 'string' }, city: { type: 'string' }, year: { type: 'string' },
      sections: { type: 'array', items: { type: 'object', properties: { heading: { type: 'string' }, level: { type: 'number' }, paragraphs: { type: 'array', items: { type: 'string' } }, bullets: { type: 'array', items: { type: 'string' } } } } },
      references: { type: 'array', items: { type: 'string' } }, title_page: { type: 'boolean' }, toc: { type: 'boolean' }, open: { type: 'boolean' }
    }, required: ['title', 'sections'] }
  }
};

module.exports = { createPresentation, createDocument, SCHEMAS };
