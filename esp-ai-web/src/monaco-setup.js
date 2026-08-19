/**
 * Monaco Editor 初始化配置（CDN 加载方案 + 代码补全 + 多主题）
 *
 * 使用 @monaco-editor/loader 从 CDN 异步加载 Monaco Editor
 * 包含 Python 代码补全、ESP-AI 专用片段、三套主题
 */
import loader from '@monaco-editor/loader'

// 配置 CDN 路径
loader.config({
  paths: {
    vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs',
  },
})

let _monaco = null
let _initPromise = null

/** Python 关键字 */
const PYTHON_KEYWORDS = [
  'def', 'class', 'return', 'import', 'from', 'as', 'if', 'elif', 'else',
  'for', 'while', 'break', 'continue', 'pass', 'try', 'except', 'finally',
  'with', 'async', 'await', 'yield', 'lambda', 'global', 'nonlocal',
  'raise', 'assert', 'del', 'in', 'is', 'not', 'and', 'or', 'None',
  'True', 'False',
]

/** Python 内置函数 */
const PYTHON_BUILTINS = [
  'print', 'len', 'range', 'enumerate', 'zip', 'map', 'filter', 'sorted',
  'reversed', 'sum', 'min', 'max', 'abs', 'round', 'isinstance', 'type',
  'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
  'open', 'format', 'input', 'hasattr', 'getattr', 'setattr',
]

/** ESP-AI 框架专用代码片段 */
const ESPAI_SNIPPETS = [
  {
    label: '@tool()',
    detail: 'ESP-AI 工具装饰器',
    insertText: '@tool()\ndef ${1:name}(${2:args}) -> ${3:str}:\n    """${4:描述}\n\n    Args:\n        ${2:args}: 参数说明\n\n    Returns:\n        返回值说明\n    """\n    ${5:pass}',
    kind: 'Snippet',
  },
  {
    label: '@tool(cache=False)',
    detail: 'ESP-AI 工具（禁用缓存）',
    insertText: '@tool(cache=False)\ndef ${1:name}(${2:args}) -> ${3:str}:\n    """${4:描述}"""\n    ${5:pass}',
    kind: 'Snippet',
  },
  {
    label: 'config_field',
    detail: 'manifest 配置字段模板',
    insertText: '{\n  "key": "${1:api_key}",\n  "label": "${2:API Key}",\n  "type": "${3:text}",\n  "required": ${4:true}\n}',
    kind: 'Snippet',
  },
  {
    label: 'if __name__',
    detail: '主入口',
    insertText: 'if __name__ == "__main__":\n    ${1:pass}',
    kind: 'Snippet',
  },
]

/** 可用主题列表 */
export const THEMES = [
  { id: 'light', label: '浅色', icon: '☀' },
  { id: 'dark', label: '深色', icon: '☾' },
  { id: 'mint', label: '薄荷', icon: '◉' },
]

function registerPythonCompletion(monaco) {
  monaco.languages.registerCompletionItemProvider('python', {
    triggerCharacters: ['.', ' ', '(', '\n'],
    provideCompletionItems(model, position) {
      const word = model.getWordUntilPosition(position)
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      }

      const suggestions = []

      for (const kw of PYTHON_KEYWORDS) {
        suggestions.push({
          label: kw, kind: monaco.languages.CompletionItemKind.Keyword,
          insertText: kw, sortText: `1_${kw}`, range,
        })
      }

      for (const fn of PYTHON_BUILTINS) {
        suggestions.push({
          label: fn, kind: monaco.languages.CompletionItemKind.Function,
          insertText: fn, sortText: `2_${fn}`, detail: 'built-in function', range,
        })
      }

      for (const snip of ESPAI_SNIPPETS) {
        const kindMap = {
          Snippet: monaco.languages.CompletionItemKind.Snippet,
          Function: monaco.languages.CompletionItemKind.Function,
          Keyword: monaco.languages.CompletionItemKind.Keyword,
        }
        suggestions.push({
          label: snip.label,
          kind: kindMap[snip.kind] || monaco.languages.CompletionItemKind.Snippet,
          insertText: snip.insertText,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
          detail: snip.detail, sortText: `0_${snip.label}`, range,
        })
      }

      return { suggestions }
    },
  })
}

function registerPythonConfig(monaco) {
  monaco.languages.setLanguageConfiguration('python', {
    comments: { lineComment: '#', blockComment: ['"""', '"""'] },
    brackets: [['(', ')'], ['[', ']'], ['{', '}']],
    autoClosingPairs: [
      { open: '(', close: ')' },
      { open: '[', close: ']' },
      { open: '{', close: '}' },
      { open: '"', close: '"', notIn: ['string'] },
      { open: "'", close: "'", notIn: ['string', 'comment'] },
      { open: '"""', close: '"""' },
    ],
    surroundingPairs: [
      { open: '(', close: ')' }, { open: '[', close: ']' }, { open: '{', close: '}' },
      { open: '"', close: '"' }, { open: "'", close: "'" },
    ],
    onEnterRules: [
      {
        beforeText: /^\s*(def|class|for|if|elif|else|while|try|except|finally|with|async)\b.*:\s*$/,
        action: { indentAction: monaco.languages.IndentAction.Indent },
      },
    ],
  })
}

