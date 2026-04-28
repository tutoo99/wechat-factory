#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const LIST_URL = "https://mp.weixin.qq.com/cgi-bin/appmsgpublish";
const WXTEXT_APP_ROOT = "/Users/naipan/dev/AiSrc/wxtext/wxtext-app";
const DEFAULT_OUTPUT_DIR =
  "/Users/naipan/.codex/skills/zhouzuoluo-perspective/references/sources/articles";
const DEFAULT_FAKEID = "MzU3MTc1MjE4OQ==";
const DEFAULT_FINGERPRINT = "5504547a08cc59c607a82d9367538b2d";
const A4_WIDTH = 595;

const requireFromWxtext = createRequire(path.join(WXTEXT_APP_ROOT, "package.json"));
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  ImageRun,
  AlignmentType,
  HeadingLevel,
  Header,
  Footer,
  PageNumber,
} = requireFromWxtext("docx");
const cheerio = requireFromWxtext("cheerio");

const { fetchArticle, getImageType } = await import(
  pathToFileURL(path.join(WXTEXT_APP_ROOT, "lib", "fetch-article.ts")).href
);

function parseArgs(argv) {
  const args = {
    begin: 0,
    count: 5,
    pages: 1,
    outputDir: DEFAULT_OUTPUT_DIR,
    articlesFile: "",
    fakeid: DEFAULT_FAKEID,
    fingerprint: DEFAULT_FINGERPRINT,
    token: process.env.WECHAT_TOKEN ?? "",
    cookie: process.env.WECHAT_COOKIE ?? "",
    maxArticles: Number.MAX_SAFE_INTEGER,
    dryRun: false,
    overwrite: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];

    switch (arg) {
      case "--begin":
        args.begin = Number(next);
        index += 1;
        break;
      case "--count":
        args.count = Number(next);
        index += 1;
        break;
      case "--pages":
        args.pages = Number(next);
        index += 1;
        break;
      case "--output-dir":
        args.outputDir = next;
        index += 1;
        break;
      case "--articles-file":
        args.articlesFile = next;
        index += 1;
        break;
      case "--fakeid":
        args.fakeid = next;
        index += 1;
        break;
      case "--fingerprint":
        args.fingerprint = next;
        index += 1;
        break;
      case "--token":
        args.token = next;
        index += 1;
        break;
      case "--cookie":
        args.cookie = next;
        index += 1;
        break;
      case "--max-articles":
        args.maxArticles = Number(next);
        index += 1;
        break;
      case "--dry-run":
        args.dryRun = true;
        break;
      case "--overwrite":
        args.overwrite = true;
        break;
      case "--help":
        printHelp(0);
        break;
      default:
        if (arg.startsWith("--")) {
          throw new Error(`Unknown argument: ${arg}`);
        }
    }
  }

  if (!Number.isFinite(args.begin) || args.begin < 0) {
    throw new Error("--begin must be a non-negative number");
  }
  if (!Number.isFinite(args.count) || args.count <= 0) {
    throw new Error("--count must be a positive number");
  }
  if (!Number.isFinite(args.pages) || args.pages <= 0) {
    throw new Error("--pages must be a positive number");
  }
  if (!Number.isFinite(args.maxArticles) || args.maxArticles <= 0) {
    throw new Error("--max-articles must be a positive number");
  }

  return args;
}

function printHelp(exitCode) {
  console.log(`Usage:
  node --experimental-strip-types export_wechat_page.mjs [options]

Options:
  --begin <n>           Starting begin offset, default 0
  --count <n>           Publish entries per page, default 5
  --pages <n>           How many backend pages to fetch, default 1
  --output-dir <dir>    Target directory for generated docx files
  --articles-file <f>   Local JSON snapshot with title/link pairs
  --token <value>       WeChat backend token (or use WECHAT_TOKEN)
  --cookie <value>      WeChat backend cookie (or use WECHAT_COOKIE)
  --fakeid <value>      WeChat account fakeid
  --fingerprint <val>   WeChat fingerprint
  --max-articles <n>    Stop after N extracted articles
  --dry-run             Only print extracted titles and links
  --overwrite           Overwrite existing docx files
  --help                Show this help
`);
  process.exit(exitCode);
}

function sanitizeFilename(name) {
  return name
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 100);
}

