#!/usr/bin/env node
/**
 * Run the actual SkillKit translator source used by its translate command.
 * Usage with tsx: tsx evaluation/compare_skillkit.mjs <skillkit-root> <source-skill-dir> <report.json>
 * No models, credentials, framework installs, or copied translator implementation.
 */
import { readFileSync, writeFileSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { resolve, join, relative, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';

const [repoArg, fixtureArg, reportArg] = process.argv.slice(2);
if (!repoArg || !fixtureArg || !reportArg) {
  throw new Error('Usage: tsx compare_skillkit.mjs <skillkit-root> <source-skill-dir> <report.json>');
}
const repo = resolve(repoArg), fixture = resolve(fixtureArg), reportPath = resolve(reportArg);
const { translateSkill, parseSkillContent } = await import(pathToFileURL(join(repo, 'packages/core/src/translator/index.ts')).href);
const original = readFileSync(join(fixture, 'SKILL.md'));
// Use the valid LF spelling for the semantic oracle. Do not count two missing
// values as a preservation success if a source parser rejected CRLF metadata.
const parsedOriginal = parseSkillContent(original.toString('utf8').replace(/\r\n/g, '\n'), 'SKILL.md');
const targets = ['cursor', 'windsurf', 'github-copilot', 'codex'];
const report = {
  comparison: 'skillkit-translator-source-v1',
  repository: 'https://github.com/rohitg00/skillkit',
  commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
  source_entry: 'packages/core/src/translator/index.ts:translateSkill',
  runtime: {
    node: process.version,
    yaml: JSON.parse(readFileSync(join(repo, 'node_modules/yaml/package.json'), 'utf8')).version,
    zod: JSON.parse(readFileSync(join(repo, 'node_modules/zod/package.json'), 'utf8')).version,
    tsx: JSON.parse(readFileSync(join(repo, 'node_modules/tsx/package.json'), 'utf8')).version,
  },
  scope: 'Actual content translator used by CLI translate. Package installation/sync paths are outside this test.',
  interpretation: 'This measures source preservation in supported translations, not framework execution equivalence. Targets differ from agentskills-bridge; it is a capability probe, not a same-format quality ranking.',
  runs: [],
};
function walk(root) {
  const result = {};
  function visit(dir) {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry), info = statSync(path);
      if (info.isDirectory()) visit(path);
      else if (info.isFile()) result[relative(root, path)] = {
        sha256: createHash('sha256').update(readFileSync(path)).digest('hex'),
        mode: info.mode & 0o777,
      };
    }
  }
  visit(root);
  return result;
}
const originalTree = walk(fixture);
for (const encoding of ['crlf', 'lf']) for (const target of targets) {
  const source = encoding === 'crlf' ? original : Buffer.from(original.toString('utf8').replace(/\r\n/g, '\n'));
  const variantTree = { ...originalTree, 'SKILL.md': {
    ...originalTree['SKILL.md'], sha256: createHash('sha256').update(source).digest('hex'),
  } };
  const parsedSource = parseSkillContent(source.toString('utf8'), 'SKILL.md');
  const first = translateSkill(source.toString('utf8'), target, { sourceFilename: 'SKILL.md' });
  const back = translateSkill(first.content, 'claude-code', { sourceFilename: first.filename });
  const parsedBack = parseSkillContent(back.content, back.filename);
  const restored = join(dirname(reportPath), 'skillkit-output', encoding, target);
  mkdirSync(restored, { recursive: true });
  writeFileSync(join(restored, 'SKILL.md'), back.content);
  const restoredTree = walk(restored);
  const missingFiles = Object.keys(originalTree).filter(p => !(p in restoredTree));
  const changedFiles = Object.keys(variantTree).filter(p => p in restoredTree && JSON.stringify(variantTree[p]) !== JSON.stringify(restoredTree[p]));
  report.runs.push({
    encoding, target, forward_success: first.success, reverse_success: back.success,
    source_name_parsed_correctly: parsedSource?.name === parsedOriginal.name,
    warnings: [...first.warnings, ...back.warnings],
    incompatible: [...first.incompatible, ...back.incompatible],
    exact_skill_bytes: source.equals(Buffer.from(back.content)),
    original_file_count: Object.keys(originalTree).length,
    recovered_file_count: Object.keys(restoredTree).length,
    missing_files: missingFiles, changed_files: changedFiles,
    license_preserved: parsedOriginal?.license === parsedBack?.license,
    metadata_preserved: JSON.stringify(parsedOriginal?.metadata) === JSON.stringify(parsedBack?.metadata),
    allowed_tools_preserved: parsedOriginal?.allowedTools === parsedBack?.allowedTools,
    body_semantics_preserved: parsedOriginal?.content === parsedBack?.content.replace(/\r\n/g, '\n'),
  });
}
report.summary = {
  translations_succeeded: report.runs.filter(r => r.forward_success && r.reverse_success).length,
  roundtrips: report.runs.length,
  exact_skill_bytes: report.runs.filter(r => r.exact_skill_bytes).length,
  full_bundle_recovery: report.runs.filter(r => !r.missing_files.length && !r.changed_files.length).length,
};
mkdirSync(dirname(reportPath), { recursive: true });
writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report.summary));
