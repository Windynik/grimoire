// The files that the collection import takes: a CSV export of a collection
// app, or a plain card list.

export const IMPORT_ACCEPT = ".csv,.tsv,.txt";
export const WRONG_FILE = "Choose a CSV file or a card list (.txt).";

/** True for a file name that the import takes. */
export function isImportFile(name) {
  return /\.(csv|tsv|txt)$/i.test(String(name || ""));
}

/** The source line of an import summary, such as "Read as a Moxfield export." */
export function sourceText(label) {
  if (!label) return "";
  // The server says "a CSV file" or "a card list" when no app matched.
  if (/^an? /.test(label)) return `Read as ${label}.`;
  return `Read as an export of ${label}.`;
}
