# Tent Rental For Course DV1703 (Flask + PostgreSQL)

## Run
1) Install deps (Including postgre DB)
2) Create .env and add "DATABASE_URL, "
2) Create DB and apply schema_postgres.sql
3) Set DATABASE_URL in .env
4) `flask --app run.py --debug run`

## Seeding (demo data)
This project includes a small seed script that:
- creates/updates an admin account: `karl.wikell@gmail.com` (password: `DV1703`)
- inserts demo tents and furnishings into the inventory

Run it after you’ve applied `schema_postgres.sql` and set `DATABASE_URL`:

```bash
`python seed.py`