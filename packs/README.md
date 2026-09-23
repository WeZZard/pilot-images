# Credential packs

Per-purpose credential bundles injected into purpose clones at provision
time. **Packs never live in this repo** — this file documents the schema only.
Real packs live on the host at `~/.config/vm-credentials/<pack>/` (dir 700,
files 600), assembled by `host/make-pack.zsh`.

## Doctrine (gateway era, 2026-09)

- The golden base, the pristine seed, and work VMs are credential-free —
  `host/inject-credentials.zsh` refuses any VM named `*-base`, `*-seed`, `*-work`,
  and `checks/no-secrets.zsh` enforces the same before promoting.
- **Every model in a VM is reached through the LiteLLM gateway**
  (`<gateway-host>`). The image-side pi profile (`profiles/pi/settings.image.json`)
  makes LiteLLM the unique provider; credentials travel as environment
  variables in the pack's `env.extra` (see `profiles/pi/litellm.env.example.md`).
  `host/make-pack.zsh` reads `LITELLM_BASE_URL` and `ANTHROPIC_BASE_URL` from
  the caller's environment and fails if either is unset.
- **The gateway architecture is transparent to users of the API.** Guests see
  an Anthropic-compatible endpoint (Claude Code) and a LiteLLM endpoint (pi).
  Nothing about the gateway chain or what backs it enters VMs, packs, or docs
  shipped into images.
- **Gateway keys are not identities.** No subscription sits behind a pack, so
  the old "one subscription = one lane = at most one running VM" rule is gone;
  one pack serves any number of concurrent VMs. The per-lane `assigned` marker
  is no longer used.
- Never promote or re-base an injected clone.

## Pack layout

| File | Content | Consumed by |
|---|---|---|
| `env.extra` | `export` lines: `LITELLM_BASE_URL`, `LITELLM_API_KEY` (pi), `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` (Claude Code), `GH_TOKEN` | guest `~/.config/zsh/secrets.zsh` (sourced by shells; `gh` CLI and both agent providers read these natively) |
| `git-identity` | optional `Name <email>` | git global config |

Historical lane packs (lane-a, lane-b: `pi-auth.json`, `claude.env`,
`gh-token`) are obsolete; their files are ignored by the injector except
`env.extra`.

## Flow

```
host/make-pack.zsh vm-agents
$EDITOR ~/.config/vm-credentials/vm-agents/env.extra   # fill the four keys
host/new-clone.zsh x-research
host/inject-credentials.zsh pilot-mac-x-research ~/.config/vm-credentials/vm-agents
# or through vm-service: vmctl acquire --purpose x-research --lane vm-agents
```
