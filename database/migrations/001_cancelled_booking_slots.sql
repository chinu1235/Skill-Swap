-- One-time, data-preserving migration for the earlier simple slot constraint.
-- The previous UNIQUE(teacher_id, booking_date, booking_time) blocks reuse even
-- after cancellation. Cancelled rows now generate NULL for active_booking_time;
-- MySQL permits multiple NULLs in a UNIQUE index, while active rows remain unique.
-- Existing schema.sql used the index name uq_bookings_teacher_slot.

USE `skillswap_db`;

ALTER TABLE `bookings`
  DROP INDEX `uq_bookings_teacher_slot`,
  ADD COLUMN `active_booking_time` TIME GENERATED ALWAYS AS (
    CASE WHEN `status` = 'cancelled' THEN NULL ELSE `booking_time` END
  ) STORED,
  ADD CONSTRAINT `uq_bookings_active_teacher_slot`
    UNIQUE (`teacher_id`, `booking_date`, `active_booking_time`);
