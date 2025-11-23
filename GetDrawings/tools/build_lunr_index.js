#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const lunr = require("lunr");

// Adjust this to point at your docs directory
const DOCS_DIR = path.resolve(__dirname, "../docs");
const OUT_FILE = path.resolve(__dirname, "../docs/lunr-index.json");

const SNIPPET_CHARS = 2000;

// Collect every JSONL file (topics_part_aa, ab, …)
function readDocs(dir) {
  const entries = [];
  for (const fname of fs.readdirSync(dir)) {
    const fullPath = path.join(dir, fname);
    const stat = fs.statSync(fullPath);
    if (stat.isDirectory()) {
      entries.push(...readDocs(fullPath));
    } else if (fname.endsWith(".jsonl")) {
      const lines = fs.readFileSync(fullPath, "utf-8").split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        try {
          const doc = JSON.parse(line);
          entries.push({
            id: doc.id,
            module: doc.module,
            title: doc.title,
            path: doc.path,
            snippet: (doc.markdown ?? "").slice(0, SNIPPET_CHARS),
          });
        } catch (err) {
          console.warn(`Skipping malformed line in ${fname}`);
        }
      }
    }
  }
  return entries;
}

const docs = readDocs(DOCS_DIR);

const index = lunr(function () {
  this.ref("id");
  this.field("title");
  this.field("module");
  this.field("snippet");
  docs.forEach((doc) => this.add(doc));
});

const docsMeta = docs.map(({ id, module, title, path }) => ({
  id, module, title, path,
}));

fs.writeFileSync(
  OUT_FILE,
  JSON.stringify({ index: index.toJSON(), docs: docsMeta }),
  "utf-8"
);

console.log(`Lunr index built with ${docs.length} docs → ${OUT_FILE}`);
