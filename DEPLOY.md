# Deployment steps

## 1) Add the files to your repo
Copy these files into the repo root:
- Dockerfile
- docker/entrypoint.sh
- docker/migrate.py
- wsgi.py
- .dockerignore
- docker-compose.yml
- .github/workflows/docker-publish.yml

## 2) Commit and push
```bash
git add Dockerfile docker/ wsgi.py .dockerignore docker-compose.yml .github/workflows/docker-publish.yml
git commit -m "Add container build, migrations, and GHCR publish workflow"
git push origin main
```

## 3) Enable package permissions
In the GitHub repo:
- Settings -> Actions -> General -> Workflow permissions
- Allow read and write permissions

## 4) Pull on the server
Install Docker + Compose plugin if needed.

Create a deployment directory on the server, for example:
```bash
mkdir -p /opt/dv1703-bookingservice
cd /opt/dv1703-bookingservice
```

Put these files there:
- docker-compose.yml
- .env

Example `.env`:
```dotenv
DATABASE_URL=postgresql://postgres:CHANGE_ME@localhost:5432/tentrental
SECRET_KEY=put-a-long-random-secret-here
```

If the GHCR package is private, log in once on the server with a PAT that has `read:packages`:
```bash
echo YOUR_GH_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

Start or update:
```bash
docker compose pull
docker compose up -d
```

Check logs:
```bash
docker compose logs -f
```

## 5) LAN access
Because the compose file uses `network_mode: host`, the app binds directly on the server network.
Open it from another machine on your LAN with:

http://YOUR_SERVER_IP:9342

## 6) New migrations
Add a new file to `migrations/`, for example:
```text
2026-04-14_add_xyz.sql
```

On the next container start after `docker compose pull && docker compose up -d`, the entrypoint runs all unapplied migration files in sorted order and records them in `public.schema_migrations`.