function defineThemes(monaco) {
  // 浅色主题（标准 VS Code 风格，干净的白色背景）
  monaco.editor.defineTheme('esp-ai-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6a737d', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'd73a49' },
      { token: 'string', foreground: '032f62' },
      { token: 'number', foreground: '005cc5' },
      { token: 'type', foreground: '6f42c1' },
      { token: 'function', foreground: '6f42c1' },
      { token: 'delimiter', foreground: '586069' },
    ],
    colors: {
      'editor.background': '#ffffff',
      'editor.foreground': '#24292e',
      'editor.lineHighlightBackground': '#f6f8fa',
      'editorLineNumber.foreground': '#959da5',
      'editorLineNumber.activeForeground': '#24292e',
      'editorCursor.foreground': '#0969da',
      'editor.selectionBackground': '#dbeafe',
      'editor.inactiveSelectionBackground': '#e0f2fe',
      'editorIndentGuide.background': '#e1e4e8',
      'editorIndentGuide.activeBackground': '#586069',
      'editorSuggestWidget.background': '#ffffff',
      'editorSuggestWidget.border': '#e1e4e8',
      'editorSuggestWidget.selectedBackground': '#f0faf6',
      'editorSuggestWidget.highlightForeground': '#0969da',
      'editorWidget.background': '#f6f8fa',
      'editorWidget.border': '#e1e4e8',
    },
  })

  // 深色主题（VS Code Dark+ 风格）
  monaco.editor.defineTheme('esp-ai-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6a9955', fontStyle: 'italic' },
      { token: 'keyword', foreground: '569cd6' },
      { token: 'string', foreground: 'ce9178' },
      { token: 'number', foreground: 'b5cea8' },
      { token: 'type', foreground: '4ec9b0' },
      { token: 'function', foreground: 'dcdcaa' },
      { token: 'delimiter', foreground: 'd4d4d4' },
    ],
    colors: {
      'editor.background': '#1e1e1e',
      'editor.foreground': '#d4d4d4',
      'editor.lineHighlightBackground': '#2a2a2a',
      'editorLineNumber.foreground': '#858585',
      'editorLineNumber.activeForeground': '#c6c6c6',
      'editorCursor.foreground': '#aeafad',
      'editor.selectionBackground': '#264f78',
      'editorIndentGuide.background': '#404040',
      'editorIndentGuide.activeBackground': '#707070',
      'editorSuggestWidget.background': '#252526',
      'editorSuggestWidget.border': '#454545',
      'editorSuggestWidget.selectedBackground': '#062f4a',
      'editorWidget.background': '#252526',
      'editorWidget.border': '#454545',
    },
  })

  // 薄荷绿主题（保留作为选项）
  monaco.editor.defineTheme('esp-ai-mint', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '999999', fontStyle: 'italic' },
      { token: 'keyword', foreground: '34d399' },
      { token: 'string', foreground: '059669' },
      { token: 'number', foreground: '6366f1' },
      { token: 'type', foreground: '8b5cf6' },
      { token: 'function', foreground: '3b82f6' },
    ],
    colors: {
      'editor.background': '#ffffff',
      'editor.lineHighlightBackground': '#f0faf6',
      'editorLineNumber.foreground': '#c5c8c6',
      'editorLineNumber.activeForeground': '#34d399',
      'editorCursor.foreground': '#34d399',
      'editor.selectionBackground': '#d1fae5',
      'editor.inactiveSelectionBackground': '#e6fffa',
      'editorIndentGuide.background': '#f0f0f0',
      'editorIndentGuide.activeBackground': '#34d399',
      'editorSuggestWidget.background': '#ffffff',
      'editorSuggestWidget.border': '#e5e7eb',
      'editorSuggestWidget.selectedBackground': '#f0faf6',
      'editorSuggestWidget.highlightForeground': '#34d399',
      'editorWidget.background': '#fafafa',
      'editorWidget.border': '#e5e7eb',
    },
  })
}

/** 主题 ID → Monaco 主题名映射 */
const THEME_MAP = { light: 'esp-ai-light', dark: 'esp-ai-dark', mint: 'esp-ai-mint' }

/** 切换主题 */
export function setEditorTheme(themeId) {
  if (!_monaco) return
  const name = THEME_MAP[themeId] || 'esp-ai-light'
  _monaco.editor.setTheme(name)
}

/**
 * 获取 Monaco 实例（单例，首次调用会从 CDN 加载）
 * @returns {Promise<typeof import('monaco-editor')>}
 */
export function getMonaco() {
  if (_monaco) return Promise.resolve(_monaco)
  if (_initPromise) return _initPromise
  _initPromise = loader.init().then((monaco) => {
    defineThemes(monaco)
    registerPythonCompletion(monaco)
    registerPythonConfig(monaco)
    _monaco = monaco
    return monaco
  })
  return _initPromise
}
