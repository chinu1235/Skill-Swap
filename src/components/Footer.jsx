import { Link } from 'react-router-dom';
import { Brand } from './Navbar.jsx';
export default function Footer() { return <footer className="site-footer"><div className="container footer-inner"><div><Brand /><p>Good things grow when we share what we know.</p></div><div className="footer-links"><Link to="/explore">Explore</Link><Link to="/about">About</Link><Link to="/contact">Contact</Link></div><small>© {new Date().getFullYear()} SkillSwap · A student project</small></div></footer>; }
