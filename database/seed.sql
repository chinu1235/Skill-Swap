-- Development catalog data only. No demo users or passwords are inserted.
USE `skillswap_db`;

INSERT INTO `skills` (`skill_name`, `category`) VALUES
  ('Web Development', 'Technology'),
  ('Python', 'Programming'),
  ('Java', 'Programming'),
  ('C++', 'Programming'),
  ('JavaScript', 'Programming'),
  ('React', 'Technology'),
  ('UI/UX Design', 'Design'),
  ('Graphic Design', 'Design'),
  ('Video Editing', 'Creative'),
  ('Data Analytics', 'Data'),
  ('Digital Marketing', 'Marketing')
ON DUPLICATE KEY UPDATE
  `category` = VALUES(`category`);
