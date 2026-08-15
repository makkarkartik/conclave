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
:root {
  --font-display: "Sora", ui-sans-serif, system-ui, sans-serif;
  --font-body: "Manrope", ui-sans-serif, system-ui, sans-serif;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #eef1f6;
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
}
/* The document sits on a tinted ground like a sheet of paper on a desk. Its
   width tracks the prose measure plus a modest gutter for tables, so the page
   does not look like a column stranded on a too-wide sheet. */
#solution-print {
  display: block;
  max-width: 46rem;
  margin: 0 auto;
  min-height: 100vh;
  box-shadow: 0 1px 3px rgba(20, 22, 28, 0.08), 0 12px 32px rgba(20, 22, 28, 0.06);
}
${collectDocumentCss()}
@media print {
  @page { margin: 0; }
  body { background: #fff; }
  #solution-print { max-width: none; box-shadow: none; min-height: 0; }
}
@media (max-width: 40rem) {
  #solution-print { padding: 7vw 6vw; }
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
