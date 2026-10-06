// Client modules read the page bootstrap at import time (dateUtil, I18N,
// timeoutSession), so it must exist before any test imports them. Tests that
// need other values call withBackend from helpers.js. This runs before
// setupTranslations.js because static imports are hoisted above any statement.
import { DEFAULT_BACKEND } from './helpers';

window.__JSON_FROM_BACKEND = structuredClone(DEFAULT_BACKEND);
