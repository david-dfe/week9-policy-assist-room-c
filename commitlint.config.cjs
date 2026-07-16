// Conventional Commits config for commitlint. See CLAUDE.md §5.
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'chore', 'docs', 'refactor', 'test', 'ci', 'build', 'perf', 'revert'],
    ],
    // Inherits subject-case from config-conventional: rejects
    // sentence-case, start-case, pascal-case, and upper-case
    // (so acronyms like "PR" or "CVE" embedded in an otherwise
    // lower-case subject are allowed).
    'subject-full-stop': [2, 'never', '.'],
    'header-max-length': [2, 'always', 100],
    'body-max-line-length': [1, 'always', 100],
  },
};
