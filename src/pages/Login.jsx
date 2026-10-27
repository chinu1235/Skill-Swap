import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const { login, sessionError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const submit = async (event) => {
    event.preventDefault();
    setMessage('');
    if (!email.trim() || !password) {
      setMessage('Please enter your email and password.');
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setMessage('Please enter a valid email address.');
      return;
    }
    setBusy(true);
    try {
      await login({ email: email.trim(), password });
      navigate(location.state?.from || '/dashboard', { replace: true });
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  };

  return <section className="page-section auth-page"><form className="form-card auth-card" onSubmit={submit} noValidate>
    <span className="eyebrow">Welcome back</span><h1>Log in to SkillSwap</h1>
    <p>Sign in to connect with learners and teachers.</p>
    {location.state?.notice && <p className="success-message" role="status">{location.state.notice}</p>}
    {sessionError && <p className="form-message" role="status">{sessionError}</p>}
    <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => { setEmail(event.target.value); setMessage(''); }} required /></label>
    <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => { setPassword(event.target.value); setMessage(''); }} required /></label>
    <button className="button button-full" type="submit" disabled={busy}>{busy ? 'Signing in...' : <>Login <span aria-hidden="true">→</span></>}</button>
    {message && <p className="form-message" role="alert">{message}</p>}
    <p className="auth-switch">New to SkillSwap? <Link to="/signup">Create an account</Link></p>
  </form></section>;
}
