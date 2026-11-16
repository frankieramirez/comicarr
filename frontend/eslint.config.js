import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'
import lingui from 'eslint-plugin-lingui'

// Comicarr ships right-to-left languages, so spacing, alignment and placement
// use logical utilities (ms/me, ps/pe, start/end, text-start, border-s,
// rounded-s) that follow the reading direction. A physical left/right class
// stays put and leaves the layout half-mirrored. Centering with left-1/2 or
// left-[50%] plus a translate is direction-neutral, so it is allowed.
const PHYSICAL_CLASS =
  String.raw`/(^|[\s"'\x60:])!?-?((m|p)[lr]|left|right|scroll-[mp][lr])-(?!1.2([\s"'\x60]|$)|\[50%\])(\d|\[|auto|full|px)|(^|[\s"'\x60:])(text-(left|right)|border-[lr]|rounded-[tb]?[lr])(-|[\s"'\x60]|$)/`
const physicalClassMessage =
  'Use a logical class (ms/me, ps/pe, start/end, text-start/end, border-s/e, rounded-s/e) so the layout mirrors in right-to-left languages.'
const PHYSICAL_CLASS_RULES = [
  { selector: `Literal[value=${PHYSICAL_CLASS}]`, message: physicalClassMessage },
  { selector: `TemplateElement[value.raw=${PHYSICAL_CLASS}]`, message: physicalClassMessage },
]
const LOCALE_RULES = [
  {
    selector: "Literal[value='en-US']",
    message: 'Do not hardcode a locale. Format through @/lib/intl, which follows the active language.',
  },
  {
    selector: "CallExpression[callee.property.name=/^toLocale(Date|Time)?String$/]",
    message: 'Format dates and numbers through @/lib/intl (formatDate, formatNumber) so they follow the active language.',
  },
  {
    selector: "NewExpression[callee.object.name='Intl']",
    message: 'Build Intl formatters through @/lib/intl so they use the active language and are cached.',
  },
]

export default tseslint.config(
  // The data-table ignore also covered the shared renderer the product tables
  // actually use, so it had never been linted. Now that the unused schema-driven
  // table system is gone, what remains under data-table/ is live code.
  { ignores: ['dist', 'src/lib/react-table.d.ts', 'eslint.i18n.config.js'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      lingui.configs['flat/recommended'],
      prettier,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        { varsIgnorePattern: '^_', argsIgnorePattern: '^_' },
      ],
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true, allowExportNames: ['useAuth', 'useTheme', 'useToast', 'useSidebar', 'useServerEventsHealth', 'buttonVariants'] },
      ],
      // Row identity is the invariant the data-table/useTableState seam exists
      // to centralise, and `getRowId` can only be *required* if there is one
      // place to require it from. A comment is not a seam, and a source scan
      // matches strings; this matches the import and fails at author time.
      // Dates and numbers follow the language the app runs in. A hardcoded
      // "en-US" (or the browser default from toLocale*String) ignores it, so
      // every formatter goes through src/lib/intl.ts (docs/architecture/i18n.md).
      'no-restricted-syntax': ['error', ...LOCALE_RULES, ...PHYSICAL_CLASS_RULES],
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '@tanstack/react-table',
              importNames: ['useTable'],
              message:
                'Call useTableState from @/components/data-table/useTableState instead. It wraps useTable so getRowId cannot fall back to TanStack’s index default (#307, #359).',
            },
          ],
        },
      ],
    },
  },
  {
    // The one file allowed to build Intl formatters.
    files: ['src/lib/intl.ts', 'src/lib/i18n.ts'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
  {
    // These components take a physical `side` and position by it on purpose;
    // their callers pick the side from the reading direction.
    files: ['src/components/ui/sidebar.tsx', 'src/components/ui/sheet.tsx'],
    rules: {
      'no-restricted-syntax': ['error', ...LOCALE_RULES],
    },
  },
  {
    // The one file allowed to build a table instance.
    files: ['src/components/data-table/useTableState.ts'],
    rules: {
      'no-restricted-imports': 'off',
    },
  },
  {
    files: ['playwright.config.ts', 'tests/**/*.{ts,tsx}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
)
