#!/usr/bin/env node
// 公開WebページのURLを受け取り、Defuddleで本文をMarkdown化して inbox/ に保存するCLI。
// 本文の文言は変更せず、HTML構造のMarkdown写像・URLのabsolute化・画像のローカル保存だけを行う。
// 人間のターミナル実行とAgent Skill (--json) の両方から同じ経路で使う。

import { createHash } from "node:crypto";
import { lookup } from "node:dns/promises";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { isIP } from "node:net";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

import { Defuddle } from "defuddle/node";
import { JSDOM, VirtualConsole } from "jsdom";

const USER_AGENT = "Mozilla/5.0 (compatible; web-to-markdown/1.0; +https://github.com/mjun0812/llm-wiki-template)";
const FETCH_TIMEOUT_MS = 30_000;
const MAX_REDIRECTS = 5;
const MAX_HTML_BYTES = 10 * 1024 * 1024;
const MAX_ASSET_BYTES = 20 * 1024 * 1024;
const MAX_TOTAL_ASSET_BYTES = 100 * 1024 * 1024;
const ARTICLE_ID_LENGTH = 10;
const CONTENT_HASH_LENGTH = 14;
const SHORT_CONTENT_WORD_COUNT = 20;
const MAX_SLUG_LENGTH = 80;

// scripts/check_image_links.py の IMAGE_EXTENSIONS と揃える。
const IMAGE_EXTENSIONS = new Set(["avif", "bmp", "gif", "jpeg", "jpg", "png", "svg", "webp"]);
const CONTENT_TYPE_EXTENSIONS = new Map([
  ["image/avif", "avif"],
  ["image/bmp", "bmp"],
  ["image/gif", "gif"],
  ["image/jpeg", "jpg"],
  ["image/png", "png"],
  ["image/svg+xml", "svg"],
  ["image/webp", "webp"],
]);

// --strict でfailureへ昇格するwarning。
const STRICT_FAILURE_WARNINGS = new Set([
  "WEBMD_WARN_ASSET_SKIPPED",
  "WEBMD_WARN_ASSET_UNSUPPORTED",
  "WEBMD_WARN_CANVAS_UNSUPPORTED",
  "WEBMD_WARN_BLOB_URL",
]);

const HELP = `Usage: node scripts/web-to-markdown.mjs <URL> [options]

公開WebページをDefuddleでMarkdown化し、inbox/ に保存する。

Options:
  --output-dir <dir>   出力ディレクトリ (既定: inbox)
  --no-assets          画像をローカル保存せずremote URLのまま残す
  --force              既存出力ファイルの上書きを許可
  --json               結果をJSONでstdoutへ返す (Agent向け)
  --dry-run            書き込みを行わず、予定ファイルと警告だけ返す
  --strict             保存できない重要要素があれば非0終了する
  -h, --help           このヘルプを表示する

Error codes:
  WEBMD_INVALID_URL WEBMD_BLOCKED_URL WEBMD_FETCH_FAILED WEBMD_FETCH_TOO_LARGE
  WEBMD_EXTRACT_EMPTY WEBMD_ASSET_FETCH_FAILED WEBMD_ASSET_TOO_LARGE
  WEBMD_OUTPUT_EXISTS WEBMD_WRITE_FAILED WEBMD_STRICT_FAILED
`;

export class CliError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export function parseArgs(argv) {
  const options = {
    url: null,
    outputDir: "inbox",
    assets: true,
    force: false,
    json: false,
    dryRun: false,
    strict: false,
    help: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case "--output-dir":
        options.outputDir = argv[++i];
        if (options.outputDir === undefined) {
          throw new CliError("WEBMD_INVALID_URL", "--output-dir に値がありません");
        }
        break;
      case "--no-assets":
        options.assets = false;
        break;
      case "--force":
        options.force = true;
        break;
      case "--json":
        options.json = true;
        break;
      case "--dry-run":
        options.dryRun = true;
        break;
      case "--strict":
        options.strict = true;
        break;
      case "-h":
      case "--help":
        options.help = true;
        break;
      default:
        if (arg.startsWith("-")) {
          throw new CliError("WEBMD_INVALID_URL", `不明なoptionです: ${arg}`);
        }
        if (options.url !== null) {
          throw new CliError("WEBMD_INVALID_URL", "URLは1つだけ指定してください");
        }
        options.url = arg;
    }
  }
  return options;
}

