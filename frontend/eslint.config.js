import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import prettier from 'eslint-config-prettier'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'src/components/data-table/**', 'src/components/custom/**', 'src/components/controls.tsx', 'src/lib/store/**', 'src/lib/table-schema/**', 'src/lib/table/**', 'src/lib/data-table/**', 'src/lib/format.ts', 'src/lib/delimiters.ts', 'src/lib/is-array.ts', 'src/lib/compose-refs.ts', 'src/lib/date-preset.ts', 'src/lib/react-table.d.ts', 'src/lib/constants/**', 'src/hooks/use-debounce.ts', 'src/hooks/use-hot-key.ts', 'src/hooks/use-media-query.ts', 'src/hooks/use-local-storage.ts', 'src/hooks/use-copy-to-clipboard.ts'] },
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
        { allowConstantExport: true, allowExportNames: ['useAuth', 'useTheme', 'useToast', 'useSidebar'] },
      ],
    },
  },
)
