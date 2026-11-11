import os
import sys

from django.apps import AppConfig

class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'  # Este nombre debe coincidir con el nombre de la carpeta de la aplicación

    def ready(self):
        # El hilo de scraping + emails no debe arrancar en tests ni cuando se desactiva a mano
        if os.getenv("DISABLE_PERIODIC") == "1" or "test" in sys.argv:
            return
        from .periodic import start_periodic_task
        start_periodic_task()
