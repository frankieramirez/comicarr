import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  // The data-table ignore also covered the shared renderer the product tables
  // actually use, so it had never been linted. Now that the unused schema-driven
  // table system is gone, what remains under data-table/ is live code.
  { ignores: ['dist', 'src/components/custom/**', 'src/components/controls.tsx', 'src/lib/format.ts', 'src/lib/delimiters.ts', 'src/lib/is-array.ts', 'src/lib/compose-refs.ts', 'src/lib/date-preset.ts', 'src/lib/react-table.d.ts', 'src/lib/constants/**', 'src/hooks/use-debounce.ts', 'src/hooks/use-hot-key.ts', 'src/hooks/use-media-query.ts', 'src/hooks/use-local-storage.ts', 'src/hooks/use-copy-to-clipboard.ts'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
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
        { allowConstantExport: true, allowExportNames: ['useAuth', 'useTheme', 'useToast', 'useSidebar', 'buttonVariants'] },
      ],
      // Row identity is the invariant the data-table/useTableState seam exists
      // to centralise, and `getRowId` can only be *required* if there is one
      // place to require it from. A comment is not a seam, and a source scan
      // matches strings; this matches the import and fails at author time.
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '@tanstack/react-table',
              importNames: ['useReactTable'],
              message:
                'Call useTableState from @/components/data-table/useTableState instead. It wraps useReactTable so getRowId cannot fall back to TanStack’s index default (#307, #359).',
            },
          ],
        },
      ],
    },
  },
  {
    // The one file allowed to build a table instance.
    files: ['src/components/data-table/useTableState.ts'],
    rules: {
      'no-restricted-imports': 'off',
      // React Compiler flags useReactTable as an incompatible library. This
      // disable used to be repo-wide because the call sites were scattered;
      // confining them to one file is what lets it narrow to one file.
      'react-hooks/incompatible-library': 'off',
    },
  },
  {
    // RATCHET — tables not yet migrated to useTableState. Each migration PR
    // deletes its own line; the last one deletes this whole block. A file that
    // is not listed here fails immediately, so a *new* call site cannot appear
    // while the migration is in flight. Tracked by #353.
    files: [
      'src/components/series/SeriesTable.tsx', // #394
      'src/components/queue/WantedTable.tsx', // #395
      'src/components/queue/UpcomingTable.tsx', // #395
      'src/components/import/ImportTable.tsx', // #396
    ],
    rules: {
      'no-restricted-imports': 'off',
      'react-hooks/incompatible-library': 'off',
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
