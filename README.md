# Tent Rental For Course DV1703

Flask + PostgreSQL backend prepared to run as a standalone WSGI service on Railway.

## Local development
1. Install the dependencies and make sure PostgreSQL is available.
2. Create `.env` with at least `DATABASE_URL` and `SECRET_KEY`.
3. Create the database and apply `schema_postgres.sql` or the SQL files in `migrations/`.
4. Run the app with `flask --app run.py --debug run`.

## Local container smoke test
Run `docker compose up --build` and open `http://localhost:8080`.

## Railway deployment
The production container now runs:
- startup migrations through `docker/entrypoint.sh`
- Gunicorn with WSGI through `wsgi.py`
- Railway's injected `PORT` via `gunicorn.conf.py`

Deployment details and Railway variables are in `DEPLOY.md`.

## Seeding demo data
This project includes a small seed script that:
- creates an admin account: `karl.wikell@gmail.com` (password: `DV1703`)
- creates a customer for testing: `hej.hej@hej.hej` (password: `DV1703`)
- inserts demo tents and furnishings into the inventory

Run it after you have applied the schema and set `DATABASE_URL`:

```bash
python seed.py
```
