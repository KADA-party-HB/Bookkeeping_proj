# Deployment steps

## 1) Add the files to your repo
Copy these files into the repo root:
- Dockerfile
- docker/entrypoint.sh
- docker/migrate.py
- docker/nginx.conf
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
- docker/nginx.conf
- certs/devcert.crt
- certs/devcert.key

Example `.env`:
```dotenv
DATABASE_URL=postgresql://postgres:CHANGE_ME@host.docker.internal:5432/tentrental
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

## 5) HTTPS access
The compose file exposes Nginx on ports 80 and 443. Nginx redirects HTTP to HTTPS and proxies to the Flask app over Docker's internal network.
Open it from another machine on your LAN with:

https://YOUR_SERVER_IP

Because `devcert.crt` is self-signed, browsers will show a certificate warning unless that certificate is trusted on the client device.

## 6) New migrations
Add a new file to `migrations/`, for example:
```text
2026-04-14_add_xyz.sql
```

On the next container start after `docker compose pull && docker compose up -d`, the entrypoint runs all unapplied migration files in sorted order and records them in `public.schema_migrations`.
