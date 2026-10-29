import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import { apiRequest } from '../services/api.js';

export default function Signup() {
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '', role: 'learner' });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState('register');
  const [registeredEmail, setRegisteredEmail] = useState('');
  const [code, setCode] = useState('');
  const [resendIn, setResendIn] = useState(0);
  const { register } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (resendIn <= 0) return undefined;
    const timer = window.setTimeout(() => setResendIn((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [resendIn]);

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setMessage('');
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!form.name.trim() || !form.email.trim() || !form.password || !form.confirm) return setMessage('Please complete all fields.');
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) return setMessage('Please enter a valid email address.');
    if (form.password !== form.confirm) return setMessage('Your passwords do not match.');
    if (form.password.length < 6) return setMessage('Please use a password with at least 6 characters.');

    setBusy(true);
    try {
      const email = form.email.trim().toLowerCase();
      const result = await register({ fullName: form.name.trim(), email, password: form.password, role: form.role });
      setRegisteredEmail(email);
      setResendIn(result.retryAfter || 60);
      setStep('verify');
      setMessage('');
    } catch (error) {
      if (error.payload?.pending) {
        setRegisteredEmail(form.email.trim().toLowerCase());
        setResendIn(error.payload.retryAfter || 0);
        setStep('verify');
      }
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (event) => {
    event.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      await apiRequest('/api/auth/verify', { method: 'POST', body: { email: registeredEmail, code } });
      navigate('/login', { replace: true, state: { notice: 'Your email is verified. Log in to continue.' } });
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setBusy(true);
    setMessage('');
    try {
      const result = await apiRequest('/api/auth/verify/resend', { method: 'POST', body: { email: registeredEmail } });
      setResendIn(result.retryAfter || 60);
      setMessage('A new code was sent.');
    } catch (error) {
      setResendIn(error.payload?.retryAfter || (error.status === 429 ? 60 : 0));
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  if (step === 'verify') return <section className="page-section auth-page"><form className="form-card auth-card signup-card" onSubmit={verify} noValidate>
    <span className="eyebrow">One quick check</span><h1>Verify your email</h1>
    <p>Enter the six digit code sent to <strong>{registeredEmail}</strong>. The code expires shortly.</p>
    <label>Email verification code<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength="6" value={code} onChange={(event) => { setCode(event.target.value.replace(/\D/g, '').slice(0, 6)); setMessage(''); }} required /></label>
    <button className="button button-full" type="submit" disabled={busy || code.length !== 6}>{busy ? 'Verifying...' : 'Verify email'}</button>
    <button className="button button-outline button-full" type="button" onClick={resend} disabled={busy || resendIn > 0}>{resendIn > 0 ? `Resend code in ${resendIn}s` : 'Resend code'}</button>
    {message && <p className="form-message" role="status">{message}</p>}
    <p className="auth-switch">Already joined us? <Link to="/login">Log in</Link></p>
  </form></section>;

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
    <button className="button button-full" type="submit" disabled={busy}>{busy ? 'Sending code...' : <>Create Account <span aria-hidden="true">→</span></>}</button>
    {message && <p className="form-message" role="alert">{message}</p>}
    <p className="auth-switch">Already joined us? <Link to="/login">Log in</Link></p>
  </form></section>;
}
