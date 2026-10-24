<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/justforms-logo-dark.png">
    <img src="docs/brand/justforms-logo.png" alt="JustForms" width="320">
  </picture>
</p>

<p align="center"><strong>Open-source forms in English and Dhivehi, with signed PDFs.</strong></p>

<p align="center">
  <a href="LICENSE"><img alt="Licence: AGPL-3.0" src="https://img.shields.io/badge/licence-AGPL--3.0-3B3FC1?style=flat-square"></a>
  <img alt="Status: early development" src="https://img.shields.io/badge/status-early%20development-FFE45C?style=flat-square&labelColor=18203A">
  <img alt="Self-hosted" src="https://img.shields.io/badge/self--hosted-Docker%20%7C%20Helm-18203A?style=flat-square&logo=docker&logoColor=white">
  <img alt="RTL and Thaana" src="https://img.shields.io/badge/RTL-Thaana%20ready-0F766E?style=flat-square">
</p>
<p align="center">
  <img alt="Python 3.13" src="https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white">
  <img alt="React 19" src="https://img.shields.io/badge/React-19-149ECA?style=flat-square&logo=react&logoColor=white">
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white">
  <img alt="shadcn/ui" src="https://img.shields.io/badge/shadcn%2Fui-000000?style=flat-square&logo=shadcnui&logoColor=white">
  <img alt="Tailwind CSS" src="https://img.shields.io/badge/Tailwind%20CSS-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white">
</p>

JustForms is a self-hosted forms builder for organisations that still run on paper: applications,
registrations, requests and declarations. Staff build a form on a canvas that looks exactly like
what respondents see, people fill it on their phones in **English or Dhivehi**, and every signed
response becomes a PDF that anyone can check is genuine. It is in early development.

<table>
  <tr>
    <td width="75%" valign="middle"><img src="docs/images/builder.webp" alt="The form builder: question types on the left, the form as a white sheet in the middle with the selected question marked in yellow, its settings on the right"></td>
    <td width="25%" valign="middle"><img src="docs/images/dhivehi-phone.webp" alt="A Dhivehi form on a phone, right to left in Thaana"></td>
  </tr>
</table>

## Features

- **Builder** with a true-to-life canvas, autosave, undo, live preview and published versions.
- **Logic**: multi-page forms with show, hide, require and skip-page rules.
- **Dhivehi** forms right to left in Thaana fonts, with a phonetic Thaana keyboard.
- **Signed PDFs** (PAdES) with a QR code to a public verify page.
- **Approvals** in up to three steps; approvers need no account.
- **Submissions** table with statuses, comments, masking and Excel export; emails and signed webhooks.
- **People and roles**: invite by email as admin, form creator or member; share forms per person.
- **AI assistant** (optional) and **Jotform import** to get forms in quickly.
- **Branding and form themes**, OIDC or emailed-code sign-in, Docker Compose or Helm.

## Quickstart

You need Docker with Compose.

```sh
git clone https://github.com/alee-ibrahim/justforms.git && cd justforms/deploy/compose
cp .env.example .env      # set JUSTFORMS_SECRET_KEY and the change-me passwords
docker compose --profile dev up -d --build
docker compose run --rm migrate python -m app.cli create-admin --email you@example.org
```

Open http://localhost:8080 and sign in with that email; the one-time code arrives in Mailpit at
http://localhost:8025.

## Documentation

- [Features](docs/features.md): a full tour, with screenshots
- [Configuration](docs/configuration.md): every `JUSTFORMS_*` setting
- [Deployment](docs/deployment.md): Docker Compose, tunnels, Helm, upgrades and backups
- [Development](docs/development.md): local setup, tests, project structure, contributing
- [Security](docs/security.md): security model and verifying signed PDFs
- [All docs](docs/README.md), including the design document and webhooks reference

## Licence

[AGPL-3.0](LICENSE). Contributions are accepted under the same licence.
