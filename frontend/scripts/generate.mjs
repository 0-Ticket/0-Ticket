// contracts/와 API 응답 모델이 원본이다. 생성 파일은 직접 고치지 않는다.
import { compile, compileFromFile } from "json-schema-to-typescript";
import { format } from "prettier";
import { execFileSync } from "node:child_process";
import { readdir, readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { resolve, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const out = resolve(root, "frontend/src/api/generated");
const check = process.argv.includes("--check");
const options = {
  bannerComment: "/* Generated. Do not edit. Run pnpm contracts. */",
  unknownAny: true,
};
const files = new Map();
for (const name of (await readdir(resolve(root, "contracts")))
  .filter((n) => n.endsWith(".schema.json"))
  .sort()) {
  files.set(
    `contract-${name.replace(".schema.json", "")}.ts`,
    await compileFromFile(resolve(root, "contracts", name), options),
  );
}
const schemas = JSON.parse(
  execFileSync("uv", ["run", "python", "scripts/export_api_schemas.py"], {
    cwd: root,
    encoding: "utf8",
  }),
);
for (const [name, schema] of Object.entries(schemas))
  files.set(`${name}.ts`, await compile(schema, name, options));
await mkdir(out, { recursive: true });
let differs = false;
for (const [name, generated] of files) {
  const text = await format(generated, { parser: "typescript" });
  if (check) {
    let old = "";
    try {
      old = await readFile(resolve(out, name), "utf8");
    } catch {
      /* Missing file is a diff. */
    }
    if (old !== text) {
      differs = true;
      console.error(`생성 차이: ${name}`);
    }
  } else await writeFile(resolve(out, name), text);
}
for (const name of await readdir(out))
  if (!files.has(name)) {
    if (check) {
      differs = true;
      console.error(`불필요한 생성 파일: ${name}`);
    } else await rm(resolve(out, name));
  }
if (differs) process.exitCode = 1;
else
  console.log(
    `${relative(root, out)}: ${files.size}개 ${check ? "일치" : "생성"}`,
  );
