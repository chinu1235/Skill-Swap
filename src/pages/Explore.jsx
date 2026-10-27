
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import TeacherCard from '../components/TeacherCard.jsx';
import { apiRequest, buildQuery } from '../services/api.js';
import { teachers as demoTeachers, skills as demoSkills } from '../data/teachers.js';

function cardTeacher(teacher) {
  const skillNames = (teacher.skills || []).map((item) =>
    typeof item === 'string' ? item : item.skillName || ''
  );

  return {
    id: teacher.id,
    name: teacher.name,
    skill: skillNames[0] || teacher.skill || 'Peer teacher',
    skills: skillNames,
    description:
      teacher.bio ||
      teacher.teachingStyle ||
      teacher.description ||
      'A SkillSwap teacher ready to share what they know.',
    rating: Number(teacher.rating || 0),
    sessions: Number(teacher.totalSessions ?? teacher.sessions ?? 0),
    avatar: (teacher.name || 'SS')
      .split(/\s+/)
      .map((part) => part[0])
      .slice(0, 2)
      .join('')
      .toUpperCase(),
    color: 'sage',
  };
}

export default function Explore() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get('search') || '');
  const [appliedSearch, setAppliedSearch] = useState(params.get('search') || '');
  const [category, setCategory] = useState(params.get('category') || '');
  const [skill, setSkill] = useState(params.get('skill') || '');
  const [rating, setRating] = useState(params.get('minRating') || '');
  const [skills, setSkills] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(
      () => setAppliedSearch(search.trim()),
      350
    );
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let active = true;

    apiRequest('/api/skills')
      .then((result) => {
        if (!active) return;

        const apiSkills = result.skills || [];
        setSkills(
          apiSkills.length
            ? apiSkills
            : demoSkills.map((item, index) => ({
                id: `demo-skill-${index}`,
                skillName: item.name,
                category: item.name,
                description: item.description,
              }))
        );
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setSkillsLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    setLoading(true);
    setError('');

    const query = buildQuery({
      search: appliedSearch,
      category,
      skill,
      minRating: rating,
    });

    apiRequest('/api/teachers' + query, { signal: controller.signal })
      .then((result) => {
        if (active) setTeachers(result.teachers || []);
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
  }, [appliedSearch, category, skill, rating]);

  useEffect(() => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      const values = {
        search: appliedSearch,
        category,
        skill,
        minRating: rating,
      };

      Object.entries(values).forEach(([key, value]) => {
        if (value) next.set(key, value);
        else next.delete(key);
      });

      return next;
    }, { replace: true });
  }, [appliedSearch, category, skill, rating, setParams]);

  const categories = useMemo(
    () => [...new Set(skills.map((item) => item.category).filter(Boolean))].sort(),
    [skills]
  );

  const cards = useMemo(() => {
    const query = appliedSearch.trim().toLowerCase();

    const allTeachers = [
      ...demoTeachers,
      ...teachers.map(cardTeacher),
    ];

    return allTeachers.filter((teacher) => {
      const name = (teacher.name || '').toLowerCase();
      const mainSkill = (teacher.skill || '').toLowerCase();
      const description = (teacher.description || teacher.bio || '').toLowerCase();

      const teacherSkills = (teacher.skills || []).map((item) =>
        (typeof item === 'string' ? item : item.skillName || '').toLowerCase()
      );

      const matchesSearch =
        !query ||
        name.includes(query) ||
        mainSkill.includes(query) ||
        description.includes(query) ||
        teacherSkills.some((item) => item.includes(query));

      const matchesCategory =
        !category ||
        teacherSkills.some((item) => item === category.toLowerCase()) ||
        mainSkill === category.toLowerCase();

      const matchesSkill =
        !skill ||
        teacherSkills.some((item) => item === skill.toLowerCase()) ||
        mainSkill === skill.toLowerCase();

      const matchesRating =
        !rating || Number(teacher.rating || 0) >= Number(rating);

      return matchesSearch && matchesCategory && matchesSkill && matchesRating;
    });
  }, [appliedSearch, category, skill, rating, teachers]);

  const clearFilters = () => {
    setSearch('');
    setAppliedSearch('');
    setCategory('');
    setSkill('');
    setRating('');
  };

  return (
    <section className="page-section explore-page">
      <div className="container">
        <div className="page-heading">
          <span className="eyebrow">A good place to begin</span>
          <h1>Explore Skills &amp; Teachers</h1>
          <p>
            Find a skill that sparks your curiosity and a person who can help you grow.
          </p>
        </div>

        <div className="explore-controls">
          <label className="search-box">
            <span aria-hidden="true">⌕</span>
            <input
              aria-label="Search skill or teacher"
              type="search"
              placeholder="Search skill or teacher"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>

          <label className="filter-label">
            Category
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              disabled={skillsLoading}
            >
              <option value="">All Categories</option>
              {categories.map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>

          <label className="filter-label">
            Skill
            <select
              value={skill}
              onChange={(event) => setSkill(event.target.value)}
              disabled={skillsLoading}
            >
              <option value="">All Skills</option>
              {skills.map((item) => (
                <option key={item.id} value={item.skillName}>
                  {item.skillName}
                </option>
              ))}
            </select>
          </label>

          <label className="filter-label">
            Rating
            <select
              value={rating}
              onChange={(event) => setRating(event.target.value)}
            >
              <option value="">All Ratings</option>
              <option value="4">4+ Stars</option>
              <option value="4.5">4.5+ Stars</option>
            </select>
          </label>
        </div>

        <div className="results-heading">
          <h2>{category || skill || 'Teachers to explore'}</h2>
          <span>
            {loading
              ? 'Loading...'
              : `${cards.length} ${cards.length === 1 ? 'teacher' : 'teachers'}`}
          </span>
        </div>

        {error && <p className="form-message" role="alert">{error}</p>}

        {loading ? (
          <p role="status">Loading teachers...</p>
        ) : cards.length > 0 ? (
          <div className="teachers-grid">
            {cards.map((teacher) => (
              <TeacherCard key={teacher.id} teacher={teacher} />
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <span aria-hidden="true">⌕</span>
            <h3>No teachers found just yet</h3>
            <p>Try another search or change your filters.</p>
            <button
              type="button"
              className="button button-outline"
              onClick={clearFilters}
            >
              Clear filters
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
