import { Routes, Route, Navigate } from 'react-router-dom';
import Navbar from './components/Navbar.jsx';
import Footer from './components/Footer.jsx';
import Home from './pages/Home.jsx';
import Explore from './pages/Explore.jsx';
import TeacherProfile from './pages/TeacherProfile.jsx';
import About from './pages/About.jsx';
import Contact from './pages/Contact.jsx';
import Login from './pages/Login.jsx';
import Signup from './pages/Signup.jsx';
import Booking from './pages/Booking.jsx';
import CodeEditorPage from './pages/CodeEditorPage.jsx';
import Dashboard from './pages/Dashboard.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';

export default function App() { return <><Navbar /><main><Routes><Route path="/" element={<Home />} /><Route path="/explore" element={<Explore />} /><Route path="/teachers/:teacherId" element={<TeacherProfile />} /><Route path="/booking/:teacherId" element={<ProtectedRoute roles={['learner']}><Booking /></ProtectedRoute>} /><Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} /><Route path="/about" element={<About />} /><Route path="/contact" element={<Contact />} /><Route path="/login" element={<Login />} /><Route path="/signup" element={<Signup />} /><Route path="/code-editor" element={<CodeEditorPage />} /><Route path="*" element={<Navigate to="/" replace />} /></Routes></main><Footer /></>; }
