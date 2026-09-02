import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { FullConfig } from "@playwright/test";

const ADMIN_PERSONAL_NUMBER = "1000001";
const ADMIN_BOOTSTRAP_PASSWORD = "ChangeMeOnFirstLogin!";

async function findPython(backendDirectory: string): Promise<string> {
  const venvPythons = [
    resolve(backendDirectory, ".venv", "Scripts", "python.exe"),
    resolve(backendDirectory, ".venv", "bin", "python"),
  ];

  for (const venvPython of venvPythons) {
    try {
      await access(venvPython);
      return venvPython;
    } catch {
      // Try the next platform-specific virtualenv location.
    }
  }

  return "python";
}

export default async function prepareAdminFlow(_config: FullConfig): Promise<void> {
  const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
  const backendDirectory = resolve(frontendDirectory, "..", "backend");
  const python = await findPython(backendDirectory);

  await new Promise<void>((resolvePromise, reject) => {
    const child = spawn(
      python,
      ["-m", "app.scripts.reset_password", ADMIN_PERSONAL_NUMBER, ADMIN_BOOTSTRAP_PASSWORD],
      { cwd: backendDirectory, env: process.env, stdio: "inherit" },
    );
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) resolvePromise();
      else reject(new Error(`Could not prepare the forced-password admin: exit code ${code ?? "unknown"}`));
    });
  });
}