// ---------------------------------------------------------------------------
// URL policy (SSRF対策)
// ---------------------------------------------------------------------------

export function parseTargetUrl(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new CliError("WEBMD_INVALID_URL", `URLとして解釈できません: ${rawUrl}`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new CliError("WEBMD_INVALID_URL", `対応していないschemeです: ${url.protocol}`);
  }
  if (url.username || url.password) {
    throw new CliError("WEBMD_BLOCKED_URL", "user/passwordを含むURLは拒否します");
  }
  return url;
}

function ipv4ToInt(ip) {
  return ip.split(".").reduce((acc, octet) => acc * 256 + Number(octet), 0);
}

function inIpv4Range(ip, cidrBase, prefixLength) {
  const mask = prefixLength === 0 ? 0 : (~0 << (32 - prefixLength)) >>> 0;
  return ((ipv4ToInt(ip) & mask) >>> 0) === ((ipv4ToInt(cidrBase) & mask) >>> 0);
}

const BLOCKED_IPV4_RANGES = [
  ["0.0.0.0", 8], // this network
  ["10.0.0.0", 8], // private
  ["100.64.0.0", 10], // CGNAT (cloud metadata含む)
  ["127.0.0.0", 8], // loopback
  ["169.254.0.0", 16], // link-local (cloud metadata含む)
  ["172.16.0.0", 12], // private
  ["192.0.0.0", 24], // IETF protocol assignments
  ["192.168.0.0", 16], // private
  ["198.18.0.0", 15], // benchmarking
];

export function isBlockedIpAddress(address) {
  const version = isIP(address);
  if (version === 4) {
    return BLOCKED_IPV4_RANGES.some(([base, prefix]) => inIpv4Range(address, base, prefix));
  }
  if (version === 6) {
    const lower = address.toLowerCase();
    if (lower === "::" || lower === "::1") {
      return true;
    }
    const mapped = lower.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    if (mapped) {
      return isBlockedIpAddress(mapped[1]);
    }
    // fc00::/7 (unique local), fe80::/10 (link-local)
    return /^f[cd]/.test(lower) || /^fe[89ab]/.test(lower);
  }
  return true;
}

const BLOCKED_HOSTNAME_PATTERN = /^(localhost|.*\.localhost|.*\.local|.*\.internal)$/i;

async function assertAllowedUrl(url, dnsLookup) {
  const hostname = url.hostname.replace(/^\[|\]$/g, "");
  if (BLOCKED_HOSTNAME_PATTERN.test(hostname)) {
    throw new CliError("WEBMD_BLOCKED_URL", `拒否対象のhostです: ${hostname}`);
  }
  if (isIP(hostname)) {
    if (isBlockedIpAddress(hostname)) {
      throw new CliError("WEBMD_BLOCKED_URL", `拒否対象のaddressです: ${hostname}`);
    }
    return;
  }
  let addresses;
  try {
    addresses = await dnsLookup(hostname, { all: true });
  } catch {
    throw new CliError("WEBMD_FETCH_FAILED", `hostを解決できません: ${hostname}`);
  }
  for (const { address } of addresses) {
    if (isBlockedIpAddress(address)) {
      throw new CliError(
        "WEBMD_BLOCKED_URL",
        `拒否対象のaddressへ解決されるhostです: ${hostname} -> ${address}`,
      );
    }
  }
}

// ---------------------------------------------------------------------------
// safe fetch
// ---------------------------------------------------------------------------

