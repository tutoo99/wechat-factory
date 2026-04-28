#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  ImageRun,
  AlignmentType,
  HeadingLevel,
} = require("docx");

function usage() {
  console.error("Usage: node render_wechat_docx.js <manifest.json> <output.docx>");
  process.exit(1);
}

function createImageParagraph(filePath, width, height, altText) {
  try {
    const imageData = fs.readFileSync(filePath);
    const ext = path.extname(filePath).replace(".", "").toLowerCase();
    const imageType = ext === "png" ? "png" : ext === "gif" ? "gif" : "jpg";

    return new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 200 },
      children: [
        new ImageRun({
          type: imageType,
          data: imageData,
          transformation: { width, height },
          altText: {
            title: altText,
            description: altText,
            name: altText.replace(/\s+/g, "_"),
          },
        }),
      ],
    });
  } catch (error) {
    return new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 200 },
      children: [new TextRun({ text: `[图片缺失: ${altText}]`, italics: true, color: "999999" })],
    });
  }
}

async function main() {
  const [, , manifestPath, outputPath] = process.argv;
  if (!manifestPath || !outputPath) usage();

  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const blocks = manifest.blocks || [];

  const children = [
    new Paragraph({
      heading: HeadingLevel.TITLE,
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: manifest.title || "未命名文章", bold: true, size: 48 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 120, after: 240 },
      children: [
        new TextRun({
          text: `作者：${manifest.author || "未知"}${manifest.source_account ? `  公众号：${manifest.source_account}` : ""}`,
          italics: true,
          size: 22,
        }),
      ],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 0, after: 240 },
      children: [new TextRun({ text: manifest.link || "", color: "666666", size: 18 })],
    }),
  ];

  for (const block of blocks) {
    if (block.type === "heading") {
      children.push(
        new Paragraph({
          heading: block.level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_1,
          spacing: { before: 240, after: 120 },
          children: [new TextRun({ text: block.text, bold: true, size: block.level === 2 ? 28 : 32 })],
        })
      );
      continue;
    }

    if (block.type === "image") {
      children.push(
        createImageParagraph(
          block.local_path,
          block.width || 420,
          block.height || 280,
          block.alt || path.basename(block.local_path)
        )
      );
      continue;
    }

    if (block.type === "paragraph") {
      children.push(
        new Paragraph({
          spacing: { before: 120, after: 120 },
          children: [new TextRun({ text: block.text })],
        })
      );
    }
  }

  const doc = new Document({
    styles: {
      default: {
        document: {
          run: { font: "Arial", size: 24 },
        },
      },
      paragraphStyles: [
        {
          id: "Title",
          name: "Title",
          basedOn: "Normal",
          run: { size: 48, bold: true, color: "000000", font: "Arial" },
          paragraph: { spacing: { before: 240, after: 120 }, alignment: AlignmentType.CENTER },
        },
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 32, bold: true, color: "000000", font: "Arial" },
          paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 28, bold: true, color: "000000", font: "Arial" },
          paragraph: { spacing: { before: 180, after: 120 }, outlineLevel: 1 },
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
          },
        },
        children,
      },
    ],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  console.log(`Wrote ${outputPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
