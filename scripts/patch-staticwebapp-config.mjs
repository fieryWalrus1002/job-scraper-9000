// Patches <YOUR-TENANT-ID> in dist/staticwebapp.config.json with AZURE_TENANT_ID.
// Run automatically via the "postbuild" npm script after `npm run build`.
//
// If AZURE_TENANT_ID is unset (e.g. CI type-check builds, local dev without az login),
// the placeholder is left as-is and the script exits cleanly. The deploy tooling
// (just ship-frontend, or a future CD workflow) is responsible for ensuring the
// variable is present before a real deployment.
import fs from "node:fs";
import path from "node:path";

const tenantId = process.env.AZURE_TENANT_ID;
const configPath = path.resolve("dist", "staticwebapp.config.json");

if (!fs.existsSync(configPath)) {
  throw new Error(`Missing generated SWA config: ${configPath}`);
}

if (!tenantId) {
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
