import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Hero from '../components/Hero.jsx';
import RoleSwitch from '../components/RoleSwitch.jsx';
import SkillCard from '../components/SkillCard.jsx';
import TeacherCard from '../components/TeacherCard.jsx';
import HowItWorks from '../components/HowItWorks.jsx';
import WhySection from '../components/WhySection.jsx';
import CTA from '../components/CTA.jsx';
import { teachers as demoTeachers, skills as skillPresentation } from '../data/teachers.js';
import { apiRequest } from '../services/api.js';

function cardTeacher(teacher) {
  const skill = teacher.skills?.[0]?.skillName || 'Peer teacher';
  return {
    id: teacher.id,
    name: teacher.name,
    skill,
    description: teacher.bio || teacher.teachingStyle || 'A SkillSwap teacher ready to share what they know.',
    rating: Number(teacher.rating || 0),
    sessions: Number(teacher.totalSessions || 0),
    avatar: (teacher.name || 'SS').split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase(),
    color: 'sage',
  };
}

export default function Home() {
  const [skills, setSkills] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [skillsLoading, setSkillsLoading] = useState(true);
  const [teachersLoading, setTeachersLoading] = useState(true);
  const [skillsError, setSkillsError] = useState('');
  const [teachersError, setTeachersError] = useState('');

  useEffect(() => {
    let active = true;
    apiRequest('/api/skills')
      .then((result) => { if (active) setSkills(result.skills || []); })
      .catch((error) => { if (active) setSkillsError(error.message); })
      .finally(() => { if (active) setSkillsLoading(false); });
    apiRequest('/api/teachers')
      .then((result) => { if (active) setTeachers(result.teachers || []); })
      .catch((error) => { if (active) setTeachersError(error.message); })
      .finally(() => { if (active) setTeachersLoading(false); });
    return () => { active = false; };
  }, []);

  const popularSkills = skillPresentation.map((presentation, index) => {
  const item = skills.find(
    (skill) => skill.skillName?.toLowerCase() === presentation.name.toLowerCase()
  );

  return {
    id: item?.id || `demo-skill-${index}`,
    name: item?.skillName || presentation.name,
    category: item?.category || presentation.name,
    description: presentation.description,
    icon: presentation.icon,
  };
});
  const topTeachers = [
  ...demoTeachers.map((teacher) => ({
    id: teacher.id,
    name: teacher.name,
    skill: teacher.skill,
    description: teacher.description,
    rating: teacher.rating,
    sessions: teacher.sessions,
    avatar: teacher.avatar,
    color: teacher.color,
  })),
  ...teachers.map(cardTeacher),
].slice(0, 4);

  return <><Hero /><RoleSwitch />
    <section className="section skills-section"><div className="container">
      <div className="section-heading section-heading-row"><div><span className="eyebrow">Find your next thing</span><h2>Popular Skills</h2><p>A few good places to start exploring.</p></div><Link className="text-link all-link" to="/explore">See all skills <span aria-hidden="true">→</span></Link></div>
      {skillsLoading ? <p role="status">Loading skills...</p> : skillsError ? <p className="form-message" role="alert">{skillsError}</p> : popularSkills.length ? <div className="skills-grid">{popularSkills.map((skill, index) => <SkillCard key={skill.id} skill={skill} index={index} />)}</div> : <p>No skills are available yet.</p>}
    </div></section>
    <section className="section teachers-section"><div className="container">
      <div className="section-heading section-heading-row"><div><span className="eyebrow">Learn from one another</span><h2>Top Rated Teachers</h2><p>Meet teachers from the SkillSwap community.</p></div><Link className="text-link all-link" to="/explore">Meet all teachers <span aria-hidden="true">→</span></Link></div>
      {teachersLoading ? <p role="status">Loading teachers...</p> : teachersError ? <p className="form-message" role="alert">{teachersError}</p> : topTeachers.length ? <div className="teachers-grid">{topTeachers.map((teacher) => <TeacherCard teacher={teacher} key={teacher.id} />)}</div> : <p>No teacher profiles are available yet.</p>}
    </div></section>
    <HowItWorks /><WhySection /><CTA />
  </>;
}
