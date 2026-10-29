import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

const networkRestrictions = [
  { selector: "CallExpression[callee.name='fetch']", message: 'API requests belong in src/api/.' },
  {
    selector: "CallExpression[callee.property.name='fetch']",
    message: 'API requests belong in src/api/.',
  },
  {
    selector: 'NewExpression[callee.name=/^(XMLHttpRequest|WebSocket|EventSource)$/]',
    message: 'Use the approved API layer.',
  },
];
const securityRestrictions = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: 'Untrusted values must remain text.',
  },
  {
    selector: 'AssignmentExpression[left.property.name=/^(innerHTML|outerHTML)$/]',
    message: 'Untrusted values must remain text.',
  },
  {
    selector: "CallExpression[callee.property.name='insertAdjacentHTML']",
    message: 'Untrusted values must remain text.',
  },
];

export default tseslint.config(
  { ignores: ['dist/**', 'src/contracts/generated/**', 'public/mockServiceWorker.js'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['**/contracts/generated/**', '**/generated/**'],
              message: 'Import contract types from src/contracts/.',
            },
          ],
        },
      ],
      'no-restricted-syntax': ['error', ...networkRestrictions, ...securityRestrictions],
    },
  },
  {
    files: ['src/api/**/*.{ts,tsx}'],
    rules: { 'no-restricted-syntax': ['error', ...securityRestrictions] },
  },
  {
    files: ['src/contracts/index.ts'],
    rules: { 'no-restricted-imports': ['error', { patterns: ['axios'] }] },
  },
);
