export type SseHandler = (eventName: string, data: unknown) => void;

export async function parseSseStream(
  response: Response,
  onEvent: SseHandler,
): Promise<void> {
  if (!response.body) {
    throw new Error("Response has no body");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: false });
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = drainEvents(buffer, onEvent);
    }
    buffer += decoder.decode();
    drainEvents(buffer, onEvent);
  } finally {
    reader.releaseLock();
  }
}

function drainEvents(buffer: string, onEvent: SseHandler): string {
  let idx = buffer.indexOf("\n\n");
  while (idx !== -1) {
    const block = buffer.slice(0, idx);
    buffer = buffer.slice(idx + 2);
    const parsed = parseEventBlock(block);
    if (parsed) {
      onEvent(parsed.event, parsed.data);
    }
    idx = buffer.indexOf("\n\n");
  }
  return buffer;
}

interface ParsedEvent {
  event: string;
  data: unknown;
}

function parseEventBlock(block: string): ParsedEvent | null {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    const colonIdx = line.indexOf(":");
    const field = colonIdx === -1 ? line : line.slice(0, colonIdx);
    const value =
      colonIdx === -1
        ? ""
        : line.slice(colonIdx + 1).replace(/^ /, "");
    if (field === "event") {
      eventName = value;
    } else if (field === "data") {
      dataLines.push(value);
    }
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  let data: unknown;
  try {
    data = JSON.parse(dataStr);
  } catch {
    data = dataStr;
  }
  return { event: eventName, data };
}
