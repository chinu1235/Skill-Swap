import { useState } from 'react';
import CodeEditor, { EDITOR_STORAGE_KEY } from '../components/CodeEditor.jsx';

function readInitialCode() {
  try {
    const saved = JSON.parse(localStorage.getItem(EDITOR_STORAGE_KEY) || 'null');
    return typeof saved?.code === 'string' ? saved.code : 'function hello() {\n  console.log("Hello SkillSwap");\n}\n\nhello();';
  } catch { return 'function hello() {\n  console.log("Hello SkillSwap");\n}\n\nhello();'; }
}

function readInitialLanguage() {
  try {
    const saved = JSON.parse(localStorage.getItem(EDITOR_STORAGE_KEY) || 'null');
    return ['javascript', 'python', 'html', 'css', 'c', 'cpp'].includes(saved?.language) ? saved.language : 'javascript';
  } catch { return 'javascript'; }
}

export default function CodeEditorPage() {
  const [code, setCode] = useState(readInitialCode);
  const [language, setLanguage] = useState(readInitialLanguage);
  return <section className="code-page"><div className="container code-page-container">
    <div className="code-page-heading"><div><span className="eyebrow">A place to practice</span><h1>SkillSwap Code Editor</h1><p>Try an idea, make a change, and see what happens.</p></div><span className="code-heading-icon" aria-hidden="true">&lt;/&gt;</span></div>
    <CodeEditor value={code} onChange={setCode} language={language} onLanguageChange={setLanguage} />
    <p className="code-page-note">JavaScript runs in a browser sandbox. Other languages are ready for a future execution service.</p>
  </div></section>;
}
