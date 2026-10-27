-- SkillSwap database schema for MySQL 8.0.16+.
-- This script creates the schema for a fresh database. It does not drop data.

CREATE DATABASE IF NOT EXISTS `skillswap_db`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `skillswap_db`;

CREATE TABLE `users` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `full_name` VARCHAR(100) NOT NULL,
  `email` VARCHAR(150) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `role` ENUM('learner', 'teacher') NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `uq_users_email` UNIQUE (`email`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `teacher_profiles` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `bio` TEXT NULL,
  `experience` VARCHAR(100) NULL,
  `teaching_style` VARCHAR(255) NULL,
  `rating` DECIMAL(3,2) NOT NULL DEFAULT 0.00,
  `total_sessions` INT NOT NULL DEFAULT 0,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `uq_teacher_profiles_user` UNIQUE (`user_id`),
  CONSTRAINT `chk_teacher_profiles_rating` CHECK (`rating` >= 0.00 AND `rating` <= 5.00),
  CONSTRAINT `chk_teacher_profiles_sessions` CHECK (`total_sessions` >= 0),
  CONSTRAINT `fk_teacher_profiles_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON UPDATE CASCADE ON DELETE CASCADE,
  KEY `idx_teacher_profiles_rating` (`rating`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `skills` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `skill_name` VARCHAR(100) NOT NULL,
  `category` VARCHAR(100) NOT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `uq_skills_skill_name` UNIQUE (`skill_name`),
  KEY `idx_skills_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `teacher_skills` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `teacher_id` INT NOT NULL,
  `skill_id` INT NOT NULL,
  PRIMARY KEY (`id`),
  CONSTRAINT `uq_teacher_skills_teacher_skill` UNIQUE (`teacher_id`, `skill_id`),
  CONSTRAINT `fk_teacher_skills_teacher`
    FOREIGN KEY (`teacher_id`) REFERENCES `teacher_profiles` (`id`)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT `fk_teacher_skills_skill`
    FOREIGN KEY (`skill_id`) REFERENCES `skills` (`id`)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  KEY `idx_teacher_skills_skill` (`skill_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `bookings` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `learner_id` INT NOT NULL,
  `teacher_id` INT NOT NULL,
  `skill_id` INT NULL,
  `booking_date` DATE NOT NULL,
  `booking_time` TIME NOT NULL,
  `duration_minutes` INT NOT NULL DEFAULT 60,
  `session_type` VARCHAR(50) NOT NULL DEFAULT 'Online',
  `notes` TEXT NULL,
  `status` ENUM('pending', 'confirmed', 'completed', 'cancelled') NOT NULL DEFAULT 'pending',
  `active_booking_time` TIME GENERATED ALWAYS AS (
    CASE WHEN `status` = 'cancelled' THEN NULL ELSE `booking_time` END
  ) STORED,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `uq_bookings_active_teacher_slot`
    UNIQUE (`teacher_id`, `booking_date`, `active_booking_time`),
  CONSTRAINT `chk_bookings_duration` CHECK (`duration_minutes` > 0),
  CONSTRAINT `fk_bookings_learner`
    FOREIGN KEY (`learner_id`) REFERENCES `users` (`id`)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT `fk_bookings_teacher`
    FOREIGN KEY (`teacher_id`) REFERENCES `teacher_profiles` (`id`)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT `fk_bookings_skill`
    FOREIGN KEY (`skill_id`) REFERENCES `skills` (`id`)
    ON UPDATE CASCADE ON DELETE SET NULL,
  KEY `idx_bookings_learner_date` (`learner_id`, `booking_date`),
  KEY `idx_bookings_teacher_date` (`teacher_id`, `booking_date`),
  KEY `idx_bookings_skill` (`skill_id`)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