function decodeHtmlEntities(text) {
  return text
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function normalizeText(text) {
  return decodeHtmlEntities(String(text ?? ""))
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function extractJsString(page, prefix, quote) {
  const idx = page.indexOf(prefix);
  if (idx === -1) return null;

  let start = idx + prefix.length;
  while (start < page.length && /\s/.test(page[start])) {
    start += 1;
  }
  if (page[start] !== quote) return null;

  let cursor = start + 1;
  let escaped = false;
  while (cursor < page.length) {
    const char = page[cursor];
    if (escaped) escaped = false;
    else if (char === "\\") escaped = true;
    else if (char === quote) return page.slice(start + 1, cursor);
    cursor += 1;
  }
  return null;
}

function decodeJsEscapes(raw) {
  return String(raw ?? "")
    .replace(/\\x([0-9A-Fa-f]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\u([0-9A-Fa-f]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\\//g, "/")
    .replace(/\\"/g, '"')
    .replace(/\\'/g, "'")
    .replace(/\\\\/g, "\\");
}

async function fetchPublishPage({ begin, count, token, fakeid, fingerprint, cookie }) {
  const url = new URL(LIST_URL);
  url.searchParams.set("sub", "list");
  url.searchParams.set("search_field", "null");
  url.searchParams.set("begin", String(begin));
  url.searchParams.set("count", String(count));
  url.searchParams.set("query", "");
  url.searchParams.set("fakeid", fakeid);
  url.searchParams.set("type", "101_1");
  url.searchParams.set("free_publish_type", "1");
  url.searchParams.set("sub_action", "list_ex");
  url.searchParams.set("fingerprint", fingerprint);
  url.searchParams.set("token", token);
  url.searchParams.set("lang", "zh_CN");
  url.searchParams.set("f", "json");
  url.searchParams.set("ajax", "1");

  const response = await fetch(url, {
    headers: {
      accept: "*/*",
      "accept-language": "zh-CN,zh;q=0.9",
      "cache-control": "no-cache",
      pragma: "no-cache",
      cookie,
      "user-agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
      "x-requested-with": "XMLHttpRequest",
    },
  });

  if (!response.ok) {
    throw new Error(`List API failed (HTTP ${response.status})`);
  }

  const payload = await response.json();
  if (payload?.base_resp?.ret !== 0) {
    throw new Error(`List API ret=${payload?.base_resp?.ret ?? "unknown"}`);
  }

  return payload;
}

async function fetchWechatHtml(url) {
  const response = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      Accept:
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      Referer: "https://mp.weixin.qq.com/",
    },
  });

  if (!response.ok) {
    throw new Error(`获取文章失败 (HTTP ${response.status})`);
  }

  return response.text();
}

function extractArticlesFromPayload(payload) {
  const publishPage =
    typeof payload.publish_page === "string"
      ? JSON.parse(payload.publish_page)
      : payload.publish_page;

  const articles = [];
  for (const publishEntry of publishPage.publish_list ?? []) {
    const publishInfo =
      typeof publishEntry.publish_info === "string"
        ? JSON.parse(publishEntry.publish_info)
        : publishEntry.publish_info;

    for (const article of publishInfo.appmsgex ?? []) {
      const title = String(article.title ?? "").trim();
      const link = String(article.link ?? "").replace(/\\\//g, "/").trim();
      if (!title || !link) {
        continue;
      }
      articles.push({
        title,
        link,
        author: String(article.author_name ?? "").trim(),
        itemShowType: article.item_show_type ?? null,
        createTime: article.create_time ?? null,
      });
    }
  }

  return articles;
}

function sectionIsLeafish($, el) {
  return $(el).find("p, section, pre, blockquote, h1, h2, h3, h4, h5, h6, img, ul, ol, li").length === 0;
}

function parseContentNodeFromFragment($, el, seenImages, depth = 0) {
  if (depth > 12 || !el?.length) return [];

  const tagName = el[0]?.tagName?.toLowerCase();
  const blocks = [];

  if (!tagName) return blocks;

  if (["h1", "h2", "h3"].includes(tagName)) {
    const text = normalizeText(el.text());
    if (text) {
      blocks.push({ type: "heading", text, level: tagName === "h1" ? 1 : tagName === "h2" ? 2 : 3 });
    }
    return blocks;
  }

  if (tagName === "img") {
    const url = el.attr("data-src") || el.attr("src");
    if (url && !seenImages.has(url)) {
      seenImages.add(url);
      blocks.push({ type: "image", url, alt: normalizeText(el.attr("alt") || "") || undefined });
    }
    return blocks;
  }

  if (["ul", "ol"].includes(tagName)) {
    const items = [];
    el.children("li").each((_, li) => {
      const text = normalizeText($(li).text());
      if (text) items.push(text);
    });
    if (items.length) blocks.push({ type: "list", items });
    return blocks;
  }

  if (["p", "blockquote", "pre", "li"].includes(tagName)) {
    el.find("img").each((_, img) => {
      blocks.push(...parseContentNodeFromFragment($, $(img), seenImages, depth + 1));
    });
    const text = normalizeText(el.text());
    if (text) {
      blocks.push({
        type: "paragraph",
        text,
        bold: el.find("strong, b").length > 0,
        italic: el.find("em, i").length > 0,
      });
    }
    return blocks;
  }

  if (["section", "div"].includes(tagName)) {
    if (sectionIsLeafish($, el)) {
      const text = normalizeText(el.text());
      if (text) blocks.push({ type: "paragraph", text });
      return blocks;
    }
    el.contents().each((_, child) => {
      if (child.type !== "tag") return;
      blocks.push(...parseContentNodeFromFragment($, $(child), seenImages, depth + 1));
    });
    return blocks;
  }

  const text = normalizeText(el.text());
  if (text) blocks.push({ type: "paragraph", text });
  return blocks;
}

function dedupeBlocks(blocks) {
  const deduped = [];
  let lastSig = null;
  for (const block of blocks) {
    const sig =
      block.type === "image"
        ? `${block.type}:${block.url}`
        : block.type === "list"
          ? `${block.type}:${block.items.join("|")}`
          : `${block.type}:${block.text}`;
    if (sig === lastSig) continue;
    deduped.push(block);
    lastSig = sig;
  }
  return deduped;
}

function getTextStats(blocks) {
  const textBlocks = blocks.filter((block) => block.type === "paragraph" || block.type === "heading");
  const textLength = textBlocks.reduce((sum, block) => sum + block.text.length, 0);
  return { textBlocks: textBlocks.length, textLength };
}

async function buildArticleFromContentNoencode(url) {
  const html = await fetchWechatHtml(url);
  const titleRaw = extractJsString(html, "var msg_title = ", "'");
  const authorRaw = extractJsString(html, 'var nickname = htmlDecode(', '"');
  const contentRaw = extractJsString(html, "content_noencode: JsDecode(", "'");

  if (!contentRaw) {
    throw new Error("content_noencode missing");
  }

  const title = normalizeText(decodeJsEscapes(titleRaw || ""));
  const author = normalizeText(decodeJsEscapes(authorRaw || ""));
  const contentHtml = decodeJsEscapes(contentRaw);
  const $ = cheerio.load(`<div id="content-root">${contentHtml}</div>`);
  const root = $("#content-root");
  const seenImages = new Set();
  const blocks = [];

  root.contents().each((_, child) => {
    if (child.type !== "tag") return;
    blocks.push(...parseContentNodeFromFragment($, $(child), seenImages, 0));
  });

  const deduped = dedupeBlocks(blocks);
  const stats = getTextStats(deduped);
  if (stats.textBlocks === 0 || stats.textLength === 0) {
    throw new Error("content_noencode parsed empty text");
  }

  return { title, author, content: deduped };
}

async function downloadImage(url) {
  try {
    const response = await fetch(url, {
      headers: {
        "user-agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        referer: "https://mp.weixin.qq.com/",
      },
    });

    if (!response.ok) {
      return null;
    }

    const buffer = Buffer.from(await response.arrayBuffer());
    const type = getImageType(url);
    let width = 400;
    let height = 300;

    if (width > A4_WIDTH) {
      const scale = A4_WIDTH / width;
      width = A4_WIDTH;
      height = Math.round(height * scale);
    }

    return { buffer, type, width, height };
  } catch {
    return null;
  }
}

async function generateDocx(article) {
  const children = [];

  children.push(
    new Paragraph({
      heading: HeadingLevel.TITLE,
      alignment: AlignmentType.CENTER,
      spacing: { before: 200, after: 200 },
      children: [
        new TextRun({
          text: article.title,
          bold: true,
          size: 56,
          font: "Arial",
        }),
      ],
    })
  );

  if (article.author) {
    children.push(
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 400 },
        children: [
          new TextRun({
            text: `作者：${article.author}`,
            italics: true,
            size: 24,
            font: "Arial",
          }),
        ],
      })
    );
  }

  for (const block of article.content) {
    switch (block.type) {
      case "paragraph": {
        const lines = block.text.split("\n");
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            continue;
          }
          children.push(
            new Paragraph({
              spacing: { before: 120, after: 120 },
              indent: { firstLine: 480 },
              children: [
                new TextRun({
                  text: trimmed,
                  bold: block.bold,
                  italics: block.italic,
                  size: 24,
                  font: "Arial",
                }),
              ],
            })
          );
        }
        break;
      }

      case "heading":
        children.push(
          new Paragraph({
            heading:
              block.level === 1
                ? HeadingLevel.HEADING_1
                : block.level === 2
                  ? HeadingLevel.HEADING_2
                  : HeadingLevel.HEADING_3,
            spacing: { before: 400, after: 200 },
            children: [
              new TextRun({
                text: block.text,
                bold: true,
                size: block.level === 1 ? 32 : 28,
                font: "Arial",
              }),
            ],
          })
        );
        break;

      case "image": {
        const image = await downloadImage(block.url);
        if (!image) {
          break;
        }
        children.push(
          new Paragraph({
            alignment: AlignmentType.CENTER,
            spacing: { before: 200, after: 200 },
            children: [
              new ImageRun({
                type: image.type,
                data: image.buffer,
                transformation: { width: image.width, height: image.height },
                altText: {
                  title: block.alt || "文章图片",
                  description: block.alt || "文章图片",
                  name: "article-image",
                },
              }),
            ],
          })
        );
        break;
      }

      case "list":
        for (const item of block.items) {
          children.push(
            new Paragraph({
              spacing: { before: 60, after: 60 },
              indent: { left: 480 },
              children: [
                new TextRun({
                  text: `• ${item}`,
                  size: 24,
                  font: "Arial",
                }),
              ],
            })
          );
        }
        break;

      default:
        break;
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
          run: { size: 56, bold: true, color: "000000", font: "Arial" },
          paragraph: {
            spacing: { before: 240, after: 120 },
            alignment: AlignmentType.CENTER,
          },
        },
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 32, bold: true, color: "000000", font: "Arial" },
          paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 28, bold: true, color: "000000", font: "Arial" },
          paragraph: { spacing: { before: 200, after: 200 }, outlineLevel: 1 },
        },
        {
          id: "Heading3",
          name: "Heading 3",
          basedOn: "Normal",
          next: "Normal",
          quickFormat: true,
          run: { size: 26, bold: true, color: "000000", font: "Arial" },
          paragraph: { spacing: { before: 160, after: 160 }, outlineLevel: 2 },
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
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                children: [
                  new TextRun({
                    text:
                      article.title.length > 30
                        ? `${article.title.slice(0, 30)}...`
                        : article.title,
                    size: 16,
                    color: "999999",
                    font: "Arial",
                  }),
                ],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({ text: "第 ", size: 16, color: "999999", font: "Arial" }),
                  new TextRun({
                    children: [PageNumber.CURRENT],
                    size: 16,
                    color: "999999",
                    font: "Arial",
                  }),
                  new TextRun({ text: " 页", size: 16, color: "999999", font: "Arial" }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });

  return Packer.toBuffer(doc);
}

