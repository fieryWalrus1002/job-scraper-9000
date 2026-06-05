# Phase 9 — Azure Deployment

Written 2026-06-04. Depends on Phase 10 (auth) being merged, which it is.

## Decisions locked

- **IaC**: Bicep for all ARM resources. Entra app registration is a manual step (Microsoft Graph, not ARM).
- **Frontend host**: Azure Static Web Apps, Standard tier (required for linked backend feature).
- **Backend host**: Azure Container Apps.
- **Trust boundary**: SWA linked backend (`az staticwebapp backends link`) — Azure handles ingress locking natively. No custom shared-secret header needed.
- **Container registry**: Azure Container Registry (Basic tier).
- **DNS**: Cloudflare

## Azure resources

| Resource                   | SKU         | Notes                                                |
| -------------------------- | ----------- | ---------------------------------------------------- |
| Log Analytics workspace    | PerGB2018   | Required by ACA environment                          |
| Container Apps environment | Consumption | Linked to Log Analytics                              |
| Azure Container Registry   | Basic       | Stores FastAPI Docker image                          |
| Azure Container App        | —           | Runs FastAPI; no public ingress (locked by SWA link) |
| Azure Static Web App       | Standard    | Hosts frontend; proxies `/api/*` to ACA              |

## Bicep structure

```
infra/
  main.bicep          # entry point, wires modules, outputs SWA URL
  main.bicepparam     # non-secret values (location, app name, tenant ID, etc.)
  modules/
    loganalytics.bicep
    registry.bicep
    containerApp.bicep
    staticWebApp.bicep
```

Tenant ID, client ID, and ACA image tag are parameters. Client secret is a `@secure()` parameter passed at deploy time (not stored in the param file).

## `/api` routing — verify before deploy

SWA proxies `/api/*` to the linked ACA backend. Need to confirm whether SWA strips the `/api` prefix before forwarding, or passes the full path. Current FastAPI routes are at `/api/*`. If SWA strips the prefix, routes need to move to root and `root_path="/api"` set in FastAPI for correct OpenAPI schema generation. Check against SWA linked backend docs before writing the Bicep.

## Manual steps (not in Bicep)

1. **Entra ID app registration** in the target tenant:
   - Single-tenant
   - Redirect URI: `https://<swa-domain>/.auth/login/aad/callback` (and `https://<custom-domain>/.auth/login/aad/callback` once custom domain is wired)
   - Generate a client secret; store as SWA application setting `AZURE_CLIENT_SECRET`
1. **Link SWA backend**: `az staticwebapp backends link --name <swa> --resource-group <rg> --backend-resource-id <aca-resource-id> --backend-region <region>`
1. **Custom domain**: attach `{custom-domain}` (and `jobs.{custom-domain}` or similar) to SWA via portal or CLI; update Cloudflare DNS with the verification TXT + CNAME records

## `staticwebapp.config.json`

```json
{
  "auth": {
    "identityProviders": {
      "azureActiveDirectory": {
        "registration": {
          "openIdIssuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
          "clientIdSettingName": "AZURE_CLIENT_ID",
          "clientSecretSettingName": "AZURE_CLIENT_SECRET"
        }
      }
    }
  },
  "routes": [
    {
      "route": "/api/health",
      "allowedRoles": ["anonymous"]
    },
    {
      "route": "/api/*",
      "allowedRoles": ["authenticated"]
    },
    {
      "route": "/*",
      "allowedRoles": ["authenticated"]
    }
  ],
  "responseOverrides": {
    "401": {
      "redirect": "/.auth/login/aad",
      "statusCode": 302
    }
  }
}
```

## Local dev with SWA CLI (optional)

The SWA CLI (`@azure/static-web-apps-cli`) emulates the full SWA environment locally including `/.auth/*` endpoints and header injection. Alternative to `AUTH_BYPASS` / `VITE_AUTH_BYPASS` flags for integration testing:

```bash
swa start http://localhost:5175 --api-devserver-url http://localhost:8000
```

Bypass flags stay in place for fast daily iteration without the CLI overhead.

## Migration to personal tenant (when ready)

1. Create Entra app registration in personal tenant
1. Update `main.bicepparam`: tenant ID, client ID
1. Redeploy (`az deployment group create`)
1. Update SWA app settings: new client ID + secret
1. Verify custom domain DNS

All Bicep resources are tenant-agnostic. The only tenant-specific values are the Entra app registration details, which are parameters.

## Out of scope

- CI/CD (GitHub Actions for auto-deploy) — Phase 9 standup is manual first
- Multi-region / availability zones — single region, portfolio scale
- Managed identity for ACR pull (use admin credentials initially, tighten later)
