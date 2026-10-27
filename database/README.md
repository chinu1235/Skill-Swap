# SkillSwap MySQL database

Database name: `skillswap_db`

The schema uses MySQL with InnoDB and `utf8mb4`. It contains `users`,
`teacher_profiles`, `skills`, `teacher_skills`, and `bookings`.

## Fresh setup

Run the schema and seed scripts from the project root with a MySQL client:

```sh
mysql -u YOUR_MYSQL_USER -p < database/schema.sql
mysql -u YOUR_MYSQL_USER -p < database/seed.sql
```

The seed script inserts the sample skill catalog only. It does not create user
accounts or plaintext passwords. Application passwords should later be stored
as Werkzeug-generated hashes in `users.password_hash`.

## Relationships and constraints

- One user can have at most one teacher profile (`teacher_profiles.user_id` is
  unique).
- `teacher_skills` links teacher profiles and skills many-to-many. Its unique
  `(teacher_id, skill_id)` constraint prevents duplicate assignments.
- A booking references a learner user, a teacher profile, and an optional skill.
- A unique `(teacher_id, booking_date, active_booking_time)` constraint
  prevents two active bookings for the same teacher and time. Cancelled rows
  store `NULL` in the generated `active_booking_time`, so their slots can be
  booked again without deleting the historical booking.
- User email and skill name are unique. Foreign keys enforce references, and
  check constraints validate ratings, session counts, and booking duration.

## Existing older schema

The project's previous `schema.sql` used a different layout (including
`teacher_profiles.user_id` as its primary key, `skills.name`, and different
booking/teacher-skill column names). This schema is for a fresh database; it
does not drop or silently alter existing tables. If that earlier schema has
already been applied to a MySQL server, back it up and migrate its data and
columns before running this schema. The SQL could not be executed against a
MySQL server in the current environment, so no migration or server execution is
claimed here.

## Existing booking slot constraint

If the current database already uses the earlier
`UNIQUE(teacher_id, booking_date, booking_time)` index named
`uq_bookings_teacher_slot`, run this one-time migration to allow cancelled
slots to be reused while retaining every booking row:

```sh
mysql -u YOUR_MYSQL_USER -p < database/migrations/001_cancelled_booking_slots.sql
```

Do not run this migration on a fresh database created from the current
`schema.sql`; that schema already has the cancellation-aware generated column
and unique index.
