/**
 * Export the solution document as a single self-contained HTML file.
 *
 * The markup is the same DOM the PDF prints, and the CSS is lifted from the
 * app's own stylesheet at export time, so the two exports cannot drift. HTML
 * carries no pagination, which is where every layout defect in the PDF path
 * came from; a print block travels inside the file so the recipient can still
 * produce a clean PDF from it.
 */

/** Pull the document's rules out of the running app's stylesheets. */
function collectDocumentCss(): string {
  const wanted = (selector: string) =>
    selector.includes('solution-md') || selector.includes('print-')

  const out: string[] = []
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList
    try {
      rules = sheet.cssRules
    } catch {
      continue // cross-origin (e.g. the font stylesheet) — nothing to read
    }
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSStyleRule && wanted(rule.selectorText)) {
        // `.print-only { display: none }` is the app's on-screen hiding rule.
        if (rule.selectorText.trim() === '.print-only' && rule.style.display === 'none') continue
        out.push(rule.cssText)
      } else if (rule instanceof CSSMediaRule && rule.conditionText.includes('print')) {
        for (const inner of Array.from(rule.cssRules)) {
          if (inner instanceof CSSStyleRule && wanted(inner.selectorText)) {
            out.push(inner.cssText)
          }
        }
      }
    }
  }
  return out.join('\n')
}

export function buildSolutionHtml(title: string): string | null {
  const node = document.getElementById('solution-print')
  if (!node) return null

  const escape = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600&family=Sora:wght@500;600;700&display=swap" rel="stylesheet">
<style>
/* The app's own tokens — the document is the conclusion section, not a
   reinterpretation of it. */
:root {
  --font-display: "Sora", ui-sans-serif, system-ui, sans-serif;
  --font-body: "Manrope", ui-sans-serif, system-ui, sans-serif;
  --color-ink: #12141a;
  --color-ink-2: #1a1d26;
  --color-panel: #1c1f2a;
  --color-line: rgba(255, 255, 255, 0.08);
  --color-sky: #6ba3ff;
  --color-speak: #f2f4f8;
  --color-think: #9aa3b5;
  --color-coral: #ff8b6b;
  --color-pass: #7a8499;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2.5rem 1.25rem 4rem;
  background: linear-gradient(180deg, #12141a 0%, #1a1d26 100%);
  background-attachment: fixed;
  color: var(--color-speak);
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
}
${collectDocumentCss()}
/* The card the solution lives in, carried over verbatim. */
#solution-print {
  display: block;
  max-width: 52rem;
  margin: 0 auto;
  border: 1px solid rgba(107, 163, 255, 0.35);
  border-radius: 1rem;
  background: linear-gradient(160deg, rgba(107, 163, 255, 0.14), rgba(28, 31, 42, 0.92) 45%);
}
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 8px; }
@media print {
  @page { margin: 0; }
  body { padding: 0; background: var(--color-ink); }
  #solution-print {
    max-width: none;
    border: none;
    border-radius: 0;
    background: var(--color-ink);
  }
}
@media (max-width: 40rem) {
  body { padding: 0; }
  #solution-print { border: none; border-radius: 0; padding: 7vw 6vw; }
}
</style>
</head>
<body>
${node.outerHTML}
</body>
</html>`
}

export function downloadSolutionHtml(filename: string, title: string): boolean {
  const html = buildSolutionHtml(title)
  if (!html) return false
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename}.html`
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Revoke on the next tick so the download has claimed the blob.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return true
}
