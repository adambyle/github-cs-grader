#!/usr/bin/env node
/*
 * autograder.js, {{course}} {{assignment}}: {{title}}
 *
 * The grading bundle's entry point, in JavaScript. `{{course}} marks` runs it
 * once per student, inside a clean checkout of the student's repository.
 * There is an identical grader written in Python (autograder.py in the
 * toolkit's scaffold folder); an assignment names ONE of them in
 * assignment.json and the harness dispatches by extension.
 *
 * THE CONTRACT (the same in both languages; see docs/writing-an-assignment.md)
 *
 *     cwd                      the student's checkout
 *     __dirname                this bundle; the authoritative files sit here
 *     reads (environment)      COURSE, ASSIGNMENT, USERNAME, SUBMISSION_TAG,
 *                              COMMIT_URL, RELEASE_URL, REVIEW_URL
 *                              RESTORE_FILES (JSON array, set by the harness)
 *     must write               ./result.json
 *     may write                ./feedback.md
 *     exit 0                   graded, whether the student passed or failed
 *     exit non-zero            infrastructure error, NOT a student failure
 *
 *   That last line matters: a student whose code does not load scores zero
 *   and this exits 0. A missing bundle file or a broken runtime exits 1, and
 *   `marks` reports it as a tooling problem instead of recording a zero.
 *
 * WHAT IT DOES, IN ORDER
 *   1. RESTORE   copies every file on the restore list from this bundle over
 *                the student's copy. The restore list lives in
 *                assignments/<a>/assignment.json; the harness hands it over in
 *                RESTORE_FILES so this file never has to find that path.
 *   2. VISIBLE   runs the suite (SUITE below) with COURSE_JSON_OUT set, and
 *                reads back one row per check.
 *   3. HIDDEN    optional. If HIDDEN_SUITE names a file in this bundle, its
 *                source is read, the file is DELETED from disk, and it is run
 *                from memory via `node -`. Student code runs with this
 *                process's privileges and can read any file that exists at
 *                that moment; this is obscure, not secret. Never write a
 *                hidden test whose content is itself the answer.
 *   4. RESULT    writes result.json (schema course/result/v1) and feedback.md.
 */

"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// ── per-assignment configuration ────────────────────────────────────────
// Plain literals only. `verify` reads them with a regex, so keep the form
// `const NAME = value;` exactly.

const EXPECTED_VISIBLE = {{expected_visible}};   // checks the visible suite runs
const EXPECTED_HIDDEN  = 0;                      // and the hidden one
const POINTS = {};                               // label prefix -> points; default 1
const DEFAULT_POINTS = 1;
const HIDDEN_SUITE = null;                       // e.g. "hidden_test.js", or null
const HIDDEN_PREFIX = "Additional: ";
const SUITE = ["node", "test.js"];               // how to run the visible suite
const TIMEOUT = 300;                             // seconds, per suite

// ────────────────────────────────────────────────────────────────────────

const HERE = __dirname;
const REPO = process.cwd();
const log = (s) => console.log(s);

/** The restore list, from the harness, falling back to assignment.json. */
function restoreList() {
  if (process.env.RESTORE_FILES) {
    try { return JSON.parse(process.env.RESTORE_FILES); } catch (e) { /* fall through */ }
  }
  const aid = process.env.ASSIGNMENT || path.basename(HERE);
  const candidate = path.join(HERE, "..", "..", "assignments", aid, "assignment.json");
  if (fs.existsSync(candidate)) {
    return JSON.parse(fs.readFileSync(candidate, "utf8")).restore || [];
  }
  log("::warning::no restore list available; grading the student's copies as they are");
  return [];
}

/** Every file under a directory, relative, POSIX separators. */
function filesUnder(dir, base = dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...filesUnder(full, base));
    else out.push(path.relative(base, full).split(path.sep).join("/"));
  }
  return out;
}

