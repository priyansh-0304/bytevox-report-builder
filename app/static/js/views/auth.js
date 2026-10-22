import { h, clear } from '../dom.js';
import { api } from '../api.js';
import { errorBox } from '../ui.js';

/** Sign-in / create-account card. Calls onSignedIn(user) on success. */
export function authView(root, onSignedIn) {
  let mode = 'login';
  const render = () => {
    clear(root);
    const isLogin = mode === 'login';
    const errors = h('div', { 'aria-live': 'polite' });
    const email = h('input', { id: 'email', type: 'email', required: true, autocomplete: 'username', maxlength: '254' });
    const password = h('input', { id: 'password', type: 'password', required: true, minlength: '8', maxlength: '200',
      autocomplete: isLogin ? 'current-password' : 'new-password' });
    const submit = h('button', { class: 'btn primary', type: 'submit' }, isLogin ? 'Sign in' : 'Create account');

    const form = h('form', { class: 'stack', onsubmit: async (ev) => {
      ev.preventDefault();
      clear(errors);
      submit.disabled = true;
      try {
        const user = await api('POST', `/api/auth/${isLogin ? 'login' : 'register'}`,
          { email: email.value, password: password.value }, { quiet: true });
        onSignedIn(user);
      } catch (err) {
        errors.append(errorBox(err));
        submit.disabled = false;
      }
    } },
      h('label', { class: 'field', for: 'email' }, 'Email', email),
      h('label', { class: 'field', for: 'password' }, isLogin ? 'Password' : 'Password (at least 8 characters)', password),
      errors, submit);

    root.append(h('div', { class: 'card' },
      h('h1', null, isLogin ? 'Sign in' : 'Create your account'),
      h('p', { class: 'muted' }, 'Build reports from a CSV where every number shows its work.'),
      form,
      h('p', null, isLogin ? 'New here? ' : 'Already have an account? ',
        h('button', { class: 'btn link', type: 'button', onclick: () => { mode = isLogin ? 'register' : 'login'; render(); email.focus(); } },
          isLogin ? 'Create an account' : 'Sign in'))));
    email.focus();
  };
  render();
}
