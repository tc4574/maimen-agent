export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Intentionally small Markdown subset. Raw HTML and active URLs are never executed.
function inline(text) {
  const code=[];
  let value=escapeHtml(text).replace(/`([^`]+)`/g,(_,v)=>{code.push(`<code>${v}</code>`);return `\u0000${code.length-1}\u0000`;});
  value=value.replace(/\[([^\]]+)\]\(([^)]+)\)/g,(_,label,url)=>`${label}（${url}）`)
    .replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')
    .replace(/__([^_\n]+)__/g,'<strong>$1</strong>')
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g,'<em>$1</em>');
  return value.replace(/\u0000(\d+)\u0000/g,(_,i)=>code[Number(i)]||'');
}
export function formatMessage(text) {
  const blocks=String(text ?? '').split(/```[^\n]*\n([\s\S]*?)```/g);
  return blocks.map((block,index)=>index%2?`<pre><code>${escapeHtml(block)}</code></pre>`:
    block.split('\n').map(line=>{
      if(/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line))return '<hr>';
      const heading=line.match(/^#{1,6}\s+(.+)/);if(heading)return `<h4>${inline(heading[1])}</h4>`;
      const bullet=line.match(/^\s*[-*+]\s+(.+)/);if(bullet)return `<div class="message-bullet"><span aria-hidden="true">•</span><span>${inline(bullet[1])}</span></div>`;
      return line.trim()?`<div>${inline(line)}</div>`:'<div class="paragraph-gap"></div>';
    }).join('')).join('');
}
export function speechText(text) {
  return String(text ?? '').replace(/```[\s\S]*?```/g,'代码内容请查看屏幕。')
    .replace(/^#{1,6}\s+/gm,'').replace(/^\s*[-*+]\s+/gm,'')
    .replace(/\*\*([^*]+)\*\*/g,'$1').replace(/__([^_]+)__/g,'$1')
    .replace(/\*([^*\n]+)\*/g,'$1').replace(/`([^`]+)`/g,'$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g,'$1');
}
