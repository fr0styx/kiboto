// The product's name before the rebrand, only where a one-time move needs it: settings exported
// before, and Kiboto's own container on an install made before. Nothing else in the page names it
// (index.html moves the browser's own saved settings). Goes with backend/legacy_names.py.

export const OLD_OWN_CONTAINERS = ['zettnas-toolkit', 'zettnas'];
export const OLD_SETTINGS_EXT = '.zettbak'; // a settings backup made before
export const OLD_BACKUP_MAGIC = 'ZETTBAK2'; // and how such a file starts
export const OLD_THEME_FORMAT = 'zett-theme'; // a theme file exported before

/** A saved setting's key in Kiboto's name (settings exported before the rebrand). */
export const settingKey = (key) => key.replace(/^zettnas/, 'kiboto');
