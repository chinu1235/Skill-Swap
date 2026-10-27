
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { apiRequest } from '../services/api.js';
import { useAuth } from '../context/AuthContext.jsx';
import { teachers as demoTeachers } from '../data/teachers.js';

export default function TeacherProfile() {
  const { teacherId } = useParams();
  const { user } = useAuth();
  const [teacher, setTeacher] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setTeacher(null);
    setLoading(true);
    setError('');

    const demoTeacher = demoTeachers.find(
      (item) => item.id === teacherId
    );

    if (demoTeacher) {
      setTeacher({
        id: demoTeacher.id,
        name: demoTeacher.name,
        bio: demoTeacher.about,
        experience: demoTeacher.experience,
        teachingStyle: demoTeacher.description,
        rating: demoTeacher.rating,
        totalSessions: demoTeacher.sessions,
        skills: demoTeacher.skills.map((name, index) => ({
          id: `${demoTeacher.id}-skill-${index}`,
          skillName: name,
        })),
        reviews: demoTeacher.reviews || [],
        isDemo: true,
      });

      setLoading(false);
      return () => {
        active = false;
        controller.abort();
      };
    }

    apiRequest(
      '/api/teachers/' + encodeURIComponent(teacherId),
      { signal: controller.signal }
    )
      .then((result) => {
        if (active) setTeacher(result.teacher);
      })
      .catch((requestError) => {
        if (active && requestError.name !== 'AbortError') {
          setError(requestError.message);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [teacherId]);

  if (loading) {
    return (
      <section className="page-section">
        <div className="container">
          <p role="status">Loading teacher profile...</p>
        </div>
      </section>
    );
  }

  if (error || !teacher) {
    return (
      <section className="page-section">
        <div className="container">
          <div className="empty-state">
            <h1>Teacher profile unavailable</h1>
            <p>{error || 'This teacher profile could not be found.'}</p>
            <Link className="button button-outline" to="/explore">
              Back to Explore
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const skills = teacher.skills || [];
  const firstSkill = skills[0]?.skillName || 'SkillSwap';
  const initials = (teacher.name || 'SS')
    .split(/\s+/)
    .map((part) => part[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const rating = Number(teacher.rating || 0);
  const sessions = Number(teacher.totalSessions ?? teacher.sessions ?? 0);
  const reviews = teacher.reviews || [];

  return (
    <section className="page-section profile-page">
      <div className="container profile-container">
        <Link to="/explore" className="back-link">
          ← Back to Explore
        </Link>

        <div className="profile-card">
          <div className="profile-top">
            <div
              className="avatar avatar-large avatar-sage"
              aria-hidden="true"
            >
              {initials}
            </div>

            <div className="profile-title">
              <span className="teacher-skill">{firstSkill} Teacher</span>
              <h1>{teacher.name}</h1>

              <div className="profile-meta">
                <span className="rating">
                  <span aria-label={`${rating.toFixed(1)} out of 5 stars`}>
                    ★★★★★
                  </span>{' '}
                  {rating.toFixed(1)}
                </span>
                <span>{sessions} Sessions</span>
                <span>{skills.length} Skills</span>
              </div>
            </div>

            {user?.role === 'teacher' ? (
              <Link className="button profile-book" to="/dashboard">
                Teacher Dashboard
              </Link>
            ) : (
              <Link
                className="button profile-book"
                to={`/booking/${teacher.id}`}
              >
                Book a Session
              </Link>
            )}
          </div>

          <div className="profile-details">
            <section>
              <h2>About</h2>
              <p>
                {teacher.bio || 'This teacher has not added a bio yet.'}
              </p>

              <h2>Teaching Skills</h2>
              <div className="tag-list">
                {skills.length ? (
                  skills.map((item) => (
                    <span key={item.id || item.skillName}>
                      {item.skillName}
                    </span>
                  ))
                ) : (
                  <span>No skills listed yet</span>
                )}
              </div>

              <h2>Experience</h2>
              <p>
                {teacher.experience ||
                  'Experience details have not been added yet.'}
              </p>

              <h2>Teaching Style</h2>
              <p>
                {teacher.teachingStyle ||
                  'Teaching style details have not been added yet.'}
              </p>
            </section>

            <aside className="reviews-panel">
              <h2>Ratings &amp; Reviews</h2>

              <div className="profile-rating-summary">
                <strong>{rating.toFixed(1)}</strong>
                <span aria-hidden="true">★★★★★</span>
                <p>{sessions} sessions listed</p>
              </div>

              {reviews.length > 0 ? (
                <ul className="profile-review-list" style={{ listStyle: 'none', padding: 0, margin: '14px 0 0', display: 'grid', gap: '12px' }}>
                  {reviews.map((review, index) => (
                    <li key={`${teacher.id}-review-${index}`} style={{ borderTop: '1px solid #e5e4db', paddingTop: '10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <strong style={{ fontSize: '12px' }}>{review.learnerName || 'Learner'}</strong>
                        <span style={{ color: '#d5a44f', fontSize: '12px', letterSpacing: '1px' }}>
                          {'★'.repeat(review.rating || 5)}{'☆'.repeat(Math.max(0, 5 - (review.rating || 5)))}
                        </span>
                      </div>
                      <p style={{ margin: '4px 0 0', fontSize: '11px', color: '#657065', lineHeight: 1.6 }}>
                        {typeof review === 'string'
                          ? review
                          : review.comment || review.text || 'Review'}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No reviews yet.</p>
              )}
            </aside>
          </div>
        </div>
      </div>
    </section>
  );
}
