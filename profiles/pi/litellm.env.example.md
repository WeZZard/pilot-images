# Gateway environment contract (host-side template — never installed into images)

VM agents reach every model through one LiteLLM gateway (`<gateway-host>`).
The image carries the *provider configuration* (`settings.image.json`); the
*credentials* travel only in credential packs (`~/.config/vm-credentials/`),
as environment variables in `env.extra`, which the injector merges into the
guest's `~/.config/zsh/secrets.zsh`.

The guest sees a plain API endpoint — nothing about the gateway architecture
is visible to agents running inside VMs.

## env.extra contents (values filled by the owner on the host)

```zsh
# pi agent: LiteLLM provider credentials (pi-provider-litellm env contract)
export LITELLM_BASE_URL=http://<gateway-host>
export LITELLM_API_KEY=sk-...

# Claude Code: transparent Anthropic-compatible endpoint through the gateway
export ANTHROPIC_BASE_URL=http://<gateway-host>
export ANTHROPIC_AUTH_TOKEN=sk-...

# Tokens passed through to tools that read them natively
export GH_TOKEN=...
```

`LITELLM_BASE_URL` and `ANTHROPIC_BASE_URL` are read from the calling
shell's environment by `host/make-pack.zsh`, which fails clearly if either is
unset. Set both to your own LiteLLM gateway's origin before running it.

## Which key for which agent

| Agent | Key | Model scope |
|---|---|---|
| pi (`defaultProvider: litellm`) | `LITELLM_API_KEY` | glm/deepseek/gpt/grok/kimi |
| Claude Code | `ANTHROPIC_AUTH_TOKEN` | claude-* only |

Both keys are LiteLLM virtual keys managed on the gateway; they are not tied
to any subscription identity, so any number of VMs may run concurrently.

## Image-side requirements (already in settings.image.json)

- package `npm:pi-provider-litellm` registered
- `litellm.providers.litellm.apiKey = "$LITELLM_API_KEY"` (reads the env var)
- `allowInsecureHttp: true` (the gateway is plain HTTP over the LAN)
