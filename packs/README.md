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
| `env.extra` | `export` lines: `LITELLM_BASE_URL`, `LITELLM_API_KEY` (pi), `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` (Claude Code), `GH_TOKEN` | guest `~/.config/zsh/secrets.zsh` (sourced by every zsh through `~/.zshenv`; `gh` CLI and both agent providers read these natively) |
| `git-identity` | optional `Name <email>` | git global config |
| `home.tgz` | files for the clone's home folder, built by `host/pack-home.zsh` from the pack's `home/` folder: sign-in files an agent keeps on disk (the Antigravity CLI's `.gemini/antigravity-cli/antigravity-oauth-token`), and settings that name the gateway (DeepSeek Harness's `.dsh/profiles/<profile>/cordis.patch.yml`) | unpacked into the guest's `$HOME` |

Historical lane packs (lane-a, lane-b: `pi-auth.json`, `claude.env`,
`gh-token`) are obsolete; their files are ignored by the injector except
`env.extra`.

## Flow

```
host/make-pack.zsh vm-agents
$EDITOR ~/.config/vm-credentials/vm-agents/env.extra   # fill the four keys
host/new-clone.zsh x-research
host/inject-credentials.zsh pilot-mac-x-research ~/.config/vm-credentials/vm-agents
# or through machine-service: machctl acquire --purpose x-research --lane vm-agents
```

An agent that keeps its sign-in in a file signs in once on the host that
holds the pack; the pack carries a copy of that file to every clone:

```
host/pack-home.zsh vm-agents .gemini/antigravity-cli/antigravity-oauth-token
host/sync-pack.zsh <other-vm-host> vm-agents   # every VM host serves its own copy
```

Run both again after signing in anew on the host. A file kept only in the
pack (gateway settings) goes straight into `home/` and is packed on every run.
