import { Link } from 'react-router-dom';

export default function SkillCard({ skill, index = 0 }) {
  const teacher = skill.teacher;
  const description = skill.description || (teacher
    ? 'Learn with ' + teacher.name + '.'
    : 'Explore this skill with a friendly peer teacher.');
  const target = teacher
    ? '/teachers/' + teacher.id
    : '/explore?skill=' + encodeURIComponent(skill.name);

  return <article className={'skill-card tone-' + (index % 4)}>
    <div className="skill-card-top"><span className="skill-icon" aria-hidden="true">{skill.icon || '✳'}</span><span className="card-arrow" aria-hidden="true">↗</span></div>
    <h3>{skill.name}</h3><p>{description}</p>
    <Link className="text-link" to={target}>Explore <span aria-hidden="true">→</span></Link>
  </article>;
}
