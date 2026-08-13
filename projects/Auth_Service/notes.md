# Project Info
Mission: Modernize OAuth2 and Single Sign-On (SSO) infrastructure for enterprise clients with zero downtime.
Tech Stack: FastAPI, PostgreSQL, Redis, PyJWT, Docker.
Lead Engineer: Alex Mercer (alex.mercer@company.com)

## Tasks
- [ ] Implement OAuth2 PKCE flow for mobile clients #p1 @2026-08-25 #blocked: Client App SDK update (Critical security upgrade for native apps)
- [ ] Add Redis token revocation cache #p2 @2026-08-30 (Speed up JWT blacklist checks)
- [ ] Configure PostgreSQL connection pooling #p3 #in_progress (Using PgBouncer with 50 connection limit)
- [ ] Write integration tests for SSO SAML 2.0 assertions #p2 #dep: Test IdP staging environment (Verify XML signature validation)
- [x] Set up OpenTelemetry tracing for auth middleware (Export traces to Jaeger)

## PROJECT SUMMARY
The Auth Service modernization is on track with core infrastructure established, including PgBouncer connection pooling and OpenTelemetry distributed tracing. Active focus is directed toward mobile client security via OAuth2 PKCE and implementing token revocation via Redis. The project is led by Alex Mercer to modernize enterprise SSO with zero downtime using FastAPI and PostgreSQL.

## ARCHIVE
- [x] Initial FastAPI repository scaffolding (Archived: 2026-08-01)
