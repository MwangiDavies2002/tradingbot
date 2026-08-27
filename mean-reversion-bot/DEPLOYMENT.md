# Deploying the dashboard API and database

This repository is configured as one Vercel project: Vite builds the dashboard and `api/index.py` exposes the FastAPI routes as a Python serverless function. The persistent Deriv trading process is deliberately **not** run by Vercel; deploy `python -m app.bot` to an always-on worker service with the same environment variables.

## 1. Create Supabase database

1. Create a Supabase project.
2. In **Connect**, copy the **Session Pooler** connection string. Change its scheme from `postgresql://` to `postgresql+asyncpg://` and use it as `DATABASE_URL`.
3. The API creates its tables at startup. For a production workflow, replace this bootstrap behavior with Alembic migrations before managing schema changes.

## 2. Deploy to Vercel

Import this repository in Vercel with `mean-reversion-bot` as the project root, or deploy from this directory with `vercel --prod`.

Set these Production environment variables in Vercel:

```
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://...
SECRET_KEY=<a-long-random-secret>
DERIV_APP_ID=<your-deriv-app-id>
DERIV_API_TOKEN=<your-deriv-token>
DERIV_DEMO=True
ALLOWED_ORIGINS=["https://<your-project>.vercel.app"]
```

`REDIS_URL` is optional. If omitted or unreachable, the API works without the cache.

After the first deployment, use the generated `https://<your-project>.vercel.app` URL in `ALLOWED_ORIGINS`, redeploy, then confirm `https://<your-project>.vercel.app/health` reports a healthy database.

## Important operational boundary

Vercel functions have execution time limits and must not run the continuous WebSocket-based bot loop. Keep the dashboard/API on Vercel, Supabase as the shared database, and run the worker separately. Never put a real-money Deriv token in the frontend or in a `VITE_*` variable.
