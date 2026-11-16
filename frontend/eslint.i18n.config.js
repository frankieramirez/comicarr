// Scan for user-facing text that has not been wrapped for translation.
// Used only by scripts/check-unlocalized.mjs, which compares the per-file
// counts against the shrink-only baseline in i18n-baseline.json. Kept out of
// eslint.config.js so the everyday lint stays fast and does not need type info.
import lingui from 'eslint-plugin-lingui'
import tseslint from 'typescript-eslint'

// The Lingui rule's ignore patterns see only a string's value, so to keep
// identifiers out they also skip single lowercase words. In JSX text and in
// visible attributes a single word ("ready", "downstream") is still text, so
// this local rule covers those positions.
const VISIBLE_ATTRIBUTES = new Set([
  'title', 'placeholder', 'alt', 'aria-label', 'aria-description',
  'aria-placeholder', 'aria-roledescription', 'aria-valuetext', 'label',
  'description', 'helpText', 'tooltip',
])
const local = {
  rules: {
    'visible-text': {
      meta: { type: 'problem', schema: [] },
      create(context) {
        const insideTrans = (node) => {
          for (let p = node.parent; p; p = p.parent) {
            if (p.type === 'JSXElement' && p.openingElement.name.name === 'Trans') return true
          }
          return false
        }
        return {
          JSXText(node) {
            if (/[A-Za-z]/.test(node.value) && !insideTrans(node)) {
              context.report({ node, message: 'Visible text not marked for translation.' })
            }
          },
          JSXAttribute(node) {
            const name = node.name.type === 'JSXIdentifier' ? node.name.name : null
            const value = node.value
            if (name && VISIBLE_ATTRIBUTES.has(name) && value?.type === 'Literal' &&
                typeof value.value === 'string' && /[A-Za-z]/.test(value.value) &&
                // A URL, host:port, address or path example is not text.
                !/^[^\s]*[:/@.\d_,][^\s]*$/.test(value.value)) {
              context.report({ node: value, message: 'Visible attribute not marked for translation.' })
            }
          },
        }
      },
    },
  },
}

export default tseslint.config(
  {
    ignores: [
      'dist',
      'src/lib/react-table.d.ts',
      'src/locales/**',
      'src/types/**',
      'src/lib/mockData.ts',
      '**/*.test.{ts,tsx}',
      '**/__tests__/**',
      'tests/**',
      '*.config.{js,ts}',
      'scripts/**',
    ],
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parser: tseslint.parser },
    plugins: { lingui, local },
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    rules: {
      'local/visible-text': 'error',
      'lingui/no-unlocalized-strings': [
        'error',
        {
          ignore: [
            // No lowercase-then-space word pattern: identifiers, enum values,
            // CSS classes, paths, keys, single tokens like "G S" or "⌘K".
            '^(?![A-Z][a-z]*\\b)[^\\s]+$',
            '^[A-Z0-9_\\-:./ ]+$',
            '^[^A-Za-z]*$',
            // Class lists outside className/cn(): every token has a - or :.
            '^(?:\\S*[-:\\[]\\S*\\s*)+$',
            '^https?://',
            // One token with an inner dot, slash, digit or similar: file names,
            // paths. Not a word ending in punctuation, like "Saved.".
            '^[^\\s]*[./@:_\\d][^\\s]*[^\\s.!?…:]$',
            '^use (?:client|strict)$',
            // Product names stay as they are in every language.
            '^(?:Deluge|Transmission|ComicVine|Metron|MangaDex|MyAnimeList|Prowlarr|Mylar3?|Comicarr|GetComics|Pixeldrain|MediaFire|Mega)$',
          ],
          ignoreNames: [
            { regex: { pattern: '^[A-Z0-9_]+$' } },
            { regex: { pattern: 'className|ClassName|^class$|Class$' } },
            { regex: { pattern: '^(?:key|id|type|variant|size|side|align|role|name|href|to|path|method|mode|status|state|kind|tone|icon|value|data-.*|form|target|rel|inputMode|autoComplete|sizes|accept|lang|dir|encType|htmlFor|testId|data-testid|queryKey|mutationKey|url|endpoint|tab|section|sort|order|format|unit|field|column|layout|orientation|position|style|width|height)$' } },
          ],
          ignoreFunctions: [
            'cn', 'clsx', 'cva', 'twMerge', 'console.*', 'Error', 'URLSearchParams',
            'fetch', 'apiRequest', 'api.*', '*.get', '*.set', '*.has', '*.delete', 'searchParams.*',
            'navigate', 'querySelector', 'querySelectorAll', '*.addEventListener', '*.removeEventListener',
            'localStorage.*', 'sessionStorage.*', 'useQueryState', 'parseAsString*', 'z.*', 'require',
            'new Date', 'Date.parse', '*.startsWith', '*.endsWith', '*.includes', '*.split', '*.replace',
            '*.replaceAll', '*.accessor', '*.match', '*.test', 'RegExp', 'invariant', 'encodeURIComponent', 'postMessage',
            'dispatchEvent', 'CustomEvent', 'Event', 'matchMedia', '*.getItem', '*.setItem', '*.removeItem',
            'document.*', 'window.*', 'expect',
          ],
        },
      ],
    },
  },
)