function buildFallbackArticle(article) {
  const rawContent = String(article.content ?? "").trim();
  if (!rawContent) {
    throw new Error("No fallback content available");
  }

  const plainText = decodeHtmlEntities(
    rawContent
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/p>/gi, "\n\n")
      .replace(/<a\b[^>]*>(.*?)<\/a>/gi, "$1")
      .replace(/<[^>]+>/g, "")
  );

  const content = plainText
    .split(/\n{2,}/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((text) => ({ type: "paragraph", text }));

  if (content.length === 0) {
    throw new Error("Fallback content is empty after normalization");
  }

  return {
    title: article.title,
    author: article.author,
    content,
  };
}

async function exportArticle(article, outputDir, overwrite) {
  let parsed;
  try {
    parsed = await fetchArticle(article.link);
  } catch (error) {
    if (!article.content) {
      throw error;
    }
    parsed = buildFallbackArticle(article);
  }

  const parsedStats = getTextStats(parsed.content);
  if (parsedStats.textLength < 1200 || parsedStats.textBlocks < 10) {
    try {
      const stronger = await buildArticleFromContentNoencode(article.link);
      const strongerStats = getTextStats(stronger.content);
      if (strongerStats.textLength > parsedStats.textLength * 2) {
        parsed = stronger;
      }
    } catch {
      // Keep current parsed result if stronger fallback fails.
    }
  }

  const buffer = await generateDocx(parsed);
  const filename = sanitizeFilename(parsed.title || article.title || "未命名文章");
  const targetPath = path.join(outputDir, `${filename}.docx`);

  if (!overwrite) {
    try {
      await fs.access(targetPath);
      return { status: "skipped", file: targetPath, title: parsed.title, url: article.link };
    } catch {
      // no-op
    }
  }

  await fs.mkdir(outputDir, { recursive: true });
  await fs.writeFile(targetPath, buffer);
  return { status: "written", file: targetPath, title: parsed.title, url: article.link };
}

