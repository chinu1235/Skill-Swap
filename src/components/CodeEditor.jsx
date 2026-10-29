import { useRef, useState } from 'react';
import Editor, { loader } from '@monaco-editor/react';
import { EDITOR_LANGUAGES, monacoLanguageFor, selectEditorLanguage } from './editorLanguages.js';

// Serve Monaco from the installed package so it does not depend on a CDN.
loader.config({ paths: { vs: '/monaco-editor/min/vs' } });

export const EDITOR_STORAGE_KEY = 'skillswap-code-editor';

function LanguageSelector({ language, onLanguageChange, disabled = false, className, label = 'Language' }) {
  return <label className={className}>{label}
    <select value={language} disabled={disabled} onChange={event => selectEditorLanguage(event.currentTarget.value, onLanguageChange)}>
      {EDITOR_LANGUAGES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select>
  </label>;
}

/**
 * Reusable editor surface: value/onChange can later be connected to a shared
 * session store or websocket without coupling collaboration to this page.
 */
export default function CodeEditor({ value, onChange, language, onLanguageChange, disabled = false, readOnly = false, running = false, sharedOutput = null, runButtonLabel = 'Run', onRun, className = 'editor-workspace' }) {
  const frameRef = useRef(null);
  const [output, setOutput] = useState([]);
  const [preview, setPreview] = useState(null);
  const [saveMessage, setSaveMessage] = useState('');
  const supportedLanguage = language === 'javascript';
  const editorReadOnly = disabled || readOnly;

  const saveCode = () => {
    try {
      localStorage.setItem(EDITOR_STORAGE_KEY, JSON.stringify({ code: value, language }));
      setSaveMessage('Saved in this browser');
    } catch {
      setSaveMessage('Could not save in this browser');
    }
  };

  const clearCode = () => {
    onChange('');
    setOutput([]);
    setPreview(null);
    setSaveMessage('');
  };

  const runCode = () => {
    if (onRun) {
      onRun();
      return;
    }
    if (language === 'html') {
      setPreview({ language, code: value });
      setOutput([]);
      return;
    }
    if (language === 'css') {
      setPreview({ language, code: value });
      setOutput([]);
      return;
    }
    setPreview(null);
    if (!supportedLanguage) {
      setOutput(['Backend execution will be connected later.']);
      return;
    }
    const frame = frameRef.current;
    if (!frame) return;
    setOutput(['Running JavaScript…']);
    const safeCode = JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
    const runId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const listener = event => {
      if (event.source !== frame.contentWindow || event.data?.runId !== runId) return;
      window.removeEventListener('message', listener);
      window.clearTimeout(timeout);
      setOutput(event.data.lines.length ? event.data.lines : ['Code ran without output.']);
    };
    window.addEventListener('message', listener);
    const timeout = window.setTimeout(() => {
      window.removeEventListener('message', listener);
      setOutput(['Execution timed out. Check for code that does not finish.']);
      frame.srcdoc = '<!doctype html><html><body></body></html>';
    }, 2500);

    // The code runs in a sandboxed, opaque-origin iframe with no access to the
    // SkillSwap page DOM or its localStorage. Never use this for server execution.
    frame.srcdoc = `<!doctype html><html><body><script>
      (() => {
        const runId = ${JSON.stringify(runId)};
        const lines = [];
        const show = (...args) => lines.push(args.map(value => {
          if (typeof value === 'string') return value;
          try { return JSON.stringify(value); } catch { return String(value); }
        }).join(' '));
        console.log = show; console.info = show; console.warn = show; console.error = show;
        window.onerror = message => { lines.push('Error: ' + message); return true; };
        try { (new Function(${safeCode}))(); }
        catch (error) { lines.push(error.name + ': ' + error.message); }
        parent.postMessage({ runId, lines }, '*');
      })();
    <\/script></body></html>`;
  };

  return <section className={className} aria-label="SkillSwap code editor">
    <div className="editor-toolbar">
      <LanguageSelector className="editor-language" language={language} disabled={editorReadOnly} onLanguageChange={nextLanguage => { onLanguageChange(nextLanguage); setOutput([]); setPreview(null); setSaveMessage(''); }} />
      <div className="editor-actions">
        <button className="button editor-run" type="button" disabled={editorReadOnly || running} onClick={runCode}><span aria-hidden="true">▶</span> {running ? 'Running…' : runButtonLabel}</button>
        <button className="editor-secondary" type="button" disabled={editorReadOnly} onClick={clearCode}>Clear</button>
        <button className="editor-secondary" type="button" onClick={saveCode}>Save</button>
      </div>
    </div>
    <div className="monaco-frame">
      <Editor height="430px" language={monacoLanguageFor(language)} theme="vs-dark" value={value} onChange={code => { onChange(code ?? ''); setSaveMessage(''); }} loading={<div className="editor-loading">Loading code editor…</div>} options={{ readOnly: editorReadOnly, minimap: { enabled: false }, fontSize: 14, lineNumbers: 'on', automaticLayout: true, scrollBeyondLastLine: false, tabSize: 2, wordWrap: 'on', padding: { top: 17 }, scrollbar: { verticalScrollbarSize: 9, horizontalScrollbarSize: 9 } }} />
    </div>
    <div className="output-panel"><div className="output-heading"><h2>Output</h2><span>{sharedOutput?.status || (preview ? `${preview.language.toUpperCase()} preview` : supportedLanguage ? 'Browser JavaScript' : 'Console')}</span></div>{preview ? <iframe className="code-preview" title={`${preview.language.toUpperCase()} result preview`} sandbox="" srcDoc={preview.language === 'html' ? preview.code : `<!doctype html><html><head><style>${preview.code}</style></head><body><main class="sample-preview"><h1>SkillSwap preview</h1><p>Your CSS is applied to this sample content.</p><button>Example button</button></main></body></html>`} /> : <pre aria-live="polite">{sharedOutput ? sharedOutput.text : output.length ? output.join('\n') : 'Run your code to see output here.'}</pre>}</div>
    <div className="editor-footnote"><span>Code stays in this browser when you choose Save.</span><span role="status">{saveMessage}</span></div>
    <iframe ref={frameRef} className="execution-frame" title="Isolated JavaScript execution" sandbox="allow-scripts" />
  </section>;
}
