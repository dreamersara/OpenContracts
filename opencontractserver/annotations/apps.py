from django.apps import AppConfig
from django.db.models.signals import post_save, post_delete
from django.utils.translation import gettext_lazy as _


class AnnotationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "opencontractserver.annotations"
    verbose_name = _("Annotations")

    def ready(self):
        try:
            import opencontractserver.annotations.signals  # noqa F401
            from opencontractserver.annotations.models import Annotation, Note
            from opencontractserver.annotations.signals import (
                ANNOT_CREATE_UID,
                NOTE_CREATE_UID,
                ANNOT_REFRESH_VIEW_UID,
                process_annot_on_create_atomic,
                process_note_on_create_atomic,
                trigger_view_refresh,
            )

            post_save.connect(
                process_annot_on_create_atomic,
                sender=Annotation,
                dispatch_uid=ANNOT_CREATE_UID,
            )
            post_save.connect(
                process_note_on_create_atomic,
                sender=Note,
                dispatch_uid=NOTE_CREATE_UID,
            )
            # Connect view refresh signal for annotations
            post_save.connect(
                trigger_view_refresh,
                sender=Annotation,
                dispatch_uid=f"{ANNOT_REFRESH_VIEW_UID}_save",
            )
            post_delete.connect(
                trigger_view_refresh,
                sender=Annotation,
                dispatch_uid=f"{ANNOT_REFRESH_VIEW_UID}_delete",
            )
        except ImportError:
            pass