/** Overwrite student copies of provided files with the bundle's. */
function restoreFiles() {
  const restored = [];
  for (const entry of restoreList()) {
    const names = entry.endsWith("/")
      ? (fs.existsSync(path.join(HERE, entry)) ? filesUnder(path.join(HERE, entry)).map((f) => entry + f) : [])
      : [entry];
    if (entry.endsWith("/") && names.length === 0) {
      log(`::warning::bundle is missing ${entry}; using the student's copy`);
    }
    for (const name of names) {
      const src = path.join(HERE, name);
      if (!fs.existsSync(src)) {
        log(`::warning::bundle is missing ${name}; using the student's copy`);
        continue;
      }
      const dst = path.join(REPO, name);
      fs.mkdirSync(path.dirname(dst), { recursive: true });
      const changed = !fs.existsSync(dst) || !fs.readFileSync(dst).equals(fs.readFileSync(src));
      fs.copyFileSync(src, dst);
      if (changed) restored.push(name);
    }
  }
  return restored;
}

function pointsFor(label) {
  for (const [prefix, pts] of Object.entries(POINTS)) {
    if (label.startsWith(prefix)) return pts;
  }
  return DEFAULT_POINTS;
}

/** Run one suite in the checkout; returns the parsed JSON or null. */
function runSuite(argv, resultsPath, label, stdin) {
  if (fs.existsSync(resultsPath)) fs.unlinkSync(resultsPath);
  log(`── running ${label} ──────────────────────────────────────────────`);
  const proc = spawnSync(argv[0], argv.slice(1), {
    cwd: REPO, input: stdin, encoding: "utf8", timeout: TIMEOUT * 1000,
    env: { ...process.env, COURSE_JSON_OUT: resultsPath, NO_COLOR: "1" },
    maxBuffer: 64 * 1024 * 1024,
  });
  if (proc.stdout) log(proc.stdout);
  if (proc.stderr && proc.stderr.trim()) { log(`── ${label} stderr ──`); log(proc.stderr.slice(-4000)); }
  if (proc.error && proc.error.code === "ETIMEDOUT") {
    log(`::error::${label} exceeded ${TIMEOUT}s; likely an infinite loop`);
    return { build: true, build_error: "", timeout: true,
             tests: [{ name: `${label} completed within ${TIMEOUT}s`, passed: false,
                       hints: ["the test suite timed out; check for an infinite loop"] }] };
  }
  if (proc.error && proc.error.code === "ENOENT") {
    log(`::error::${argv[0]} is not installed`);
    return null;
  }
  log("──────────────────────────────────────────────────────────────────");
  if (!fs.existsSync(resultsPath)) return null;
  try { return JSON.parse(fs.readFileSync(resultsPath, "utf8")); }
  catch (err) { log(`::error::could not parse ${label} JSON output: ${err.message}`); return null; }
}

/** Run the hidden suite from memory, after removing it from disk. */
function runHidden(script, resultsPath, label) {
  const source = fs.readFileSync(script, "utf8");
  try { fs.unlinkSync(script); } catch (err) { log(`::warning::could not remove ${path.basename(script)}: ${err.message}`); }
  return runSuite(["node", "-"], resultsPath, label, source);
}

function rowsFrom(data, prefix = "") {
  const rows = [], hints = {};
  for (const t of data.tests || []) {
    const pts = pointsFor(t.name);
    const name = prefix + t.name;
    rows.push({ "test-name": name, passed: !!t.passed, score: t.passed ? pts : 0, "max-score": pts });
    hints[name] = t.hints || [];
  }
  return [rows, hints];
}

function failureSection(title, rows, hints) {
  const failed = rows.filter((r) => !r.passed);
  if (!failed.length) return [];
  const out = [`### ${title}`, ""];
  for (const r of failed) {
    out.push(`- **${r["test-name"]}**`);
    for (const h of hints[r["test-name"]] || []) out.push(`  - ${h}`);
  }
  out.push("");
  return out;
}

