# adiClub Upload

Aplicación web en **Streamlit** para que miembros de **adiClub** suban una
**foto** o un **video** desde un link público.

## Qué hace

1. Pide al miembro identificarse con **ID de adiClub** o **email**.
2. Valida formato de email, tipo de archivo y tamaño máximo:
   - imágenes: `jpg`, `jpeg`, `png`, `webp`, `gif` hasta **10 MB**
   - videos: `mp4`, `mov`, `webm` hasta **100 MB**
3. Guarda el archivo con nombre único (`uuid + extensión`).
4. Muestra preview y confirmación de la subida.
5. Incluye una **Galería (admin)** protegida con contraseña.

## Backends de almacenamiento

- `LOCAL` — desarrollo local, guarda en `uploads/`
- `CLOUDINARY` — recomendado para publicación pública en Streamlit Community Cloud
- `AZURE` — opción corporativa / productiva cuando haya suscripción

## Correr localmente

```bash
cd consumer-loyalty-os/adiclub-upload
pip install -r requirements.txt
streamlit run app.py
```

Por defecto usa `LOCAL`.

## Publicar en Streamlit Community Cloud con persistencia real

Para que la app sea pública y las subidas no se pierdan, usa:

- **Streamlit Community Cloud** para alojar la app
- **Cloudinary** para guardar imágenes y videos

### 1. Crea una cuenta en Cloudinary

Entra a <https://cloudinary.com/> y crea una cuenta gratuita.

Luego copia estos tres valores desde tu dashboard:

- `Cloud name`
- `API Key`
- `API Secret`

### 2. Crea la app en Streamlit Community Cloud

1. Sube `app.py`, `storage.py`, `requirements.txt` y `README.md` a un repo
   personal de GitHub.
2. Entra a <https://share.streamlit.io> y crea una app con:
   - **Repository:** tu repo personal
   - **Branch:** `main`
   - **Main file path:** `app.py`

### 3. Agrega los secrets

En **Advanced settings** o luego en **App settings → Secrets**, pega:

```toml
STORAGE_BACKEND = "CLOUDINARY"
ADMIN_PASSWORD = "tu-clave-secreta"

CLOUDINARY_CLOUD_NAME = "tu-cloud-name"
CLOUDINARY_API_KEY = "tu-api-key"
CLOUDINARY_API_SECRET = "tu-api-secret"
CLOUDINARY_FOLDER = "adiclub-upload"
```

### 4. Comparte el link público

Cuando el deploy termine, Streamlit te da un link tipo:

```text
https://adiclub-upload-xxxxx.streamlit.app
```

Cualquier persona con ese link podrá cargar contenido.

## Dónde ves luego el contenido

En la misma app:

1. Abre el link público
2. En la barra lateral elige **Galería (admin)**
3. Ingresa tu `ADMIN_PASSWORD`

Ahí verás:

- quién subió el archivo
- nombre original
- fecha
- preview
- botón **Abrir archivo**

Como los archivos viven en **Cloudinary**, no dependen del reinicio de Streamlit.

## Variables disponibles

| Variable | Uso |
| --- | --- |
| `STORAGE_BACKEND` | `LOCAL`, `CLOUDINARY` o `AZURE` |
| `ADMIN_PASSWORD` | contraseña de la galería admin |
| `LOCAL_STORAGE_DIR` | carpeta local para backend `LOCAL` |
| `CLOUDINARY_CLOUD_NAME` | cloud name de Cloudinary |
| `CLOUDINARY_API_KEY` | API key de Cloudinary |
| `CLOUDINARY_API_SECRET` | API secret de Cloudinary |
| `CLOUDINARY_FOLDER` | carpeta lógica en Cloudinary |
| `AZURE_STORAGE_CONNECTION_STRING` | conexión a Azure Blob |
| `AZURE_STORAGE_CONTAINER` | container de Azure Blob |

## Estructura

```text
adiclub-upload/
├── app.py
├── storage.py
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── deploy-azure.ps1
├── README.md
└── .gitignore
```
