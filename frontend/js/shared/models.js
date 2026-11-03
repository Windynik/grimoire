// Pure helpers for the local model list that /api/ai/status returns.

/** Return true when name is the recommended model, by exact name or "name:tag" prefix. */
export function isRecommended(ai, name) {
  return Boolean(ai && ai.recommended)
    && (name === ai.recommended || name.startsWith(`${ai.recommended}:`));
}
