# Railway Backend Deployment

This repo is now set up to deploy as a backend-only Railway service.

- The root `Dockerfile` is used directly by Railway.
- The app is served by Gunicorn through `wsgi.py`.
- Gunicorn binds to `0.0.0.0:$PORT`, which matches Railway's public networking requirement.
- Database migrations run on container startup through `docker/entrypoint.sh`.
- Nginx is no longer part of this repo's deployment flow.

## 1. Create the backend service
In Railway, create a service from this repository. Railway will automatically use the root `Dockerfile` as long as it is named `Dockerfile`.

## 2. Add the required variables
Set these service variables for the backend:

```dotenv
APP_ENV=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
SECRET_KEY=put-a-long-random-secret-here
TRUST_PROXY_HEADERS=1
RUN_DB_MIGRATIONS=1
```

Notes:
- `PORT` is injected automatically by Railway, so do not set it unless you have a special reason.
- If your PostgreSQL service has a different Railway service name than `Postgres`, update the reference accordingly.
- `TRUST_PROXY_HEADERS=1` should only be enabled when the app is actually behind Railway or your separate Nginx service and forwarded headers are being set correctly.

## 3. Deploy
Deploy the service from Railway. Startup works like this:

1. Railway builds the image from the root `Dockerfile`.
2. `docker/entrypoint.sh` runs `docker/migrate.py`.
3. Gunicorn starts `wsgi:application`.

The migration runner already uses a PostgreSQL advisory lock, so parallel starts will not apply the same migration twice.

## 4. Backend networking
For the final production setup, keep this backend service private and let your separate Nginx Railway service proxy to it over Railway's private network. We can wire up the exact Nginx config later when you are ready.

## 5. Optional tuning
You can tune Gunicorn with extra Railway variables if needed:

```dotenv
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=120
GUNICORN_GRACEFUL_TIMEOUT=30
```

## 6. Local container check
If you want to smoke-test the backend container locally:

```bash
docker compose up --build
```

That compose file is now backend-only and exposes the app on `http://localhost:8080`.

## 7. New migrations
Add each schema change as a new `.sql` file in `migrations/`, for example:

```text
2026-04-14_add_xyz.sql
```

On the next deployment, the container applies unapplied migration files in sorted order and records them in `public.schema_migrations`.
