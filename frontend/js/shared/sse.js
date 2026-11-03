// Read a server-sent event stream from a fetch Response.

/**
 * Call onEvent(parsed) for each "data: " line of the stream.
 * A line that is not valid JSON is skipped with a console.warn.
 * The promise resolves when the stream ends.
 *
 * @param {Response} response
 * @param {function(Object): (void|Promise<void>)} onEvent
 */
export async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  async function handle(message) {
    for (const line of message.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      let data;
      try {
        data = JSON.parse(line.slice(6));
      } catch (error) {
        console.warn("Skipped an unreadable stream line:", line);
        continue;
      }
      await onEvent(data);
    }
  }

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      const messages = buffer.split("\n\n");
      buffer = messages.pop() || "";
      for (const message of messages) await handle(message);
    }
    if (done) break;
  }
  buffer += decoder.decode();
  if (buffer.trim()) await handle(buffer);
}
