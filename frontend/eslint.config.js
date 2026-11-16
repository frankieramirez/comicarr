import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'
import lingui from 'eslint-plugin-lingui'

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
      'no-restricted-syntax': [
        'error',
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
      ],
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
