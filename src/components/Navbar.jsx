import { useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export function Brand() {
  return <Link to="/" className="brand" aria-label="SkillSwap home"><span className="brand-s">S</span><span className="brand-rest"><span>kill</span><span>wap</span></span></Link>;
}

export default function Navbar() {
  const [open, setOpen] = useState(false);
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();
  const close = () => setOpen(false);
  const signOut = () => { logout(); close(); navigate('/'); };
  return <header className="site-header"><nav className="nav-wrap container" aria-label="Main navigation">
    <Brand />
    <button className="menu-toggle" type="button" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} onClick={() => setOpen(!open)}><span></span><span></span><span></span></button>
    <div className={`nav-content ${open ? 'is-open' : ''}`}>
      <div className="nav-links"><NavLink to="/" end onClick={close}>Home</NavLink><NavLink to="/explore" onClick={close}>Explore</NavLink><a href="/#how-it-works" onClick={close}>How It Works</a><NavLink to="/about" onClick={close}>About</NavLink><NavLink to="/contact" onClick={close}>Contact</NavLink><NavLink className="code-nav-link" to="/code-editor" aria-label="Code Editor" title="Code Editor" onClick={close}><span aria-hidden="true">&lt;/&gt;</span><span className="code-nav-label">Code Editor</span></NavLink></div>
      <div className="nav-actions">{loading ? <span className="login-link" role="status">Checking session...</span> : user ? <>
        <Link className="login-link" to="/dashboard" onClick={close}>{user.fullName}</Link>
        <button className="login-link nav-logout" type="button" onClick={signOut}>Log out</button>
      </> : <><Link className="login-link" to="/login" onClick={close}>Login</Link><Link className="button button-small" to="/signup" onClick={close}>Sign Up</Link></>}</div>
    </div>
  </nav></header>;
}
