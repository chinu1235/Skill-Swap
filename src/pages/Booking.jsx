import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiRequest } from '../services/api.js';

function todayString() {
  const today = new Date();
  return [today.getFullYear(), String(today.getMonth() + 1).padStart(2, '0'), String(today.getDate()).padStart(2, '0')].join('-');
}

export default function Booking() {
  const { teacherId } = useParams();
  const [teacher, setTeacher] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(null);
  const [form, setForm] = useState({
    skillId: '',
    bookingDate: '',
    bookingTime: '',
    durationMinutes: '60',
    sessionType: 'Online',
    notes: '',
  });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    apiRequest('/api/teachers/' + encodeURIComponent(teacherId), { signal: controller.signal })
      .then((result) => {
        if (!active) return;
        const profile = result.teacher;
        setTeacher(profile);
        setForm((current) => ({ ...current, skillId: profile.skills?.[0]?.id ? String(profile.skills[0].id) : '' }));
      })
      .catch((requestError) => {
        if (active && requestError.name !== 'AbortError') setError(requestError.message);
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [teacherId]);

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setError('');
  };

  const submit = async (event) => {
    event.preventDefault();
    setError('');
    setSuccess(null);
    if (!form.bookingDate || !form.bookingTime) {
      setError('Choose a date and time for your session.');
      return;
    }
    if ((teacher?.skills || []).length && !form.skillId) {
      setError('Choose a skill this teacher offers.');
      return;
    }

    setBusy(true);
    try {
      const payload = {
        teacherId: teacherId,
        skillId: form.skillId || null,
        bookingDate: form.bookingDate,
        bookingTime: form.bookingTime,
        durationMinutes: Number(form.durationMinutes),
        sessionType: form.sessionType,
        notes: form.notes.trim() || null,
      };
      const result = await apiRequest('/api/bookings', { method: 'POST', auth: true, body: payload });
      setSuccess(result.booking);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <section className="page-section"><div className="container"><p role="status">Loading teacher profile...</p></div></section>;
  if (error && !teacher) return <section className="page-section"><div className="container"><div className="empty-state"><h1>Booking unavailable</h1><p>{error}</p><Link className="button button-outline" to="/explore">Back to Explore</Link></div></div></section>;
  if (!teacher) return null;

  if (success) return <section className="page-section"><div className="container"><div className="form-card booking-card">
    <div className="booking-icon" aria-hidden="true">✓</div><span className="eyebrow">Request sent</span><h1>Booking created</h1>
    <p>Your session request with {teacher.name} is pending confirmation.</p>
    <p>{success.bookingDate} at {success.bookingTime} · {success.durationMinutes} minutes</p>
    <Link className="button" to="/dashboard">View My Bookings</Link>
  </div></div></section>;

  return <section className="page-section"><div className="container">
    <div className="form-card booking-card">
      <div className="booking-icon" aria-hidden="true">✳</div><span className="eyebrow">A little more time</span><h1>Book a session</h1>
      <p>Choose a time to learn with {teacher.name}.</p>
      <form className="booking-form" onSubmit={submit}>
        {(teacher.skills || []).length > 0 && <label>Skill
          <select name="skillId" value={form.skillId} onChange={update} required>
            <option value="">Choose a skill</option>{teacher.skills.map((item) => <option key={item.id} value={item.id}>{item.skillName}</option>)}
          </select>
        </label>}
        <label>Date<input name="bookingDate" type="date" min={todayString()} value={form.bookingDate} onChange={update} required /></label>
        <label>Time<input name="bookingTime" type="time" value={form.bookingTime} onChange={update} required /></label>
        <label>Duration<select name="durationMinutes" value={form.durationMinutes} onChange={update}>
          {[30, 45, 60, 90, 120].map((minutes) => <option key={minutes} value={minutes}>{minutes} minutes</option>)}
        </select></label>
        <label>Session Type<select name="sessionType" value={form.sessionType} onChange={update}><option>Online</option><option>Offline</option></select></label>
        <label>Notes<textarea name="notes" rows="4" maxLength="60000" value={form.notes} onChange={update} placeholder="What would you like to learn?" /></label>
        <button className="button button-full" type="submit" disabled={busy}>{busy ? 'Creating booking...' : 'Request Session'}</button>
        {error && <p className="form-message" role="alert">{error}</p>}
      </form>
      <Link className="text-link" to={'/teachers/' + teacher.id}>Back to {teacher.name}'s profile</Link>
    </div>
  </div></section>;
}
