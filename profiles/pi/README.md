# pi image profile

Default-deny allowlist for what of pi's configuration enters golden images.
Anything not present in this directory stays on the machine it came from.

## Included in images (this directory)

- `settings.image.json` — installed as `~/.pi/agent/settings.json`. Packages
  (owner-approved 2026-08-12; pi-provider-litellm added 2026-09-10):
  pi-web-access, @zigai/pi-prompt-history, git:WeZZard/workflows (unpinned —
  tracks releases via the update cron), @juicesharp/rpiv-ask-user-question,
  pi-subagents, @juicesharp/rpiv-todo, pi-cc-extensions, pi-provider-litellm.
  LiteLLM is the unique model provider (`defaultProvider: litellm`,
  `defaultModel: glm-5.3-flash`); the provider reads `LITELLM_API_KEY` from
  the environment (`litellm.providers.litellm.apiKey = "$LITELLM_API_KEY"`,
  `allowInsecureHttp: true` for the LAN's plain-HTTP gateway). No provider
  credential is embedded here — auth arrives via the credential pack.
- `litellm.env.example.md` — the gateway environment contract: which env vars
  the pack must deliver, which key serves which agent. Host-side template,
  never installed into images.
- `keybindings.json` — carried per owner pick. Note: its stated purpose is to
  let pi-ui-hephaestus own ctrl+v, and hephaestus is NOT in the image profile.
- `web-search.json` — pi-web-access configuration.

## Deliberately excluded (local-only on the host Mac)

- `auth.json` — NEVER here. In the gateway era packs carry no pi auth at all:
  pi authenticates with `LITELLM_API_KEY` from the pack's `env.extra`
  (`host/make-pack.zsh` → `~/.config/vm-credentials/<pack>/env.extra`).
- pi-ui-hephaestus (+ its settings block), pi-language-tutor +
  language-learn.json, pi-cover-image, pi-x-articles, attune, additive
  (local-path packages), skill co-browse, trust.json, models-store.json,
  sessions/, run-history.jsonl, caches.

## Changing the profile

Edit `settings.image.json`, then either rebuild the base or apply during a
maintenance boot (`host/refresh-base.zsh` + rerun phase 50 payload). Purpose-
specific extras (e.g. blog tooling) belong in a per-purpose overlay applied to
clones, not in the base profile.
