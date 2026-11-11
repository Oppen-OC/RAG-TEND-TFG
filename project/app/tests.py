"""Tests de seguridad de las vistas. No necesitan SQL Server:

    DB_ENGINE=sqlite DISABLE_PERIODIC=1 python project/manage.py test app

DBManager (pyodbc contra SQL Server) se sustituye por un mock en todas las pruebas.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

# Vistas que modifican datos o lanzan procesos (todas son POST)
ENDPOINTS_POST = [
    "update_database",
    "cargar_anexo",
    "get_anexoI_data",
    "crear_alerta",
    "eliminar_alerta",
    "guardar_anexo",
    "quitar_guardada",
    "actualizar_usuario",
    "cambiar_password",
]

PASSWORD = "Clave-antigua-123"
NUEVA = "Clave-nueva-456"


@patch("app.views.DBManager")
class SeguridadVistasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ana", "ana@example.com", PASSWORD)

    def test_anonimo_redirige_al_login(self, db):
        for name in ENDPOINTS_POST:
            with self.subTest(name):
                r = self.client.post(reverse(f"app:{name}"))
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r["Location"].startswith("/?next="))
        db.assert_not_called()

    def test_post_sin_token_csrf_da_403(self, db):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name in ENDPOINTS_POST:
            with self.subTest(name):
                self.assertEqual(client.post(reverse(f"app:{name}")).status_code, 403)
        db.assert_not_called()

    def test_eliminar_alerta_usa_el_usuario_de_la_sesion(self, db):
        cursor = db.return_value.cursor
        cursor.rowcount = 1
        self.client.force_login(self.user)

        r = self.client.post(reverse("app:eliminar_alerta"), {"id": "7", "user": "otro"})

        self.assertEqual(r.status_code, 200)
        sql, params = cursor.execute.call_args.args
        self.assertIn("[user] = ?", sql)
        self.assertEqual(params, (7, "ana"))

    def test_eliminar_alerta_ajena_da_404(self, db):
        db.return_value.cursor.rowcount = 0
        self.client.force_login(self.user)
        r = self.client.post(reverse("app:eliminar_alerta"), {"id": "7"})
        self.assertEqual(r.status_code, 404)

    def test_quitar_guardada_no_borra_datos_globales(self, db):
        cursor = db.return_value.cursor
        cursor.rowcount = 1
        self.client.force_login(self.user)

        r = self.client.post(
            reverse("app:quitar_guardada"),
            data='{"cod_licitacion": "X/1", "user": "otro"}',
            content_type="application/json",
        )

        self.assertEqual(r.status_code, 200)
        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args.args
        self.assertIn("DELETE FROM anexos_guardados", sql)
        self.assertEqual(params, ("X/1", "ana"))
        db.return_value.deleteObject.assert_not_called()

    def test_cambiar_password_guarda_hash(self, db):
        self.client.force_login(self.user)

        r = self.client.post(reverse("app:cambiar_password"), {
            "old_password": PASSWORD, "new_password1": NUEVA, "new_password2": NUEVA,
        })

        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NUEVA))
        self.assertTrue(self.user.password.startswith("pbkdf2_"))
        # update_session_auth_hash: la sesión sigue siendo válida
        self.assertEqual(self.client.get(reverse("app:user_settings")).status_code, 200)

    def test_cambiar_password_sin_la_actual_falla(self, db):
        self.client.force_login(self.user)

        r = self.client.post(reverse("app:cambiar_password"), {
            "old_password": "incorrecta", "new_password1": NUEVA, "new_password2": NUEVA,
        })

        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_user_settings_no_expone_el_hash(self, db):
        self.client.force_login(self.user)
        r = self.client.get(reverse("app:user_settings"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, self.user.password)
        self.assertNotContains(r, "pbkdf2_")

    def test_actualizar_usuario_reasigna_sus_datos(self, db):
        self.client.force_login(self.user)

        r = self.client.post(reverse("app:actualizar_usuario"), {"username": "ana2", "email": "ana2@example.com"})

        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual((self.user.username, self.user.email), ("ana2", "ana2@example.com"))
        for call in db.return_value.cursor.execute.call_args_list:
            self.assertEqual(call.args[1], ("ana2", "ana"))
        self.assertEqual(db.return_value.cursor.execute.call_count, 2)

    def test_actualizar_usuario_con_username_existente_falla(self, db):
        User.objects.create_user("luis", "luis@example.com", PASSWORD)
        self.client.force_login(self.user)

        r = self.client.post(reverse("app:actualizar_usuario"), {"username": "luis", "email": "ana@example.com"})

        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "ana")
        db.assert_not_called()
