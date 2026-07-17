# AI features

[← Back to README](../README.md)

EC Weather can use Home Assistant's AI Task integration to make weather data easier to read. Every AI feature is opt-in and off by default.

> **Beta.** AI features are currently in beta. Their behavior and defaults may change between releases. Feedback is welcome via GitHub issues.

## How AI is used here

The integration follows a few principles that apply to every AI feature:

- AI only ever enhances presentation. It never gates access to data, and it never hides or drops anything.
- It always fails open. If the AI is missing, times out, or returns an invalid answer, you get the plain, un-enhanced view, never an error and never a blank.
- It is called sparingly. The integration asks the AI only when the underlying data changes, not on every poll, and it adds no Environment Canada API calls.

## Requirements

These apply to every AI feature:

- Home Assistant 2025.7 or newer (for the `ai_task` integration).
- An integration that provides an AI Task entity. Ollama, OpenAI, Anthropic, and Google all provide one since HA 2025.8.

Local models (for example Ollama) are the design target: the defaults are tuned to run well on a small model on your own hardware, with no cloud dependency and no per-call cost. Where a feature lets you pick an AI Task entity, leaving the field empty uses Home Assistant's preferred AI Task entity.

## Model choice and prompt tuning

The default prompts are developed and validated against a small local model (a qwen3 4B-class model via Ollama). Larger or cloud models generally work too, but they can judge differently, so a feature's defaults are calibrated for the small-model case rather than the most capable one.

Features that expose an editable instructions field let you change the judgment the AI makes. The output format is always fixed in code and is not editable: you tune what the AI decides, not how the result is shaped.

When editing instructions:

- Keep the rules short and positive.
- Avoid "when in doubt, do nothing" escape hatches. Small models read those as permission to stop acting entirely.
- Put the rule you most need obeyed at the end. Small models weight the most recent instruction most heavily.

Clearing an instructions field restores its default. If you never customized it, you automatically track improvements to that default.

## Alert grouping

Environment Canada often publishes several alerts for one weather event: a severe thunderstorm warning alongside its watch, or one storm covered by several bulletins. Alert grouping asks an AI Task to decide which active alerts describe the same event, so the card can show them as one alert with its related bulletins nested inside.

### What it does

With grouping on, related alerts fold into a single bar in the `alerts` section:

- The most severe alert in the group is the primary and its headline is shown on the bar (a warning outranks a watch, a watch an advisory, an advisory a statement).
- A muted `+N` pill after the headline counts the related alerts.
- Expanding the bar shows the primary text, then each related alert as a collapsed, tappable row that opens its own detail.

Alerts that do not belong to any group render on their own, exactly as before.

### How to enable

Settings → Integrations → EC Weather → Configure. The options live in the collapsed "Beta" section of the configure dialog; expand it to reveal them. Three options control the feature:

| Option | What it does |
|---|---|
| Group related alerts with AI | Turns the feature on. Off by default. |
| AI Task entity | Which AI Task entity to use. Leave empty to use your preferred AI Task entity. |
| AI grouping instructions | How the AI decides which alerts belong together. The default works well; edit it only to change the grouping judgment. |

The integration reloads itself when you save.

### Safety guarantees

Grouping only annotates how alerts are presented. It never changes what is active:

- No alert is ever hidden or dropped. Every active alert still renders, grouped or not.
- The alert count and the highest-severity state are unchanged.
- Any AI failure (the service is missing, times out, or returns an invalid answer) simply shows the alerts ungrouped. Grouping never fails an alert update.
- If the AI is unavailable at Home Assistant startup (the AI Task integration may still be loading), grouping retries automatically once startup completes, so it does not wait a full poll interval.

### How it works

Before any AI is involved, two deterministic steps run on every alert refresh, independent of this option:

1. Exact duplicates are removed. EC returns one copy of an alert per sub-zone; identical `(headline, text)` copies collapse to one.
2. Per-zone copies of the same product are merged. EC issues the same product for each forecast zone in a multi-zone area, so near-identical copies that share a `(headline, type)` collapse to one, keeping the copy that stays valid longest. The card shows no zones, so this always runs.

If grouping is on and at least two alerts remain, the AI step runs:

3. The deduplicated, merged alerts are sent to `ai_task.generate_data` with a structured output schema and a 60-second timeout. The response is strictly validated (every index in range, no alert in two groups, every group has at least two members); any violation discards the whole verdict and the alerts stay ungrouped.
4. A valid verdict is cached against the current alert set and applied. The AI is called again only when the alert set changes.

When retained alerts are pruned (an alert reaches its EC expiration while a fetch is failing), the group annotations are re-validated: a group that falls below two members is dissolved, and if a group's primary expired, the highest-severity survivor is promoted.

### Model notes for grouping

On the target small model, the default instructions group a severe thunderstorm warning with its watch (warning shown first) and keep different phenomena apart, for example a heat warning and an air quality warning stay separate. Other models can judge differently: a larger model (gemma3 12B, observed) may group a heat warning and an air quality warning together. If your model groups in a way you dislike, edit the AI grouping instructions using the guidance in [Model choice and prompt tuning](#model-choice-and-prompt-tuning) above.
