import assert from 'node:assert/strict';
import test from 'node:test';
import { EDITOR_LANGUAGES, classroomEditorReadOnly, monacoLanguageFor, selectEditorLanguage, shouldApplyEditorSnapshot } from './editorLanguages.js';

test('selecting Python updates the controlled language used by Monaco', () => {
  let selectedLanguage = 'javascript';
  const changed = selectEditorLanguage('python', value => { selectedLanguage = value; });

  assert.equal(changed, true);
  assert.equal(selectedLanguage, 'python');
  assert.equal(monacoLanguageFor(selectedLanguage), 'python');
  assert.ok(EDITOR_LANGUAGES.some(language => language.value === 'python'));
});

test('unsupported selection values do not alter the controlled language', () => {
  let selectedLanguage = 'javascript';
  const changed = selectEditorLanguage('ruby', value => { selectedLanguage = value; });

  assert.equal(changed, false);
  assert.equal(selectedLanguage, 'javascript');
});

test('an active classroom participant gets an editable Monaco editor', () => {
  assert.equal(classroomEditorReadOnly('in_progress', true), false);
  assert.equal(classroomEditorReadOnly('in_progress', false), true);
  assert.equal(classroomEditorReadOnly('not_started', true), true);
});

test('equal or stale collaboration snapshots cannot reset a newer language choice', () => {
  assert.equal(shouldApplyEditorSnapshot(4, 4, true), false);
  assert.equal(shouldApplyEditorSnapshot(3, 4, true), false);
  assert.equal(shouldApplyEditorSnapshot(5, 4, true), true);
  assert.equal(shouldApplyEditorSnapshot(0, 0, false), true);
});
