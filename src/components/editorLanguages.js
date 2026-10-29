export const EDITOR_LANGUAGES = [
  { value: 'javascript', label: 'JavaScript' },
  { value: 'python', label: 'Python' },
  { value: 'html', label: 'HTML' },
  { value: 'css', label: 'CSS' },
  { value: 'c', label: 'C' },
  { value: 'cpp', label: 'C++' }
];

export function selectEditorLanguage(nextLanguage, onLanguageChange) {
  if (!EDITOR_LANGUAGES.some(({ value }) => value === nextLanguage)) return false;
  onLanguageChange(nextLanguage);
  return true;
}

export function monacoLanguageFor(language) {
  return language === 'c' ? 'cpp' : language;
}

export function shouldApplyEditorSnapshot(revision, currentRevision, initialized) {
  return !initialized || revision > currentRevision;
}

export function classroomEditorReadOnly(sessionState, collaborationJoined) {
  return sessionState !== 'in_progress' || !collaborationJoined;
}
