// A single owner for character state; speech and request lifecycles may overlap.
export function resolveAnimation({hidden, speaking, listening, querying, feedback}) {
  if (hidden) return 'paused';
  if (speaking) return 'speaking';
  if (listening) return 'listening';
  if (querying) return 'thinking';
  return feedback || 'idle';
}

export function createAnimationController(render) {
  const state = {};
  let timer, current;
  const update = () => {
    const next = resolveAnimation(state);
    if (current !== next) { current = next; render(next); }
  };
  update();
  return {
    set(patch) { Object.assign(state, patch); update(); },
    flash(feedback, duration = 1600) {
      clearTimeout(timer);
      state.feedback = feedback;
      update();
      timer = setTimeout(() => { state.feedback = null; update(); }, duration);
    },
  };
}
