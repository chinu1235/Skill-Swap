import { skills as demoSkills } from '../data/teachers.js';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiRequest } from '../services/api.js';
import { useAuth } from '../context/AuthContext.jsx';

function BookingDetails({ booking }) {
  return (
    <div className="dashboard-booking-details">
      <strong>{booking.skill?.skillName || 'Skill not available'}</strong>
      <span>{booking.bookingDate} at {booking.bookingTime}</span>
      <span>{booking.durationMinutes} minutes · {booking.sessionType}</span>
      {booking.notes && <p>{booking.notes}</p>}
      <span className="booking-status">
        Status: {booking.status}
      </span>
    </div>
  );
}

function StatCard({ title, value, description }) {
  return (
    <article className="form-card dashboard-stat-card" style={{ padding: '20px', textAlign: 'left' }}>
      <p style={{ margin: '0 0 8px', fontSize: '12px', fontWeight: 600, color: 'var(--muted)' }}>{title}</p>
      <h3 style={{ margin: '0 0 6px', fontSize: '28px', color: 'var(--ink)' }}>{value}</h3>
      <small style={{ fontSize: '11px', color: 'var(--muted)' }}>{description}</small>
    </article>
  );
}

function getBookingDateTime(booking) {
  if (!booking?.bookingDate || !booking?.bookingTime) return null;

  const timeStr = String(booking.bookingTime).trim();
  const parts = timeStr.split(':');
  if (parts.length < 2) return null;

  const hours = parts[0].padStart(2, '0');
  const minutes = parts[1].padStart(2, '0');
  const seconds = (parts[2] || '00').padStart(2, '0');
  const time = `${hours}:${minutes}:${seconds}`;

  const parsed = new Date(`${booking.bookingDate}T${time}`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export default function Dashboard() {
  const { user } = useAuth();
  const isTeacher = user?.role === 'teacher';

  const [bookings, setBookings] = useState([]);
  const [teacherProfile, setTeacherProfile] = useState(null);
  const [skills, setSkills] = useState([]);
  const [selectedSkill, setSelectedSkill] = useState('');
  const [profileForm, setProfileForm] = useState({
    bio: '',
    experience: '',
    teachingStyle: '',
  });

  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [workingBooking, setWorkingBooking] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [profileMessage, setProfileMessage] = useState('');
  const [reload, setReload] = useState(0);

  const [teacherReviews, setTeacherReviews] = useState([]);
  const [reviewModalBooking, setReviewModalBooking] = useState(null);
  const [reviewForm, setReviewForm] = useState({ rating: 5, comment: '' });
  const [submittingReview, setSubmittingReview] = useState(false);
  const [reviewError, setReviewError] = useState('');

  useEffect(() => {
    let active = true;

    setLoading(true);
    setError('');

    if (!user) {
      setLoading(false);
      return () => {
        active = false;
      };
    }

    if (!isTeacher) {
      apiRequest('/api/bookings/my', { auth: true })
        .then((result) => {
          if (active) setBookings(result.bookings || []);
        })
        .catch((requestError) => {
          if (active) setError(requestError.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });

      return () => {
        active = false;
      };
    }

    Promise.allSettled([
      apiRequest('/api/bookings/received', { auth: true }),
      apiRequest('/api/teachers'),
      apiRequest('/api/skills'),
    ])
      .then((results) => {
        if (!active) return;

        const [bookingsResult, teachersResult, skillsResult] = results;

        if (bookingsResult.status === 'fulfilled') {
          setBookings(bookingsResult.value.bookings || []);
        } else if (bookingsResult.reason?.status !== 404) {
          setError(bookingsResult.reason?.message || 'Could not load bookings.');
        }

        if (teachersResult.status === 'fulfilled') {
          const ownProfile = (teachersResult.value.teachers || []).find(
            (item) => String(item.userId) === String(user.id)
          );

          setTeacherProfile(ownProfile || null);
          setProfileForm({
            bio: ownProfile?.bio || '',
            experience: ownProfile?.experience || '',
            teachingStyle: ownProfile?.teachingStyle || '',
          });

          if (ownProfile?.id) {
            apiRequest('/api/reviews?teacherId=' + encodeURIComponent(ownProfile.id))
              .then((res) => {
                if (active) setTeacherReviews(res.reviews || []);
              })
              .catch(() => {
                if (active) setTeacherReviews([]);
              });
          }
        } else {
          setError((current) =>
            current || teachersResult.reason?.message || 'Could not load your profile.'
          );
        }

        const fallbackSkills = demoSkills.map((skill, index) => ({
          id: `demo-skill-${index + 1}`,
          skillName: skill.name,
        }));

        if (skillsResult.status === 'fulfilled') {
          const apiSkills = skillsResult.value.skills || [];
          setSkills(apiSkills.length ? apiSkills : fallbackSkills);
        } else {
          setSkills(fallbackSkills);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [isTeacher, user?.id, reload]);

  const bookingStats = useMemo(() => {
    const now = new Date();

    const pending = bookings.filter(
      (booking) => booking.status === 'pending'
    );

    const confirmed = bookings.filter(
      (booking) => booking.status === 'confirmed'
    );

    const completed = bookings.filter(
      (booking) => booking.status === 'completed'
    );

    const upcoming = confirmed.filter((booking) => {
      const dateTime = getBookingDateTime(booking);
      return dateTime ? dateTime >= now : true;
    });

    return {
      total: bookings.length,
      pending: pending.length,
      completed: completed.length,
      upcoming,
      confirmed: confirmed.length,
      pendingBookings: pending,
      completedBookings: completed,
    };
  }, [bookings]);

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

      setTeacherProfile((current) => ({
        ...current,
        ...result.teacher,
        skills: current?.skills || [],
      }));

      setProfileMessage(
        teacherProfile ? 'Profile updated successfully.' : 'Profile created successfully.'
      );
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

    if (
      teacherProfile?.skills?.some(
        (item) => String(item.id) === String(skillId)
      )
    ) {
      return;
    }

    try {
      await apiRequest('/api/teachers/profile/skills', {
        method: 'POST',
        auth: true,
        body: { skillId },
      });

      const skill = skills.find(
        (item) => String(item.id) === String(skillId)
      );

      if (skill) {
        setTeacherProfile((current) => ({
          ...current,
          skills: [...(current?.skills || []), skill],
        }));
      }

      setSelectedSkill('');
      setNotice('Skill added to your teacher profile.');
    } catch (requestError) {
      setNotice(requestError.message);
    }
  };

  const removeSkill = async (skillId) => {
    try {
      await apiRequest(
        '/api/teachers/profile/skills/' + encodeURIComponent(skillId),
        { method: 'DELETE', auth: true }
      );

      setTeacherProfile((current) => ({
        ...current,
        skills: (current?.skills || []).filter(
          (item) => String(item.id) !== String(skillId)
        ),
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
        await apiRequest('/api/bookings/' + booking.id, {
          method: 'DELETE',
          auth: true,
        });
      } else {
        await apiRequest('/api/bookings/' + booking.id + '/status', {
          method: 'PUT',
          auth: true,
          body: { status },
        });
      }

      setNotice(
        status === 'cancelled'
          ? 'Booking cancelled.'
          : 'Booking status updated.'
      );

      setReload((value) => value + 1);
    } catch (requestError) {
      setNotice(requestError.message);
    } finally {
      setWorkingBooking(null);
    }
  };

  const openReviewModal = (booking) => {
    setReviewModalBooking(booking);
    setReviewForm({ rating: 5, comment: '' });
    setReviewError('');
  };

  const closeReviewModal = () => {
    setReviewModalBooking(null);
    setReviewForm({ rating: 5, comment: '' });
    setReviewError('');
  };

  const submitReview = async (e) => {
    e.preventDefault();
    if (!reviewModalBooking) return;
    if (!reviewForm.rating || reviewForm.rating < 1 || reviewForm.rating > 5) {
      setReviewError('Please select a star rating from 1 to 5.');
      return;
    }
    if (!reviewForm.comment.trim()) {
      setReviewError('Please enter written feedback for your review.');
      return;
    }

    setSubmittingReview(true);
    setReviewError('');
    try {
      await apiRequest('/api/reviews', {
        method: 'POST',
        auth: true,
        body: {
          bookingId: reviewModalBooking.id,
          rating: Number(reviewForm.rating),
          comment: reviewForm.comment.trim(),
        },
      });
      setNotice('Review submitted successfully! Thank you for your feedback.');
      closeReviewModal();
      setReload((v) => v + 1);
    } catch (err) {
      setReviewError(err.message || 'Could not submit review.');
    } finally {
      setSubmittingReview(false);
    }
  };

  const availableSkills = skills.filter(
    (skill) =>
      !(teacherProfile?.skills || []).some(
        (item) => String(item.id) === String(skill.id)
      )
  );

  const renderBookingList = (items, emptyTitle, emptyDescription) => {
    if (!items.length) {
      return (
        <div className="empty-state">
          <h3>{emptyTitle}</h3>
          <p>{emptyDescription}</p>
        </div>
      );
    }

    return (
      <div className="dashboard-bookings">
        {items.map((booking) => (
          <article className="form-card dashboard-booking" key={booking.id}>
            <div className="dashboard-booking-heading">
              <h3>
                {isTeacher
                  ? booking.learner?.name || 'Learner unavailable'
                  : booking.teacher?.name || 'Teacher unavailable'}
              </h3>
              <span className="booking-status">{booking.status}</span>
            </div>

            <BookingDetails booking={booking} />

            <div className="dashboard-booking-actions">
              {!isTeacher &&
                ['pending', 'confirmed'].includes(booking.status) && (
                  <button
                    className="button button-outline"
                    type="button"
                    disabled={workingBooking === booking.id}
                    onClick={() => changeBooking(booking, 'cancelled')}
                  >
                    {workingBooking === booking.id
                      ? 'Updating...'
                      : 'Cancel Booking'}
                  </button>
                )}

              {!isTeacher && booking.status === 'completed' && (
                booking.hasReview ? (
                  <span className="booking-status" style={{ background: '#eef3eb', color: '#3d6144' }}>
                    Reviewed ★
                  </span>
                ) : (
                  <button
                    className="button"
                    type="button"
                    onClick={() => openReviewModal(booking)}
                  >
                    Write a Review
                  </button>
                )
              )}

              {isTeacher && booking.status === 'pending' && (
                <>
                  <button
                    className="button"
                    type="button"
                    disabled={workingBooking === booking.id}
                    onClick={() => changeBooking(booking, 'confirmed')}
                  >
                    Confirm
                  </button>
                  <button
                    className="button button-outline"
                    type="button"
                    disabled={workingBooking === booking.id}
                    onClick={() => changeBooking(booking, 'cancelled')}
                  >
                    Cancel
                  </button>
                </>
              )}

              {isTeacher && booking.status === 'confirmed' && (
                <>
                  <button
                    className="button"
                    type="button"
                    disabled={workingBooking === booking.id}
                    onClick={() => changeBooking(booking, 'completed')}
                  >
                    Mark Completed
                  </button>
                  <button
                    className="button button-outline"
                    type="button"
                    disabled={workingBooking === booking.id}
                    onClick={() => changeBooking(booking, 'cancelled')}
                  >
                    Cancel
                  </button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>
    );
  };

  if (!user) {
    return (
      <section className="page-section">
        <div className="container">
          <div className="empty-state">
            <h2>Please log in to view your dashboard.</h2>
            <Link className="button" to="/login">Log In</Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="page-section dashboard-page">
      <div className="container">
        <div className="page-heading">
          <span className="eyebrow">Your SkillSwap space</span>
          <h1>{isTeacher ? 'Teacher Dashboard' : 'My Bookings'}</h1>
          <p>Welcome, {user.fullName}.</p>
        </div>

        {error && <p className="form-message" role="alert">{error}</p>}
        {notice && <p className="form-message" role="status">{notice}</p>}

        {isTeacher && (
          <>
            <div
              className="dashboard-section dashboard-stats"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                gap: '16px',
                marginTop: '0',
                marginBottom: '30px',
              }}
            >
              <StatCard
                title="Total Bookings"
                value={loading ? '—' : bookingStats.total}
                description="All bookings received"
              />
              <StatCard
                title="Pending Requests"
                value={loading ? '—' : bookingStats.pending}
                description="Waiting for your response"
              />
              <StatCard
                title="Upcoming Confirmed Sessions"
                value={loading ? '—' : bookingStats.upcoming.length}
                description="Confirmed sessions in the future"
              />
              <StatCard
                title="Completed Sessions"
                value={loading ? '—' : bookingStats.completed}
                description="Sessions marked completed"
              />
            </div>

            <div className="dashboard-section form-card">
              <h2>Teacher Profile</h2>
              <p>
                {teacherProfile
                  ? 'Keep your profile details up to date.'
                  : 'Create your profile so learners can find you.'}
              </p>

              <form className="dashboard-profile-form" onSubmit={saveProfile}>
                <label>
                  About
                  <textarea
                    rows="4"
                    maxLength="60000"
                    value={profileForm.bio}
                    onChange={(event) =>
                      setProfileForm((value) => ({
                        ...value,
                        bio: event.target.value,
                      }))
                    }
                  />
                </label>

                <label>
                  Experience
                  <input
                    maxLength="100"
                    value={profileForm.experience}
                    onChange={(event) =>
                      setProfileForm((value) => ({
                        ...value,
                        experience: event.target.value,
                      }))
                    }
                  />
                </label>

                <label>
                  Teaching Style
                  <input
                    maxLength="255"
                    value={profileForm.teachingStyle}
                    onChange={(event) =>
                      setProfileForm((value) => ({
                        ...value,
                        teachingStyle: event.target.value,
                      }))
                    }
                  />
                </label>

                <button
                  className="button"
                  type="submit"
                  disabled={savingProfile || loading}
                >
                  {savingProfile
                    ? 'Saving...'
                    : teacherProfile
                      ? 'Update Profile'
                      : 'Create Profile'}
                </button>

                {profileMessage && (
                  <p className="form-message" role="status">{profileMessage}</p>
                )}
              </form>

              {teacherProfile && (
                <div className="dashboard-skills">
                  <h3>Teaching Skills</h3>

                  {(teacherProfile.skills || []).length ? (
                    <div className="tag-list">
                      {teacherProfile.skills.map((skill) => (
                        <span key={skill.id}>
                          {skill.skillName}
                          <button
                            type="button"
                            aria-label={'Remove ' + skill.skillName}
                            onClick={() => removeSkill(skill.id)}
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p>No skills added yet.</p>
                  )}

                  <form className="dashboard-skill-form" onSubmit={addSkill}>
                    <label htmlFor="teacher-skill-select">Add a skill</label>
                    <select
                      id="teacher-skill-select"
                      value={selectedSkill}
                      onChange={(event) => setSelectedSkill(event.target.value)}
                    >
                      <option value="">Choose a skill</option>
                      {availableSkills.map((skill) => (
                        <option key={skill.id} value={skill.id}>
                          {skill.skillName}
                        </option>
                      ))}
                    </select>

                    <button
                      className="button button-outline"
                      type="submit"
                      disabled={!selectedSkill || loading}
                    >
                      Add Skill
                    </button>
                  </form>
                </div>
              )}
            </div>

            <div className="dashboard-section">
              <h2>Average Rating & Reviews</h2>
              <div className="form-card" style={{ padding: '24px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', marginBottom: '8px' }}>
                  <h3 style={{ margin: 0, fontSize: '28px', color: 'var(--ink)' }}>
                    ★ {teacherProfile?.rating !== undefined && teacherProfile?.rating !== null ? Number(teacherProfile.rating).toFixed(1) : '0.0'}
                  </h3>
                  <span style={{ fontSize: '13px', color: 'var(--muted)' }}>
                    / 5.0 ({teacherReviews.length} {teacherReviews.length === 1 ? 'review' : 'reviews'})
                  </span>
                </div>
                <p style={{ margin: '0 0 16px', fontSize: '12px', color: 'var(--muted)' }}>
                  {teacherReviews.length > 0
                    ? 'Learner ratings and written reviews from completed sessions.'
                    : 'Ratings and feedback from learners will appear here once submitted.'}
                </p>

                {teacherReviews.length > 0 ? (
                  <div style={{ display: 'grid', gap: '12px', borderTop: '1px solid #eeece3', paddingTop: '16px' }}>
                    {teacherReviews.map((rev) => (
                      <div key={rev.id} style={{ padding: '12px 14px', background: '#f8f7f1', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                          <strong style={{ fontSize: '12px' }}>{rev.learnerName}</strong>
                          <span style={{ color: '#d5a44f', fontSize: '13px', letterSpacing: '1px' }}>
                            {'★'.repeat(rev.rating)}{'☆'.repeat(Math.max(0, 5 - rev.rating))}
                          </span>
                        </div>
                        <p style={{ margin: 0, fontSize: '12px', color: 'var(--ink)', lineHeight: 1.5 }}>
                          {rev.comment}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ margin: 0 }}>No reviews yet.</p>
                )}
              </div>
            </div>

            <div className="dashboard-section">
              <h2>Incoming Pending Requests</h2>
              {loading ? (
                <p role="status">Loading booking requests...</p>
              ) : (
                renderBookingList(
                  bookingStats.pendingBookings,
                  'No pending requests',
                  'New learner requests will appear here.'
                )
              )}
            </div>

            <div className="dashboard-section">
              <h2>Upcoming Confirmed Sessions</h2>
              {loading ? (
                <p role="status">Loading upcoming sessions...</p>
              ) : (
                renderBookingList(
                  bookingStats.upcoming,
                  'No upcoming sessions',
                  'Confirmed future sessions will appear here.'
                )
              )}
            </div>

            <div className="dashboard-section">
              <h2>Completed Sessions</h2>
              {loading ? (
                <p role="status">Loading completed sessions...</p>
              ) : (
                renderBookingList(
                  bookingStats.completedBookings,
                  'No completed sessions',
                  'Sessions you mark as completed will appear here.'
                )
              )}
            </div>

            <div className="dashboard-section">
              <h2>All Received Bookings</h2>
              {loading ? (
                <p role="status">Loading bookings...</p>
              ) : (
                renderBookingList(
                  bookings,
                  'No bookings yet',
                  'New learner requests will appear here.'
                )
              )}
            </div>
          </>
        )}

        {!isTeacher && (
          <div className="dashboard-section">
            <h2>My Learning Sessions</h2>
            {loading ? (
              <p role="status">Loading bookings...</p>
            ) : (
              renderBookingList(
                bookings,
                'No bookings yet',
                'Explore teachers to request a learning session.'
              )
            )}

            {!bookings.length && !loading && (
              <Link className="button button-outline" to="/explore">
                Explore Teachers
              </Link>
            )}
          </div>
        )}
      </div>

      {reviewModalBooking && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.45)',
            display: 'grid',
            placeItems: 'center',
            zIndex: 100,
            padding: '20px',
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) closeReviewModal();
          }}
        >
          <div className="form-card" style={{ maxWidth: '480px', width: '100%', padding: '28px', background: '#fffefa' }}>
            <h2 style={{ margin: '0 0 6px', fontSize: '20px' }}>
              Write a Review
            </h2>
            <p style={{ margin: '0 0 16px', fontSize: '12px', color: 'var(--muted)' }}>
              Share your learning experience with {reviewModalBooking.teacher?.name || 'your teacher'} for the session on {reviewModalBooking.bookingDate}.
            </p>

            {reviewError && (
              <p className="form-message" role="alert" style={{ color: '#b3261e', background: '#fdf2f2', marginBottom: '14px' }}>
                {reviewError}
              </p>
            )}

            <form onSubmit={submitReview}>
              <div style={{ marginBottom: '16px' }}>
                <span style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#49574a', marginBottom: '8px' }}>
                  Rating (1–5 Stars) *
                </span>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      type="button"
                      onClick={() => setReviewForm((f) => ({ ...f, rating: star }))}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        cursor: 'pointer',
                        fontSize: '28px',
                        lineHeight: 1,
                        padding: 0,
                        color: star <= reviewForm.rating ? '#d5a44f' : '#d2d6d2',
                        transition: 'transform 0.1s',
                      }}
                      aria-label={`${star} star${star > 1 ? 's' : ''}`}
                    >
                      ★
                    </button>
                  ))}
                  <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--ink)', marginLeft: '6px' }}>
                    {reviewForm.rating} / 5
                  </span>
                </div>
              </div>

              <label style={{ display: 'grid', gap: '6px', fontSize: '11px', fontWeight: 600, color: '#49574a', marginBottom: '18px' }}>
                Written Feedback *
                <textarea
                  rows="4"
                  required
                  maxLength="2000"
                  value={reviewForm.comment}
                  onChange={(e) => setReviewForm((f) => ({ ...f, comment: e.target.value }))}
                  placeholder="What did you learn? How was the teaching style?"
                  style={{ width: '100%', padding: '10px 11px', borderRadius: '7px', border: '1px solid #dfdfd5' }}
                />
              </label>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="button button-outline"
                  onClick={closeReviewModal}
                  disabled={submittingReview}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="button"
                  disabled={submittingReview}
                >
                  {submittingReview ? 'Submitting...' : 'Submit Review'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
}