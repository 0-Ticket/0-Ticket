import { compileFromFile } from 'json-schema-to-typescript';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { resolve, basename } from 'node:path';

const target = process.argv[2];
const source = process.argv[3];
const header = '/* 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py */';
const names = (await readdir(source)).filter(n => n.endsWith('.schema.json')).sort();
for (const name of names) {
  const output = await compileFromFile(resolve(source, name), {
    bannerComment: header, cwd: source,
    additionalProperties: false, format: true, style: { singleQuote: true },
  });
  await writeFile(resolve(target, name.replace('.schema.json', '.ts')), output);
}
// Export just the root interface from each module; referenced interfaces may recur locally.
const lines = [];
for (const name of names) {
  const schema = JSON.parse(await readFile(resolve(source, name), 'utf8'));
  lines.push(`export type { ${schema.title} } from './${basename(name, '.schema.json')}.js';`);
}
await writeFile(resolve(target, 'index.ts'), header + '\n' + lines.join('\n') + '\n');
