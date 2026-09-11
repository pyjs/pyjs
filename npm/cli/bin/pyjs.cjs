#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

function runtimePackage() {
  const target = `${process.platform}-${process.arch}`;
  if (target === "linux-x64" || target === "linux-arm64") {
    const glibc = process.report?.getReport().header.glibcVersionRuntime;
    if (!glibc) {
      throw new Error("The PyJS npm prototype does not support Linux musl yet.");
    }
    return `@pyjsdev/cli-${target}`;
  }
  const packages = {
    "darwin-x64": "@pyjsdev/cli-darwin-x64",
    "darwin-arm64": "@pyjsdev/cli-darwin-arm64",
    "win32-x64": "@pyjsdev/cli-win32-x64",
  };
  if (packages[target]) {
    return packages[target];
  }
  throw new Error(
    `The PyJS npm prototype does not support ${process.platform}-${process.arch} yet.`,
  );
}

function resolveRuntime(packageName) {
  let manifestPath;
  try {
    manifestPath = require.resolve(`${packageName}/package.json`);
  } catch (error) {
    if (error.code !== "MODULE_NOT_FOUND") {
      throw error;
    }
    throw new Error(
      `The platform package ${packageName} is missing. ` +
        "Reinstall @pyjsdev/cli without omitting optional dependencies.",
    );
  }

  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const executable = manifest.pyjsRuntime?.python;
  if (!executable) {
    throw new Error(`${packageName} does not describe its Python executable.`);
  }
  return path.join(path.dirname(manifestPath), executable);
}

function main() {
  const python = resolveRuntime(runtimePackage());
  const environment = { ...process.env, PYTHONNOUSERSITE: "1" };
  delete environment.PYTHONHOME;
  delete environment.PYTHONPATH;

  const result = spawnSync(python, ["-m", "pyjs", ...process.argv.slice(2)], {
    env: environment,
    stdio: "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  if (result.signal) {
    process.kill(process.pid, result.signal);
  }
  process.exit(result.status ?? 1);
}

try {
  main();
} catch (error) {
  console.error(`pyjs: ${error.message}`);
  process.exit(1);
}
