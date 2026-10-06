// What web/client/translate.js does for every entry point. It is CommonJS that
// requires Flow sources, so register the same dictionary from here.
import I18N from 'lib/I18N';
import translations from 'i18n';

I18N.registerTranslations(translations);