async function readBodyLimited(response, maxBytes, tooLargeCode) {
  const contentLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > maxBytes) {
    await response.body?.cancel();
    throw new CliError(tooLargeCode, `response sizeが上限 (${maxBytes} bytes) を超えています`);
  }
  if (response.body === null) {
    return Buffer.alloc(0);
  }
  const chunks = [];
  let total = 0;
  for await (const chunk of response.body) {
    total += chunk.byteLength;
    if (total > maxBytes) {
      await response.body.cancel().catch(() => {});
      throw new CliError(tooLargeCode, `response sizeが上限 (${maxBytes} bytes) を超えています`);
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function safeFetch(rawUrl, { maxBytes, tooLargeCode, accept, fetchImpl, dnsLookup }) {
  let current = parseTargetUrl(rawUrl);
  for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects++) {
    await assertAllowedUrl(current, dnsLookup);
    let response;
    try {
      response = await fetchImpl(current.href, {
        redirect: "manual",
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
        headers: { "user-agent": USER_AGENT, accept },
      });
    } catch (error) {
      throw new CliError("WEBMD_FETCH_FAILED", `fetchに失敗しました: ${current.href} (${error.message})`);
    }
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get("location");
      await response.body?.cancel();
      if (!location) {
        throw new CliError("WEBMD_FETCH_FAILED", `redirectにlocationがありません: ${current.href}`);
      }
      current = parseTargetUrl(new URL(location, current).href);
      continue;
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw new CliError("WEBMD_FETCH_FAILED", `HTTP ${response.status}: ${current.href}`);
    }
    const body = await readBodyLimited(response, maxBytes, tooLargeCode);
    return { finalUrl: current.href, contentType: response.headers.get("content-type") ?? "", body };
  }
  throw new CliError("WEBMD_FETCH_FAILED", `redirect回数が上限 (${MAX_REDIRECTS}) を超えました`);
}

// ---------------------------------------------------------------------------
// 日付・frontmatter
// ---------------------------------------------------------------------------

function pad2(value) {
  return String(value).padStart(2, "0");
}

export function localDateString(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export function localIsoString(date) {
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMinutes);
  return (
    `${localDateString(date)}T${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}` +
    `${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`
  );
}

export function normalizePublishedDate(value) {
  if (!value) {
    return null;
  }
  const isoPrefix = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoPrefix) {
    const [, year, month, day] = isoPrefix;
    return `${year}-${month}-${day}`;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString().slice(0, 10);
}

