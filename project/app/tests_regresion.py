"""Red de regresión: fija el comportamiento actual de las vistas antes del recorte de código muerto.

Estos tests deben pasar ANTES y DESPUÉS de cada tarea del recorte. Si uno falla, el fallo está en el cambio, no en el test.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from app.views import CAMPOS_ANEXO

PASSWORD = "Clave-antigua-123"
LIC = ("X/1",) + tuple(f"lic{i}" for i in range(1, 25))  # 25 columnas de Licitaciones; LIC[7] no es numérico a propósito
ANEXO = ("X/1",) + tuple(f"a{i}" for i in range(1, 48))  # 48 columnas de AnexoI / AnexoI_Fuentes
DOCS = ("X/1", "anexo_url", "pliego_url", "titulo", "d4", "d5", "2025-01-01")  # Documentos; [6] = Modificado


def _search(con_anexo=True):
    def search(table, criteria):
        return {
            "Licitaciones": LIC, "Codigos": ("X/1", "http://orig"), "Documentos": DOCS,
            "AnexoI": ANEXO if con_anexo else [], "anexoI_fuentes": ANEXO if con_anexo else [],
            "Anexoi_fuentes": ANEXO if con_anexo else [], "anexoI": ANEXO if con_anexo else [],
            "anexos_guardados": [],
        }.get(table, [])
    return search


@patch("app.views.DBManager")
class PaginasTests(TestCase):
    """Cada página GET responde 200 con datos realistas."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("ana", "ana@example.com", PASSWORD))

    def _db(self, db, con_anexo=True):
        db.return_value.viewTable.return_value = [LIC]
        db.return_value.searchTable.side_effect = _search(con_anexo)
        db.return_value.getFullTable.return_value = [(1, "2025-06-15 22:37:29")]
        db.return_value.searchAllTable.side_effect = lambda table, criteria, *a: {
            "alertas": [[1, "ana", "Mi alerta", 1, '[{"campo": "Tipo_Contrato", "valor": "Obras"}]']],
            "anexos_guardados": [[1, "X/1", "ana", None]],
        }.get(table, [])

    def test_paginas_responden_200(self, db):
        self._db(db)
        for name, args in [("licitaciones", []), ("detalles_licitacion", ["X/1"]), ("alertas", []),
                           ("mis_licitaciones", []), ("estadisticas", []), ("user_settings", [])]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(f"app:{name}", args=args)).status_code, 200)

    def test_login_y_registro_anonimos_responden_200(self, db):
        self.client.logout()
        for url in (reverse("app:login"), reverse("app:register"), "/accounts/login/"):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_licitaciones_con_anexo_mapea_columnas(self, db):
        self._db(db)
        lic = self.client.get(reverse("app:licitaciones")).context["licitaciones"][0]
        self.assertEqual(lic["COD"], "X/1")
        self.assertEqual(lic["Organo_Contratacion"], "lic2")
        self.assertEqual(lic["URL_Original"], "http://orig")
        self.assertEqual(lic["Regulacion_armonizada"], "a1")
        self.assertEqual(lic["Tareas_criticas"], "a47")
        self.assertEqual(lic["Modificado"], "2025-01-01")

    def test_licitaciones_sin_anexo_rellena_vacios(self, db):
        self._db(db, con_anexo=False)
        lic = self.client.get(reverse("app:licitaciones")).context["licitaciones"][0]
        for campo in CAMPOS_ANEXO[1:]:
            self.assertEqual(lic[campo], "", campo)
        self.assertEqual(lic["COD"], "X/1")

    def test_detalles_con_fuentes_mapea_columnas(self, db):
        self._db(db)
        ctx = self.client.get(reverse("app:detalles_licitacion", args=["X/1"])).context
        self.assertEqual(ctx["anexoI_fuentes"], dict(zip(CAMPOS_ANEXO, ANEXO)))
        self.assertEqual(ctx["licitacion"]["Modificado"], "2025-01-01")
        self.assertEqual((ctx["anexo_url"], ctx["pliego_administrativo_url"]), ("anexo_url", "pliego_url"))

    def test_detalles_sin_fuentes_rellena_vacios(self, db):
        self._db(db, con_anexo=False)
        ctx = self.client.get(reverse("app:detalles_licitacion", args=["X/1"])).context
        self.assertEqual(ctx["anexoI_fuentes"], dict.fromkeys(CAMPOS_ANEXO, ""))


@patch("app.views.DBManager")
class EndpointsJsonTests(TestCase):
    """Forma de las respuestas JSON que consume el frontend."""

    def setUp(self):
        self.client.force_login(User.objects.create_user("ana", "ana@example.com", PASSWORD))

    def test_cargar_anexo_existente_devuelve_campos(self, db):
        db.return_value.searchTable.side_effect = _search()
        # Con el anexo ya en BD no se lanza el pipeline (si lo hiciera, aquí daría 500)
        r = self.client.post(reverse("app:cargar_anexo"), data='{"cod": "X/1"}', content_type="application/json")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body["anexoI"]), set(CAMPOS_ANEXO) | {"Modificado"})
        self.assertEqual(body["anexoI"]["Tareas_criticas"], "a47")
        self.assertEqual(body["anexoI_fuentes"]["Modificado"], "2025-01-01")

    def test_get_anexoI_data_devuelve_lista_de_dicts(self, db):
        db.return_value.searchTable.side_effect = _search()
        db.return_value.cursor.description = [(c,) for c in CAMPOS_ANEXO]
        r = self.client.post(reverse("app:get_anexoI_data"), data='{"cod_list": ["X/1"]}', content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [dict(zip(CAMPOS_ANEXO, ANEXO))])


@patch("app.views.DBManager")
class FrontendLimpioTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("ana", "ana@example.com", PASSWORD))

    def test_ajustar_filtro_ya_no_existe(self, db):
        with self.assertRaises(NoReverseMatch):
            reverse("app:ajustar_filtro", args=[1])

    def test_alertas_renderiza_sin_js_muerto(self, db):
        db.return_value.searchAllTable.return_value = []
        r = self.client.get(reverse("app:alertas"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="formNuevaAlerta"')
        self.assertNotContains(r, "ajax-form")
