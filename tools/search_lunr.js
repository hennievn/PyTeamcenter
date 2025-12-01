#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const lunr = require("lunr");

const INDEX_FILE = path.resolve(__dirname, "../docs/lunr-index.json");
const query = process.argv.slice(2).join(" ");
if (!query) {
  console.error("Usage: node tools/search_lunr.js <query terms…>");
  process.exit(1);
}

const { index, docs } = JSON.parse(fs.readFileSync(INDEX_FILE, "utf-8"));
const idx = lunr.Index.load(index);

const docMap = new Map(docs.map((doc) => [doc.id, doc]));
const results = idx.search(query);

if (!results.length) {
  console.log("No matches.");
  process.exit(0);
}

for (const res of results.slice(0, 10)) {
  const doc = docMap.get(res.ref);
  if (!doc) continue;
  console.log(`${doc.title} [${doc.module}]`);
  console.log(`  Path: ${doc.path}`);
  console.log(`  Score: ${res.score.toFixed(3)}\n`);
}