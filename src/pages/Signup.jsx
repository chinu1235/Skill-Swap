import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function Signup() {
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '', role: 'learner' });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const { register } = useAuth();
  const navigate = useNavigate();

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setMessage('');
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!form.name.trim() || !form.email.trim() || !form.password || !form.confirm) {
      setMessage('Please complete all fields.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      setMessage('Please enter a valid email address.');
      return;
    }
    if (form.password !== form.confirm) {
      setMessage('Your passwords do not match.');
      return;
    }
    if (form.password.length < 6) {
      setMessage('Please use a password with at least 6 characters.');
      return;
    }

    setBusy(true);
    try {
      await register({
        fullName: form.name.trim(),
        email: form.email.trim().toLowerCase(),
        password: form.password,
        role: form.role,
      });
      navigate('/login', { replace: true, state: { notice: 'Your account was created. Log in to continue.' } });
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  return <section className="page-section auth-page"><form className="form-card auth-card signup-card" onSubmit={submit} noValidate>
    <span className="eyebrow">Make room to grow</span><h1>Create your account</h1>
    <p>Join as a learner or teacher and start sharing skills.</p>
    <label>Full Name<input name="name" autoComplete="name" value={form.name} onChange={update} required /></label>
    <label>Email<input name="email" type="email" autoComplete="email" value={form.email} onChange={update} required /></label>
    <div className="two-fields">
      <label>Password<input name="password" type="password" autoComplete="new-password" value={form.password} onChange={update} required minLength="6" /></label>
      <label>Confirm Password<input name="confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={update} required /></label>
    </div>
    <fieldset className="role-fieldset"><legend>How would you like to start?</legend><div className="role-choice">
      {['learner', 'teacher'].map((role) => <label key={role} className={form.role === role ? 'selected' : ''}>
        <input type="radio" name="role" value={role} checked={form.role === role} onChange={update} />{role[0].toUpperCase() + role.slice(1)}
      </label>)}
    </div></fieldset>
    <button className="button button-full" type="submit" disabled={busy}>{busy ? 'Creating account...' : <>Create Account <span aria-hidden="true">→</span></>}</button>
    {message && <p className="form-message" role="alert">{message}</p>}
    <p className="auth-switch">Already joined us? <Link to="/login">Log in</Link></p>
  </form></section>;
}
