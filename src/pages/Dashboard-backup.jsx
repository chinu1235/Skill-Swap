import { skills as demoSkills } from '../data/teachers.js';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiRequest } from '../services/api.js';
import { useAuth } from '../context/AuthContext.jsx';

function BookingDetails({ booking }) {
  return <div className="dashboard-booking-details">
    <strong>{booking.skill?.skillName || 'Skill not available'}</strong>
    <span>{booking.bookingDate} at {booking.bookingTime}</span>
    <span>{booking.durationMinutes} minutes · {booking.sessionType}</span>
    {booking.notes && <p>{booking.notes}</p>}
    <span className="booking-status">Status: {booking.status}</span>
  </div>;
}

export default function Dashboard() {
  const { user } = useAuth();
  const isTeacher = user.role === 'teacher';
  const [bookings, setBookings] = useState([]);
  const [teacherProfile, setTeacherProfile] = useState(null);
  const [skills, setSkills] = useState([]);
  const [selectedSkill, setSelectedSkill] = useState('');
  const [profileForm, setProfileForm] = useState({ bio: '', experience: '', teachingStyle: '' });
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [workingBooking, setWorkingBooking] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [profileMessage, setProfileMessage] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');

    if (!isTeacher) {
      apiRequest('/api/bookings/my', { auth: true })
        .then((result) => { if (active) setBookings(result.bookings || []); })
        .catch((requestError) => { if (active) setError(requestError.message); })
        .finally(() => { if (active) setLoading(false); });
      return () => { active = false; };
    }

    Promise.allSettled([
      apiRequest('/api/bookings/received', { auth: true }),
      apiRequest('/api/teachers'),
      apiRequest('/api/skills'),
    ]).then((results) => {
      if (!active) return;
      const [bookingsResult, teachersResult, skillsResult] = results;

      if (bookingsResult.status === 'fulfilled') setBookings(bookingsResult.value.bookings || []);
      else if (bookingsResult.reason.status !== 404) setError(bookingsResult.reason.message);

      if (teachersResult.status === 'fulfilled') {
        const ownProfile = (teachersResult.value.teachers || []).find((item) => String(item.userId) === String(user.id));
        setTeacherProfile(ownProfile || null);
        setProfileForm({
          bio: ownProfile?.bio || '',
          experience: ownProfile?.experience || '',
          teachingStyle: ownProfile?.teachingStyle || '',
        });
      } else setError(teachersResult.reason.message);

      if (skillsResult.status === 'fulfilled') {
  const apiSkills = skillsResult.value.skills || [];

  const fallbackSkills = demoSkills.map((skill, index) => ({
    id: `demo-skill-${index + 1}`,
    skillName: skill.name,
  }));

  setSkills(apiSkills.length ? apiSkills : fallbackSkills);
} else {
  setSkills(
    demoSkills.map((skill, index) => ({
      id: `demo-skill-${index + 1}`,
      skillName: skill.name,
    }))
  );
}
    }).finally(() => { if (active) setLoading(false); });

    return () => { active = false; };
  }, [isTeacher, user.id, reload]);

  const saveProfile = async (event) => {
    event.preventDefault();
    setSavingProfile(true);
    setProfileMessage('');
    try {
      const result = await apiRequest('/api/teachers/profile', {
        method: teacherProfile ? 'PUT' : 'POST',
        auth: true,
        body: profileForm,
      });
      setTeacherProfile((current) => ({ ...result.teacher, skills: current?.skills || [] }));
      setProfileMessage(teacherProfile ? 'Profile updated.' : 'Profile created.');
      setNotice('');
      setReload((value) => value + 1);
    } catch (requestError) {
      setProfileMessage(requestError.message);
    } finally {
      setSavingProfile(false);
    }
  };

  const addSkill = async (event) => {
    event.preventDefault();
    if (!selectedSkill) return;
    const skillId = selectedSkill;
    if (teacherProfile?.skills?.some((item) => String(item.id) === String(skillId))) return;
    try {
      await apiRequest('/api/teachers/profile/skills', {
        method: 'POST',
        auth: true,
        body: { skillId },
      });
      const skill = skills.find((item) => String(item.id) === String(skillId));
      if (skill) setTeacherProfile((current) => ({ ...current, skills: [...(current?.skills || []), skill] }));
      setSelectedSkill('');
      setNotice('Skill added to your teacher profile.');
    } catch (requestError) {
      setNotice(requestError.message);
    }
  };

  const removeSkill = async (skillId) => {
    try {
      await apiRequest('/api/teachers/profile/skills/' + skillId, { method: 'DELETE', auth: true });
      setTeacherProfile((current) => ({
        ...current,
        skills: (current?.skills || []).filter((item) => String(item.id) !== String(skillId)),
      }));
      setNotice('Skill removed from your teacher profile.');
    } catch (requestError) {
      setNotice(requestError.message);
    }
  };

  const changeBooking = async (booking, status) => {
    setWorkingBooking(booking.id);
    setNotice('');
    try {
      if (status === 'cancelled') {
        await apiRequest('/api/bookings/' + booking.id, { method: 'DELETE', auth: true });
      } else {
        await apiRequest('/api/bookings/' + booking.id + '/status', {
          method: 'PUT',
          auth: true,
          body: { status },
        });
      }
      setNotice(status === 'cancelled' ? 'Booking cancelled.' : 'Booking status updated.');
      setReload((value) => value + 1);
    } catch (requestError) {
      setNotice(requestError.message);
    } finally {
      setWorkingBooking(null);
    }
  };

  const availableSkills = skills.filter((skill) => !(teacherProfile?.skills || []).some((item) => String(item.id) === String(skill.id)));

  return <section className="page-section dashboard-page"><div className="container">
    <div className="page-heading"><span className="eyebrow">Your SkillSwap space</span><h1>{isTeacher ? 'Teacher Dashboard' : 'My Bookings'}</h1><p>Welcome, {user.fullName}.</p></div>
    {error && <p className="form-message" role="alert">{error}</p>}
    {notice && <p className="form-message" role="status">{notice}</p>}

    {isTeacher && <div className="dashboard-section form-card">
      <h2>Teacher Profile</h2>
      <p>{teacherProfile ? 'Keep your profile details up to date.' : 'Create your profile so learners can find you.'}</p>
      <form className="dashboard-profile-form" onSubmit={saveProfile}>
        <label>About<textarea rows="4" maxLength="60000" value={profileForm.bio} onChange={(event) => setProfileForm((value) => ({ ...value, bio: event.target.value }))} /></label>
        <label>Experience<input maxLength="100" value={profileForm.experience} onChange={(event) => setProfileForm((value) => ({ ...value, experience: event.target.value }))} /></label>
        <label>Teaching Style<input maxLength="255" value={profileForm.teachingStyle} onChange={(event) => setProfileForm((value) => ({ ...value, teachingStyle: event.target.value }))} /></label>
        <button className="button" type="submit" disabled={savingProfile || loading}>{savingProfile ? 'Saving...' : teacherProfile ? 'Update Profile' : 'Create Profile'}</button>
        {profileMessage && <p className="form-message" role="status">{profileMessage}</p>}
      </form>
      {teacherProfile && <div className="dashboard-skills"><h3>Teaching Skills</h3>
        {(teacherProfile.skills || []).length ? <div className="tag-list">{teacherProfile.skills.map((skill) => <span key={skill.id}>{skill.skillName}<button type="button" aria-label={'Remove ' + skill.skillName} onClick={() => removeSkill(skill.id)}>×</button></span>)}</div> : <p>No skills added yet.</p>}
        <form className="dashboard-skill-form" onSubmit={addSkill}>
          <label htmlFor="teacher-skill-select">Add a skill</label>
          <select id="teacher-skill-select" value={selectedSkill} onChange={(event) => setSelectedSkill(event.target.value)}>
            <option value="">Choose a skill</option>{availableSkills.map((skill) => <option key={skill.id} value={skill.id}>{skill.skillName}</option>)}
          </select>
          <button className="button button-outline" type="submit" disabled={!selectedSkill}>Add Skill</button>
        </form>
      </div>}
    </div>}

    <div className="dashboard-section">
      <h2>{isTeacher ? 'Received Bookings' : 'My Learning Sessions'}</h2>
      {loading ? <p role="status">Loading bookings...</p> : bookings.length ? <div className="dashboard-bookings">
        {bookings.map((booking) => <article className="form-card dashboard-booking" key={booking.id}>
          <div className="dashboard-booking-heading"><h3>{isTeacher ? booking.learner?.name || 'Learner unavailable' : booking.teacher?.name || 'Teacher unavailable'}</h3><span className="booking-status">{booking.status}</span></div>
          <BookingDetails booking={booking} />
          <div className="dashboard-booking-actions">
            {!isTeacher && ['pending', 'confirmed'].includes(booking.status) && <button className="button button-outline" type="button" disabled={workingBooking === booking.id} onClick={() => changeBooking(booking, 'cancelled')}>{workingBooking === booking.id ? 'Updating...' : 'Cancel Booking'}</button>}
            {isTeacher && booking.status === 'pending' && <>
              <button className="button" type="button" disabled={workingBooking === booking.id} onClick={() => changeBooking(booking, 'confirmed')}>Confirm</button>
              <button className="button button-outline" type="button" disabled={workingBooking === booking.id} onClick={() => changeBooking(booking, 'cancelled')}>Cancel</button>
            </>}
            {isTeacher && booking.status === 'confirmed' && <>
              <button className="button" type="button" disabled={workingBooking === booking.id} onClick={() => changeBooking(booking, 'completed')}>Mark Completed</button>
              <button className="button button-outline" type="button" disabled={workingBooking === booking.id} onClick={() => changeBooking(booking, 'cancelled')}>Cancel</button>
            </>}
          </div>
        </article>)}
      </div> : <div className="empty-state"><h3>No bookings yet</h3><p>{isTeacher ? 'New learner requests will appear here.' : 'Explore teachers to request a learning session.'}</p>{!isTeacher && <Link className="button button-outline" to="/explore">Explore Teachers</Link>}</div>}
    </div>
  </div></section>;
}
