# Scripts

## Prerequisites

- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated: `gh auth login`
- Permission to set **Actions** repository secrets for the target repo

## `push-github-secrets`

Uploads secrets from a dotenv file or from your current shell environment to GitHub using `gh secret set`. Used with the [Deploy workflow](../.github/workflows/deploy.yml).

### Secret names

| Name | Used for |
|------|----------|
| `CORS_ORIGINS` | Allowed browser origins (comma-separated) |
| `OPENROUTER_KEY` | Reserved for future use |
| `ANALYTICS_ADMIN_KEY` | Reserved for future use |
| `VPS_HOST` | Deploy SSH host |
| `VPS_USER` | Deploy SSH user |
| `VPS_SSH_KEY` | Private key for SSH (can be multiline in dotenv) |
| `GH_PAT` | Token for `docker login ghcr.io` on the server |

Keep local copies only in files that are gitignored (for example `.env.secrets`).

### Mode 1: Dotenv file (recommended)

Put one `KEY=value` per line (GitHub CLI dotenv rules apply; multiline values are supported as in `gh secret set -f`).

**PowerShell (repo root):**

```powershell
.\scripts\push-github-secrets.ps1 -EnvFile .\.env.secrets
```

**Git Bash / WSL / Linux:**

```bash
./scripts/push-github-secrets.sh --env-file .env.secrets
```

### Mode 2: Current environment

Exports values from **process**, then **user**, then **machine** environment (PowerShell), or from the shell environment (bash). Any name that is unset is skipped.

**PowerShell:**

```powershell
.\scripts\push-github-secrets.ps1 -FromEnvironment
```

**Bash:**

```bash
export VPS_HOST=example.com
# ... set other variables ...
./scripts/push-github-secrets.sh --from-environment
```

### Another repository

If you are not in the checkout of the target repo, pass the repo explicitly:

**PowerShell:**

```powershell
.\scripts\push-github-secrets.ps1 -EnvFile .\.env.secrets -Repo owner/repo-name
```

**Bash:**

```bash
./scripts/push-github-secrets.sh --env-file .env.secrets --repo owner/repo-name
```

### PowerShell only: custom secret list

When using `-FromEnvironment`, you can override which variable names are read:

```powershell
.\scripts\push-github-secrets.ps1 -FromEnvironment -SecretNames @('VPS_HOST','GH_PAT')
```

### Troubleshooting

- **`gh is not authenticated`:** Run `gh auth login` and ensure the token can manage repository secrets.
- **Wrong repo:** Use `-Repo` / `--repo` or run the script from a clone whose `origin` matches the target (when `-Repo` is omitted, `gh` uses the current repo).
