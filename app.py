"""adiClub media upload app.

A single-page app where an adiClub member identifies themselves (member ID or
email) and then uploads a photo or a video. Files are validated (type + size),
stored via a pluggable storage backend, and previewed on success.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import os
import re

import streamlit as st

from storage import UploadMetadata, build_stored_filename, get_storage_backend

# --- Configuration -----------------------------------------------------------

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_VIDEO_BYTES = 30 * 1024 * 1024  # 30 MB

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Admin gallery password env var name. Set ADMIN_PASSWORD (env var or Streamlit
# secret) to override the default. The gallery is only visible to whoever knows
# this password.
DEFAULT_ADMIN_PASSWORD = "adiclub-admin"


def _load_secrets_into_env() -> None:
    """Bridge Streamlit secrets into environment variables.

    On Streamlit Community Cloud configuration is provided via ``st.secrets``.
    Copying them into ``os.environ`` lets the storage layer (which reads env
    vars) work unchanged across local, Azure, and Streamlit Cloud.
    """

    try:
        secrets = st.secrets
    except Exception:
        return
    for key in (
        "STORAGE_BACKEND",
        "LOCAL_STORAGE_DIR",
        "AZURE_STORAGE_CONNECTION_STRING",
        "AZURE_STORAGE_CONTAINER",
        "CLOUDINARY_CLOUD_NAME",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
        "CLOUDINARY_FOLDER",
        "ADMIN_PASSWORD",
    ):
        try:
            if key in secrets and key not in os.environ:
                os.environ[key] = str(secrets[key])
        except Exception:
            continue


def _admin_password() -> str:
    return os.getenv("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)


# --- Validation helpers ------------------------------------------------------

def validate_member(identifier: str) -> tuple[bool, str]:
    """Validate an adiClub identifier (non-empty ID, or well-formed email)."""

    identifier = (identifier or "").strip()
    if not identifier:
        return False, "Ingresa tu ID de adiClub o tu email para continuar."
    if "@" in identifier and not EMAIL_RE.match(identifier):
        return False, "El email no tiene un formato válido."
    return True, ""


def classify_media(extension: str) -> str | None:
    """Return 'image' or 'video' for a known extension, else ``None``."""

    ext = extension.lower().lstrip(".")
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def validate_file(filename: str, size_bytes: int) -> tuple[bool, str, str | None]:
    """Validate file type and size. Returns (ok, message, media_type)."""

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_type = classify_media(ext)
    if media_type is None:
        allowed = ", ".join(sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))
        return False, f"Tipo de archivo no permitido. Usa: {allowed}.", None

    limit = MAX_IMAGE_BYTES if media_type == "image" else MAX_VIDEO_BYTES
    if size_bytes > limit:
        limit_mb = limit // (1024 * 1024)
        kind = "imágenes" if media_type == "image" else "videos"
        return (
            False,
            f"El archivo supera el tamaño máximo para {kind} ({limit_mb} MB).",
            media_type,
        )
    return True, "", media_type


# --- App ---------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="adiClub — Sube tu contenido", page_icon="👟")

    _load_secrets_into_env()

    if "member" not in st.session_state:
        st.session_state.member = None
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    backend = get_storage_backend()

    st.sidebar.markdown("### Navegación")
    page = st.sidebar.radio(
        "Sección",
        ["Subir contenido", "Galería (admin)"],
        label_visibility="collapsed",
    )
    st.sidebar.markdown("### Almacenamiento")
    st.sidebar.info(backend.name())

    if page == "Galería (admin)":
        _render_gallery(backend)
    else:
        _render_upload_page(backend)


def _render_upload_page(backend) -> None:
    st.title("👟 adiClub — Comparte tu contenido")
    st.caption(
        "Sube una foto o un video como miembro de adiClub. "
        "Formatos: imágenes (jpg, jpeg, png, webp, gif) o videos (mp4, mov, webm). "
        "Límite: imágenes hasta 10 MB y videos hasta 30 MB."
    )
    st.info(
        "Solo se permite un archivo por persona, de preferencia una foto. "
        "El contenido será de uso interno de adidas y no será compartido con terceros."
    )

    _render_identification()

    if not st.session_state.member:
        st.warning("Identifícate para habilitar la subida de archivos.")
        return

    st.success(f"Identificado como: **{st.session_state.member}**")
    _render_upload(backend)


def _render_identification() -> None:
    st.subheader("1. Identifícate")

    if st.session_state.member:
        if st.button("Cambiar de miembro"):
            st.session_state.member = None
            st.rerun()
        return

    with st.form("identify_form"):
        identifier = st.text_input(
            "ID de adiClub o email",
            placeholder="p. ej. 123456 o nombre@correo.com",
        )
        submitted = st.form_submit_button("Continuar")

    if submitted:
        ok, message = validate_member(identifier)
        if ok:
            st.session_state.member = identifier.strip()
            st.rerun()
        else:
            st.error(message)


def _render_upload(backend) -> None:
    st.subheader("2. Sube tu foto o video")

    uploaded = st.file_uploader(
        "Selecciona un archivo",
        type=sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS),
        accept_multiple_files=False,
    )

    if uploaded is None:
        return

    data = uploaded.getvalue()
    ok, message, media_type = validate_file(uploaded.name, len(data))
    if not ok:
        st.error(message)
        return

    if st.button("Subir archivo", type="primary"):
        stored_filename = build_stored_filename(uploaded.name)
        metadata = UploadMetadata.create(
            member=st.session_state.member,
            original_filename=uploaded.name,
            stored_filename=stored_filename,
            content_type=uploaded.type or "",
            media_type=media_type,
            size_bytes=len(data),
        )
        try:
            reference = backend.save(data, stored_filename, metadata)
        except Exception as exc:  # noqa: BLE001 - surface storage errors to the user
            st.error(f"No se pudo guardar el archivo: {exc}")
            return

        st.success("¡Archivo subido con éxito! 🎉")
        st.caption(f"Guardado como `{stored_filename}` en {reference}")

        if media_type == "image":
            st.image(data, caption=uploaded.name, use_container_width=True)
        else:
            st.video(data)


def _render_gallery(backend) -> None:
    st.title("🔒 Galería (solo admin)")

    if not st.session_state.is_admin:
        st.caption("Esta sección es privada. Ingresa la contraseña de administrador.")
        with st.form("admin_login"):
            password = st.text_input("Contraseña de administrador", type="password")
            submitted = st.form_submit_button("Entrar")
        if submitted:
            if password == _admin_password():
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta.")
        return

    col_a, col_b = st.columns([3, 1])
    col_a.caption("Contenido subido por los miembros de adiClub.")
    if col_b.button("Cerrar sesión admin"):
        st.session_state.is_admin = False
        st.rerun()

    uploads = backend.list_uploads()
    if not uploads:
        st.info("Todavía no hay contenido subido.")
        return

    st.write(f"**{len(uploads)}** archivo(s) subido(s).")

    for item in uploads:
        with st.container(border=True):
            st.markdown(
                f"**{item.member}** · {item.media_type} · "
                f"{item.size_bytes / 1024:.0f} KB · {item.timestamp}"
            )
            st.caption(f"Original: {item.original_filename} — guardado: {item.stored_filename}")
            if item.storage_url:
                if item.media_type == "image":
                    st.image(item.storage_url, use_container_width=True)
                else:
                    st.video(item.storage_url)
                st.link_button("Abrir archivo", item.storage_url)
            else:
                data = backend.get(item.stored_filename)
                if data is None:
                    st.warning("Archivo no encontrado en el almacenamiento.")
                    continue
                if item.media_type == "image":
                    st.image(data, use_container_width=True)
                else:
                    st.video(data)
                st.download_button(
                    "Descargar",
                    data=data,
                    file_name=item.original_filename,
                    key=f"dl_{item.stored_filename}",
                )


if __name__ == "__main__":
    main()