function yamlQuote(value) {
  return `"${String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function buildFrontmatter(fields) {
  const lines = ["---"];
  for (const [key, value] of Object.entries(fields)) {
    if (value === null || value === undefined || value === "") {
      continue;
    }
    lines.push(`${key}: ${yamlQuote(value)}`);
  }
  lines.push("---");
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// slug・filename
// ---------------------------------------------------------------------------

export function slugFromTitle(title, fallback) {
  const slug = String(title ?? "")
    .normalize("NFKC")
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/[/\\:*?"<>|#%&()[\]{}!]/g, " ")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_SLUG_LENGTH)
    .replace(/-+$/, "");
  return slug || fallback;
}

function shortSha256(text, length) {
  return createHash("sha256").update(text).digest("hex").slice(0, length);
}

// ---------------------------------------------------------------------------
// GFM normalization
// ---------------------------------------------------------------------------

// Defuddleはfenced code block内のバッククォートを `\`` にエスケープし、コード本文を
// 変えてしまう。エスケープは全バッククォートへの一律のバックスラッシュ挿入なので、
// fence内だけ1つ剥がすことで正確に元へ戻せる。これ以外の独自変換は追加しない。
export function unescapeFencedCode(markdown) {
  let insideFence = false;
  return markdown
    .split("\n")
    .map((line) => {
      if (/^\s*(`{3,}|~{3,})/.test(line)) {
        insideFence = !insideFence;
        return line;
      }
      return insideFence ? line.replaceAll("\\`", "`") : line;
    })
    .join("\n");
}

// ---------------------------------------------------------------------------
// asset localizer
// ---------------------------------------------------------------------------

const MARKDOWN_IMAGE_PATTERN = /!\[[^\]\n]*\]\((?<target>[^)\s]+)(?:\s+"[^"]*")?\)/g;
const HTML_IMG_SRC_PATTERN = /<img\b[^>]*?\bsrc\s*=\s*"(?<target>[^"]+)"/g;

export function collectImageTargets(markdown) {
  const targets = new Set();
  for (const pattern of [MARKDOWN_IMAGE_PATTERN, HTML_IMG_SRC_PATTERN]) {
    for (const match of markdown.matchAll(pattern)) {
      targets.add(match.groups.target);
    }
  }
  return [...targets];
}

function extensionFor(contentType, targetUrl) {
  const mime = contentType.split(";")[0].trim().toLowerCase();
  const mapped = CONTENT_TYPE_EXTENSIONS.get(mime);
  if (mapped) {
    return mapped;
  }
  try {
    const urlExtension = path.extname(new URL(targetUrl).pathname).slice(1).toLowerCase();
    if (IMAGE_EXTENSIONS.has(urlExtension)) {
      return urlExtension;
    }
  } catch {
    // data URIなどURLとして解釈できないtargetは下のfallbackへ。
  }
  if (/^image\/[a-z0-9.-]+$/.test(mime)) {
    const subtype = mime.slice("image/".length).replace(/[^a-z0-9]/g, "");
    if (subtype) {
      return subtype;
    }
  }
  return null;
}

function decodeDataUri(target) {
  const match = target.match(/^data:(?<mime>image\/[a-z0-9.+-]+)(?<params>[^,]*),(?<data>.*)$/is);
  if (!match) {
    return null;
  }
  const { mime, params, data } = match.groups;
  const bytes = /;\s*base64$/i.test(params)
    ? Buffer.from(data, "base64")
    : Buffer.from(decodeURIComponent(data), "utf-8");
  return { contentType: mime.toLowerCase(), bytes };
}

async function localizeAssets({ markdown, articleId, imagesDir, warnings, fetchImpl, dnsLookup }) {
  const targets = collectImageTargets(markdown);
  const files = new Map(); // filename -> bytes
  const replacements = new Map(); // target -> relative path
  const filenameByHash = new Map();
  let totalBytes = 0;

  for (const target of targets) {
    let contentType;
    let bytes;
    if (target.startsWith("data:")) {
      const decoded = decodeDataUri(target);
      if (!decoded) {
        warnings.push({ code: "WEBMD_WARN_ASSET_UNSUPPORTED", message: "image以外のdata URIをそのまま残しました" });
        continue;
      }
      if (decoded.bytes.byteLength > MAX_ASSET_BYTES) {
        warnings.push({ code: "WEBMD_WARN_ASSET_SKIPPED", message: "size上限を超えるdata URI画像をそのまま残しました" });
        continue;
      }
      ({ contentType, bytes } = decoded);
    } else if (target.startsWith("blob:")) {
      warnings.push({ code: "WEBMD_WARN_BLOB_URL", message: `blob: URLは保存できません: ${target}` });
      continue;
    } else if (/^https?:\/\//i.test(target)) {
      try {
        const fetched = await safeFetch(target, {
          maxBytes: MAX_ASSET_BYTES,
          tooLargeCode: "WEBMD_ASSET_TOO_LARGE",
          accept: "image/*,*/*;q=0.8",
          fetchImpl,
          dnsLookup,
        });
        contentType = fetched.contentType;
        bytes = fetched.body;
      } catch (error) {
        warnings.push({
          code: "WEBMD_WARN_ASSET_SKIPPED",
          message: `画像を取得できずremote URLのまま残しました: ${target} (${error.message})`,
        });
        continue;
      }
    } else {
      warnings.push({ code: "WEBMD_WARN_ASSET_UNSUPPORTED", message: `対応していない画像参照です: ${target}` });
      continue;
    }

    const extension = extensionFor(contentType, target);
    if (!extension) {
      warnings.push({
        code: "WEBMD_WARN_ASSET_UNSUPPORTED",
        message: `画像形式を判定できずremote URLのまま残しました: ${target}`,
      });
      continue;
    }
    totalBytes += bytes.byteLength;
    if (totalBytes > MAX_TOTAL_ASSET_BYTES) {
      throw new CliError("WEBMD_ASSET_TOO_LARGE", `asset合計sizeが上限 (${MAX_TOTAL_ASSET_BYTES} bytes) を超えました`);
    }
    // 同一記事内でのみdeduplicateする。記事間はarticle-id namespaceで分離される。
    const contentHash = shortSha256(bytes, CONTENT_HASH_LENGTH);
    let filename = filenameByHash.get(contentHash);
    if (!filename) {
      filename = `${articleId}-${contentHash}.${extension}`;
      filenameByHash.set(contentHash, filename);
      files.set(filename, bytes);
    }
    replacements.set(target, `${path.basename(imagesDir)}/${filename}`);
  }

  let rewritten = markdown;
  for (const [target, relativePath] of replacements) {
    rewritten = rewritten.split(`(${target})`).join(`(${relativePath})`);
    rewritten = rewritten.split(`src="${target}"`).join(`src="${relativePath}"`);
  }
  return { markdown: rewritten, files };
}

// ---------------------------------------------------------------------------
// main pipeline
// ---------------------------------------------------------------------------

// Defuddleのauthor/share widget除去は、trimmed textがこのパターンに一致する要素を
// 語数の少ない親要素ごと削除する (dist/removals/content-patterns.js の SHARE_AUTHOR_LABEL)。
// syntax highlighterのtoken span (例: shikiの `<span> Author</span>`) が誤爆すると
// コード行が丸ごと消えるため、pre/code内の該当token spanを事前にテキストへ
// unwrapして防ぐ。textContentは変わらないため本文の忠実性には影響しない。
const AUTHOR_WIDGET_LABEL_PATTERN = /^(?:share|follow|authors?|written\s+by)$/i;

export function protectCodeTokenSpans(document) {
  for (const span of document.querySelectorAll("pre span, code span")) {
    if (span.children.length === 0 && AUTHOR_WIDGET_LABEL_PATTERN.test((span.textContent ?? "").trim())) {
      span.replaceWith(document.createTextNode(span.textContent));
    }
  }
}

function detectDocumentWarnings(document, warnings) {
  if (document.querySelector("canvas")) {
    warnings.push({ code: "WEBMD_WARN_CANVAS_UNSUPPORTED", message: "canvasによる図は保存できません" });
  }
  if (document.querySelector('img[src^="blob:"]')) {
    warnings.push({ code: "WEBMD_WARN_BLOB_URL", message: "blob: URLの画像は保存できません" });
  }
}

function detectContentWarnings(content, wordCount, warnings) {
  if (/<svg[\s>]/i.test(content)) {
    warnings.push({ code: "WEBMD_WARN_INLINE_SVG", message: "inline SVGをraw HTMLとして保持しました" });
  }
  if (/<table[\s>]/i.test(content)) {
    warnings.push({ code: "WEBMD_WARN_COMPLEX_TABLE_HTML", message: "複雑な表をraw HTML tableとして保持しました" });
  }
  if (wordCount < SHORT_CONTENT_WORD_COUNT) {
    warnings.push({ code: "WEBMD_WARN_SHORT_CONTENT", message: `本文が短すぎる可能性があります (${wordCount} words)` });
  }
}

export async function runWebToMarkdown(rawUrl, options = {}) {
  const {
    outputDir = "inbox",
    assets = true,
    force = false,
    dryRun = false,
    strict = false,
    fetchImpl = fetch,
    dnsLookup = lookup,
    now = new Date(),
    log = () => {},
  } = options;

  const warnings = [];
  const sourceUrl = parseTargetUrl(rawUrl).href;

  log(`fetch: ${sourceUrl}`);
  const page = await safeFetch(sourceUrl, {
    maxBytes: MAX_HTML_BYTES,
    tooLargeCode: "WEBMD_FETCH_TOO_LARGE",
    accept: "text/html,application/xhtml+xml",
    fetchImpl,
    dnsLookup,
  });

  const virtualConsole = new VirtualConsole();
  const dom = new JSDOM(page.body.toString("utf-8"), { url: page.finalUrl, virtualConsole });
  const document = dom.window.document;

  // Defuddleがdocumentを変更する可能性があるため、抽出前にDOM由来の情報を取り出す。
  const canonicalHref = document.querySelector('link[rel="canonical"]')?.href ?? null;
  let canonicalUrl = null;
  if (canonicalHref) {
    try {
      canonicalUrl = parseTargetUrl(canonicalHref).href;
    } catch {
      canonicalUrl = null;
    }
  }
  detectDocumentWarnings(document, warnings);
  protectCodeTokenSpans(document);

  log("extract: defuddle");
  const result = await Defuddle(document, page.finalUrl, { markdown: true });
  const content = unescapeFencedCode((result.content ?? "").trim());
  if (!content) {
    throw new CliError("WEBMD_EXTRACT_EMPTY", "Defuddleで本文を抽出できませんでした");
  }
  detectContentWarnings(content, result.wordCount ?? 0, warnings);

  const articleId = shortSha256(canonicalUrl ?? sourceUrl, ARTICLE_ID_LENGTH);
  const publishedAt = normalizePublishedDate(result.published);
  const createdDate = publishedAt ?? localDateString(now);
  const retrievedDate = localDateString(now);

  const title = (result.title ?? "").trim() || new URL(sourceUrl).hostname;
  const slug = slugFromTitle(title, articleId);
  const markdownPath = path.join(outputDir, `${createdDate}_${slug}.md`);
  const imagesDir = path.join(outputDir, "images");

  if (!force && existsSync(markdownPath)) {
    throw new CliError("WEBMD_OUTPUT_EXISTS", `出力先が既に存在します: ${markdownPath} (--forceで上書き)`);
  }

  let markdown = content;
  let assetFiles = new Map();
  if (assets && !dryRun) {
    log("assets: download");
    const localized = await localizeAssets({
      markdown,
      articleId,
      imagesDir,
      warnings,
      fetchImpl,
      dnsLookup,
    });
    markdown = localized.markdown;
    assetFiles = localized.files;
  }

  if (strict) {
    const escalated = warnings.filter((warning) => STRICT_FAILURE_WARNINGS.has(warning.code));
    if (escalated.length > 0) {
      const codes = [...new Set(escalated.map((warning) => warning.code))].join(", ");
      throw new CliError("WEBMD_STRICT_FAILED", `--strict: 保存できない重要要素があります (${codes})`);
    }
  }

  const frontmatter = buildFrontmatter({
    title,
    created: createdDate,
    updated: retrievedDate,
    source_url: sourceUrl,
    canonical_url: canonicalUrl,
    retrieved_at: localIsoString(now),
    published_at: publishedAt,
    author: (result.author ?? "").trim() || null,
    extractor: "defuddle",
  });
  const output = `${frontmatter}\n\n# ${title}\n\n${markdown}\n`;

  const assetPaths = [...assetFiles.keys()].map((filename) => path.join(imagesDir, filename));
  if (!dryRun) {
    try {
      await mkdir(path.dirname(markdownPath), { recursive: true });
      if (assetFiles.size > 0) {
        await mkdir(imagesDir, { recursive: true });
        for (const [filename, bytes] of assetFiles) {
          await writeFile(path.join(imagesDir, filename), bytes);
        }
      }
      await writeFile(markdownPath, output, "utf-8");
    } catch (error) {
      throw new CliError("WEBMD_WRITE_FAILED", `書き込みに失敗しました: ${error.message}`);
    }
    log(`write: ${markdownPath}`);
  }

  return {
    ok: true,
    url: sourceUrl,
    canonicalUrl: canonicalUrl ?? sourceUrl,
    markdown: markdownPath,
    assets: assetPaths,
    warnings,
  };
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n${HELP}`);
    return 1;
  }
  if (options.help) {
    process.stdout.write(HELP);
    return 0;
  }
  if (!options.url) {
    process.stderr.write(HELP);
    return 1;
  }

  try {
    const result = await runWebToMarkdown(options.url, {
      outputDir: options.outputDir,
      assets: options.assets,
      force: options.force,
      dryRun: options.dryRun,
      strict: options.strict,
      log: (message) => process.stderr.write(`${message}\n`),
    });
    for (const warning of result.warnings) {
      process.stderr.write(`warning: [${warning.code}] ${warning.message}\n`);
    }
    if (options.json) {
      process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    } else {
      process.stdout.write(`${options.dryRun ? "planned" : "saved"}: ${result.markdown}\n`);
    }
    return 0;
  } catch (error) {
    const code = error instanceof CliError ? error.code : "WEBMD_FETCH_FAILED";
    if (options.json) {
      const failure = {
        ok: false,
        url: options.url,
        markdown: null,
        assets: [],
        warnings: [],
        error: { code, message: error.message },
      };
      process.stdout.write(`${JSON.stringify(failure, null, 2)}\n`);
    } else {
      process.stderr.write(`error: [${code}] ${error.message}\n`);
    }
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
