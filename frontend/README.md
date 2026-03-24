# LocalVideo Frontend

Web UI for LocalVideo, built with Next.js 16, React 19, TypeScript, Tailwind CSS, Zustand, and TanStack Query.

## Requirements

- Node.js 22+
- pnpm 10+

## Local Development

```bash
cd frontend
pnpm install
pnpm dev
```

The app runs on `http://localhost:3000` by default.

To point the frontend at a different backend API:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 pnpm dev
```

## Common Commands

```bash
cd frontend

# Start the dev server
pnpm dev

# Lint the codebase
pnpm lint

# Create a production build
pnpm build

# Run the production server locally
pnpm start

# Run Playwright end-to-end tests
pnpm test:e2e
```

If you use `just`, the root workspace also exposes:

```bash
just frontend-sync
just dev-frontend
just lint-frontend
just build-frontend
just test-e2e
```

## Docker Development

For hot reload inside Docker, use the workspace-level development compose setup:

```bash
just docker-dev-cpu
# or
just docker-dev-gpu
```

This mounts `./frontend` into the container and runs the app in development mode.

## Project Structure

- `src/app`: Next.js App Router entrypoints and pages
- `src/components`: reusable UI and feature components
- `src/hooks`: custom React hooks
- `src/lib`: API client and shared helpers
- `src/stores`: Zustand stores
- `src/types`: shared TypeScript types

## Notes

- The frontend expects the backend API under `/api/v1`.
- End-to-end tests use Playwright. Install browsers with `pnpm exec playwright install chromium` when running locally for the first time.
