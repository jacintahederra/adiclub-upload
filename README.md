---
title: adiClub Upload
emoji: 👟
colorFrom: blue
colorTo: green
sdk: streamlit
app_file: app.py
pinned: false
---

# adiClub Upload — MVP

Página donde miembros de adiClub se identifican (ID o email) y suben una foto o
video. Incluye galería de administrador protegida por contraseña.

## Secrets (Settings → Variables and secrets)

- `ADMIN_PASSWORD` — contraseña de la galería de admin (cámbiala).
- Opcional, para persistir en Azure Blob (si no, almacenamiento efímero):
  - `STORAGE_BACKEND = AZURE`
  - `AZURE_STORAGE_CONNECTION_STRING = ...`
  - `AZURE_STORAGE_CONTAINER = adiclub-uploads`

> Sin Azure, las subidas usan el disco efímero del Space y se pierden al
> reiniciar/reconstruir. Para el demo está bien.
