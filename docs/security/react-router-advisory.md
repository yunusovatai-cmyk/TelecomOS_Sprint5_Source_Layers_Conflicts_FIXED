# React Router security upgrade advisory

## Current state

The frontend declares `react-router-dom` as `^6.28.0`. The current lockfile resolves both `react-router-dom` and its transitive `react-router` dependency to `6.30.4`. Both packages are production/runtime dependencies.

`npm audit` reports two moderate vulnerable package entries for the 6.x dependency tree:

- `react-router-dom`: open redirect leading to cross-site scripting (`GHSA-jjmj-jmhj-qwj2`). The affected range includes `6.30.2` through `6.30.4`.
- `react-router`: open redirect through backslashes in `<Link>` and `useNavigate` (`GHSA-wrjc-x8rr-h8h6`) and arbitrary constructor injection during SSR error hydration (`GHSA-337j-9hxr-rhxg`). Versions before `7.18.0` are affected by these advisories.

## Why 7.18.2 was rejected

A migration was evaluated on the local branch `chore/react-router-7-security-upgrade`. Installing `react-router-dom@7.18.2` also installed `react-router@7.18.2` and removed the original moderate findings, but the resulting dependency tree introduced a high-severity finding from the performed `npm audit`:

- `GHSA-qwww-vcr4-c8h2`: React Router RSC mode CSRF bypass can allow action execution before a 400 response. The audit marked `react-router` versions `>=7.12.0 <8.3.0` as affected and propagated the finding to `react-router-dom`.

The audit's suggested available version was `7.11.0`. That downgrade does not satisfy the requested `^7.18.0` migration and falls back into the ranges affected by the earlier moderate advisories. Moving to 7.18.2 would therefore replace two moderate findings with a high-severity finding rather than produce a secure upgrade.

The migration branch was left without file changes. It was not merged or pushed.

## Criterion for resuming the migration

Resume the migration only when an installable React Router release closes both advisory groups:

1. The 6.x open-redirect/XSS and SSR hydration findings represented by `GHSA-jjmj-jmhj-qwj2`, `GHSA-wrjc-x8rr-h8h6`, and `GHSA-337j-9hxr-rhxg`.
2. The RSC CSRF finding `GHSA-qwww-vcr4-c8h2`.

Before implementation, confirm the candidate version using a fresh `npm audit --json` and the published advisory ranges. The resulting audit must contain no React Router vulnerability of equal or greater severity.

## Required validation after a future update

The future migration must run and pass all of the following checks:

- Clean install with `npm ci` and a reviewed `npm audit --json` report.
- TypeScript check and `npm run build`.
- Frontend routing tests covering internal links, direct `/projects` loading, Engineering Map navigation, browser back/forward, percent-encoded URLs, backslash-containing URLs, external redirect attempts, and safe behavior for both `Link` and `useNavigate`.
- Compatibility checks for `BrowserRouter`, `Routes`, `Route`, `NavLink`, `Link`, `useNavigate`, splat routes, relative navigation, query parameters, and direct refreshes of nested routes.
- Backend `pytest` regression suite.
- Reproducible Sprint 5 smoke test through `scripts/e2e_smoke.sh`.
- `docker compose build`, healthy service startup, and backend/frontend log review.
- Manual browser checks of Dashboard, Projects, Engineering Map, Import Center, Review Queue, object selection, the map and asset inspector, and page refresh on every application route.