async function loadArticlesFromFile(filePath) {
  const raw = await fs.readFile(filePath, "utf8");
  const parsed = JSON.parse(raw);
  const items = Array.isArray(parsed) ? parsed : parsed.articles;

  if (!Array.isArray(items)) {
    throw new Error(`Invalid articles file: ${filePath}`);
  }

  return items
    .map((item) => ({
      title: String(item.title ?? "").trim(),
      link: String(item.link ?? "").trim(),
      author: String(item.author ?? "").trim(),
      content: String(item.content ?? ""),
      itemShowType: item.itemShowType ?? null,
      createTime: item.createTime ?? null,
    }))
    .filter((item) => item.title && item.link);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  const articles = [];
  if (args.articlesFile) {
    articles.push(...(await loadArticlesFromFile(args.articlesFile)));
  } else {
    if (!args.cookie || !args.token) {
      throw new Error("WECHAT_COOKIE / WECHAT_TOKEN missing; provide env vars or --cookie/--token");
    }

    for (let pageIndex = 0; pageIndex < args.pages; pageIndex += 1) {
      const begin = args.begin + pageIndex * args.count;
      const payload = await fetchPublishPage({
        begin,
        count: args.count,
        token: args.token,
        fakeid: args.fakeid,
        fingerprint: args.fingerprint,
        cookie: args.cookie,
      });
      const pageArticles = extractArticlesFromPayload(payload);
      articles.push(...pageArticles);
      if (articles.length >= args.maxArticles) {
        break;
      }
    }
  }

  const dedupedArticles = [];
  const seenLinks = new Set();
  for (const article of articles) {
    if (seenLinks.has(article.link)) {
      continue;
    }
    seenLinks.add(article.link);
    dedupedArticles.push(article);
    if (dedupedArticles.length >= args.maxArticles) {
      break;
    }
  }

  if (dedupedArticles.length === 0) {
    throw new Error("No articles extracted from publish page");
  }

  console.log(`Extracted ${dedupedArticles.length} article(s) from begin=${args.begin}`);
  for (const [index, article] of dedupedArticles.entries()) {
    console.log(`${index + 1}. ${article.title}`);
    console.log(`   ${article.link}`);
  }

  if (args.dryRun) {
    return;
  }

  const results = [];
  for (const [index, article] of dedupedArticles.entries()) {
    console.log(`\n[${index + 1}/${dedupedArticles.length}] Exporting ${article.title}`);
    try {
      const result = await exportArticle(article, args.outputDir, args.overwrite);
      results.push(result);
      console.log(`   ${result.status === "written" ? "Saved" : "Skipped"} -> ${result.file}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      results.push({ status: "failed", title: article.title, url: article.link, error: message });
      console.error(`   Failed -> ${message}`);
    }
  }

  const written = results.filter((item) => item.status === "written").length;
  const skipped = results.filter((item) => item.status === "skipped").length;
  const failed = results.filter((item) => item.status === "failed").length;

  console.log(`\nDone. written=${written} skipped=${skipped} failed=${failed}`);

  if (failed > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
