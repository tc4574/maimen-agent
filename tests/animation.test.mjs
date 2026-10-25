import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveAnimation, createAnimationController } from '../web/animation.mjs';

test('speech, listening and active requests have explicit priority', () => {
  assert.equal(resolveAnimation({speaking:true,querying:true}), 'speaking');
  assert.equal(resolveAnimation({listening:true,querying:true}), 'listening');
  assert.equal(resolveAnimation({querying:true,feedback:'success'}), 'thinking');
  assert.equal(resolveAnimation({hidden:true,speaking:true}), 'paused');
});
test('speech ending resumes a pending query, cancellation returns to idle', () => {
  const modes=[];const animation=createAnimationController(mode=>modes.push(mode));
  animation.set({querying:true});animation.set({speaking:true});
  animation.set({speaking:false});animation.set({querying:false});
  assert.deepEqual(modes,['idle','thinking','speaking','thinking','idle']);
});
test('temporary feedback expires without disturbing an active request', async () => {
  const modes=[];const animation=createAnimationController(mode=>modes.push(mode));
  animation.flash('success',5);animation.set({querying:true});
  await new Promise(resolve=>setTimeout(resolve,20));
  assert.deepEqual(modes,['idle','success','thinking']);
  animation.set({querying:false});assert.equal(modes.at(-1),'idle');
});