function writeFeedback(visRows, visHints, hidRows, hidHints, restored, buildError) {
  const rows = visRows.concat(hidRows);
  const score = rows.reduce((s, r) => s + r.score, 0);
  const max = rows.reduce((s, r) => s + r["max-score"], 0);
  let out = [`## ${score} / ${max}`, ""];
  if (buildError) {
    out = out.concat(["### Your code did not load", "",
      "Fix the error below, run `npm test` locally until everything passes, then push again.", "",
      "```", buildError.trim().slice(-3000), "```", ""]);
    fs.writeFileSync("feedback.md", out.join("\n"));
    return;
  }
  out = out.concat(failureSection(`${visRows.filter((r) => !r.passed).length} visible check(s) failed`, visRows, visHints));
  if (hidRows.length) {
    out = out.concat(failureSection(`${hidRows.filter((r) => !r.passed).length} additional check(s) failed`, hidRows, hidHints));
  }
  if (score === max) out.push("All checks passed. Nice work.", "");
  const passing = rows.filter((r) => r.passed);
  if (passing.length) {
    out.push(`<details><summary>${passing.length} check(s) passed</summary>`, "");
    for (const r of passing) out.push(`- ${r["test-name"]}`);
    out.push("", "</details>", "");
  }
  if (restored.length) {
    out.push("> Note: `" + restored.join("`, `") + "` were restored from the course copy before grading. Grading always uses the official test suite.", "");
  }
  for (const [label, actual, expected] of [["visible", visRows.length, EXPECTED_VISIBLE], ["additional", hidRows.length, EXPECTED_HIDDEN]]) {
    if (actual !== expected) out.push(`> Note: the ${label} suite ran ${actual} checks; ${expected} were expected.`, "");
  }
  fs.writeFileSync("feedback.md", out.join("\n"));
}

function main() {
  const restored = restoreFiles();
  const tmp = fs.mkdtempSync(path.join(require("node:os").tmpdir(), "grader-"));

  const visible = runSuite(SUITE, path.join(tmp, "visible.json"), "visible suite");
  if (visible === null) {
    log("::error::the visible suite produced no results file; grading could not run");
    return 1;
  }

  const totalMax = (EXPECTED_VISIBLE + EXPECTED_HIDDEN) * DEFAULT_POINTS;
  let visRows, visHints, hidRows = [], hidHints = {}, buildError = "";

  if (visible.build === false) {
    // Load failure: one row, worth the whole assignment, scored zero. The
    // denominator stays EXPECTED_VISIBLE, not 0/0.
    visRows = [{ "test-name": "Build (code loads)", passed: false, score: 0, "max-score": totalMax }];
    visHints = {};
    buildError = visible.build_error || "";
  } else {
    [visRows, visHints] = rowsFrom(visible);
    if (HIDDEN_SUITE) {
      const hiddenPath = path.join(HERE, HIDDEN_SUITE);
      if (fs.existsSync(hiddenPath)) {
        const hidden = runHidden(hiddenPath, path.join(tmp, "hidden.json"), "additional checks");
        if (hidden === null) log("::warning::the additional-check suite produced no results; grading on the visible suite alone");
        else [hidRows, hidHints] = rowsFrom(hidden, HIDDEN_PREFIX);
      } else {
        log(`::warning::${HIDDEN_SUITE} is missing from the bundle`);
      }
    }
  }

  const rows = visRows.concat(hidRows);
  const score = rows.reduce((s, r) => s + r.score, 0);
  const max = rows.reduce((s, r) => s + r["max-score"], 0);
  const env = process.env;

  fs.writeFileSync("result.json", JSON.stringify({
    schema: "course/result/v1",
    course: env.COURSE || "",
    assignment: env.ASSIGNMENT || "",
    usernames: [env.USERNAME || ""],
    submission: env.SUBMISSION_TAG || "",
    commit: env.COMMIT_URL || "",
    release: env.RELEASE_URL || env.COMMIT_URL || "",
    review: env.REVIEW_URL || env.COMMIT_URL || "",
    datetime: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    score, "max-score": max, tests: rows,
  }, null, 2));

  writeFeedback(visRows, visHints, hidRows, hidHints, restored, buildError);
  log(`Score: ${score}/${max}`);
  return 0;
}

process.exit(main());
