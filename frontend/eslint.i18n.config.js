// Scan for user-facing text that has not been wrapped for translation.
// Used only by scripts/check-unlocalized.mjs, which compares the per-file
// counts against the shrink-only baseline in i18n-baseline.json. Kept out of
// eslint.config.js so the everyday lint stays fast and does not need type info.
import lingui from 'eslint-plugin-lingui'
import tseslint from 'typescript-eslint'

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
    plugins: { lingui },
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    rules: {
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
            '^(?:\S*[-:\[]\S*\s*)+$',
            '^https?://',
            '^use (?:client|strict)$',
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
            '*.replaceAll', '*.match', '*.test', 'RegExp', 'invariant', 'encodeURIComponent', 'postMessage',
            'dispatchEvent', 'CustomEvent', 'Event', 'matchMedia', '*.getItem', '*.setItem', '*.removeItem',
            'document.*', 'window.*', 'expect',
          ],
        },
      ],
    },
  },
)
