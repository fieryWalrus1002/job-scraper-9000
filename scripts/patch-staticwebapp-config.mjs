// Patches <YOUR-TENANT-ID> in dist/staticwebapp.config.json with AZURE_TENANT_ID.
// Run automatically via the "postbuild" npm script after `npm run build`.
//
// - In CI: AZURE_TENANT_ID must be set or the build fails loudly.
// - Locally: missing env var emits a warning and exits cleanly (placeholder stays).
import fs from "node:fs";
import path from "node:path";

const tenantId = process.env.AZURE_TENANT_ID;
const configPath = path.resolve("dist", "staticwebapp.config.json");

if (!fs.existsSync(configPath)) {
  throw new Error(`Missing generated SWA config: ${configPath}`);
}

if (!tenantId) {
  if (process.env.CI) {
    throw new Error("AZURE_TENANT_ID is required when building in CI.");
  }
  console.warn(
    "AZURE_TENANT_ID is not set. Leaving <YOUR-TENANT-ID> placeholder unchanged."
  );
  process.exit(0);
}

const config = fs.readFileSync(configPath, "utf8");

if (!config.includes("<YOUR-TENANT-ID>")) {
  console.warn(
    "No <YOUR-TENANT-ID> placeholder found in dist/staticwebapp.config.json — already patched?"
  );
  process.exit(0);
}

const patched = config.replaceAll("<YOUR-TENANT-ID>", tenantId);
fs.writeFileSync(configPath, patched);
console.log("Patched dist/staticwebapp.config.json with AZURE_TENANT_ID.");
