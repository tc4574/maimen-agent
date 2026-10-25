export function conversationStore(storage, makeId = () => crypto.randomUUID()) {
  const read = (key, fallback) => { try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const list = () => read('mcbot.conversations', []);
  const load = id => read(`mcbot.thread.${id}`, null);
  function save(thread) {
    // Write the content first. A quota failure must not replace an existing thread with empty data.
    storage.setItem(`mcbot.thread.${thread.id}`, JSON.stringify(thread));
    const entries = list().filter(t => t.id !== thread.id);
    entries.unshift({id:thread.id, title:thread.title, updated:Date.now()});
    storage.setItem('mcbot.conversations', JSON.stringify(entries));
    storage.setItem('mcbot.activeThread', JSON.stringify(thread.id));
  }
  function create(messages=[]) {
    const thread={id:makeId(),title:messages.find(m=>m.role==='user')?.text.slice(0,24)||'新对话',messages,
      session:null,cards:[],run:null,selected:null,locks:[],skippedCardIds:[]};
    save(thread);return thread;
  }
  function current() {
    return load(read('mcbot.activeThread', '')) || create(read('mcbot.messages', []));
  }
  return {list,load,save,create,current};
}
