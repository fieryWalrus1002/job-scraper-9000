// SWA -> ACA backend link, declared as IaC (#133). Previously a manual
// `az staticwebapp backends link` step — tribal knowledge lost on a fresh
// deploy.
//
// This lives in its own module, NOT inside staticWebApp.bicep, to avoid a
// dependency cycle: containerApp already depends on staticWebApp (it consumes
// swaHostname for the #152 authConfig). Putting the link inside staticWebApp
// would make staticWebApp depend on containerApp's resource id -> cycle.
// As a separate leaf that depends on both, the graph stays acyclic.

param swaName string

// Resource id of the Container App to link as the SWA backend.
param backendResourceId string

// Name of the linked backend entry. Matches what `az ... backends link`
// produced (the container app name).
param backendName string

// Region of the backend (the ACA region). Required at link creation.
param region string

resource swa 'Microsoft.Web/staticSites@2023-12-01' existing = {
  name: swaName
}

// The `default` build (production environment) is created implicitly by the
// SWA; the linked backend hangs off it.
resource defaultBuild 'Microsoft.Web/staticSites/builds@2023-12-01' existing = {
  parent: swa
  name: 'default'
}

resource linkedBackend 'Microsoft.Web/staticSites/builds/linkedBackends@2023-12-01' = {
  parent: defaultBuild
  name: backendName
  properties: {
    backendResourceId: backendResourceId
    region: region
  }
}
