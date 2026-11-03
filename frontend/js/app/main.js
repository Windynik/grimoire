// Entry point: register every screen, start the shell and the router.
// This is the only script tag in index.html.

import { register, start } from "./router.js";
import { startShell } from "./shell.js";
import { enhanceSelects } from "../shared/select.js";
import * as home from "../home/home.js";
import * as collection from "../collection/viewer.js";
import * as importScreen from "../collection/import.js";
import * as forge from "../forge/forge.js";
import * as decks from "../decks/decks.js";
import * as settings from "../settings/settings.js";

register("home", home);
register("collection", collection);
register("import", importScreen);
register("forge", forge);
register("decks", decks);
register("settings", settings);

startShell();
enhanceSelects();
await start();

// Tests wait for this flag. It is set after the first route ran.
document.documentElement.dataset.ready = "true";
