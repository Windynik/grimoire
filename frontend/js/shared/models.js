// Pure helpers for the local model list that /api/ai/status returns.

/** Return true when name is the recommended model, by exact name or "name:tag" prefix. */
export function isRecommended(ai, name) {
  return Boolean(ai && ai.recommended)
    && (name === ai.recommended || name.startsWith(`${ai.recommended}:`));
}

/**
 * Pick the model for the agent: the recommended model when it is installed,
 * else the default model.
 *
 * @param {{available: boolean, models: string[], default_model: ?string, recommended: ?string}} ai
 * @returns {?string} The model name, or null when no model runs.
 */
export function pickModel(ai) {
  if (!ai || !ai.available) return null;
  const models = ai.models || [];
  return models.find((name) => isRecommended(ai, name)) || ai.default_model || models[0] || null;
}
