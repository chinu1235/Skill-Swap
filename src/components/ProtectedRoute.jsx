import { Link, Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function ProtectedRoute({ children, roles }) {
  const { user, loading, sessionError } = useAuth();
  const location = useLocation();

  if (loading) {
    return <section className="page-section"><div className="container"><p role="status">Checking your session...</p></div></section>;
  }
  if (!user && sessionError) {
    return <section className="page-section"><div className="container"><div className="form-card"><h1>Could not verify your session</h1><p>{sessionError}</p><Link className="button" to="/login">Go to Login</Link></div></div></section>;
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/dashboard" replace />;
  return children;
}
