"""Red de regresión del pipeline (sin SQL Server, sin red, sin LLM).

Fija el comportamiento actual de DBManager, del scraper, del procesado de documentos y de process_prompt.
Estos tests deben pasar ANTES y DESPUÉS de cada tarea del recorte. Si uno falla, el fallo está en el cambio, no en el test.
"""
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.util import db_manager, document_handler as dh, rag_operations as ro, scrapper as sc
from app.util.db_manager import DBManager


def _pdf(paginas):
    """PDF mínimo (Helvetica, texto ASCII) con una lista de líneas por página."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lineas in paginas:
        flujo = "BT /F1 12 Tf 72 720 Td " + " 0 -16 Td ".join(f"({l}) Tj" for l in lineas) + " ET"
        objs.append(f"<< /Length {len(flujo)} >>\nstream\n{flujo}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


class DBManagerSQLTests(unittest.TestCase):
    def setUp(self):
        p = patch("app.util.db_manager.pyodbc.connect")
        self.connect = p.start()
        self.addCleanup(p.stop)
        self.db = DBManager()
        self.db.openConnection()
        self.cur = self.connect.return_value.cursor.return_value

    def test_insertDb_usa_columnas_de_strings(self):
        self.db.insertDb("alertas", ["ana", "a", 1, "[]"])
        self.assertEqual(self.cur.execute.call_args.args,
                         ("INSERT INTO alertas ([user], nombre, activo, condiciones) VALUES (?, ?, ?, ?)", ["ana", "a", 1, "[]"]))
        self.assertTrue(self.connect.return_value.commit.called)

    def test_insertDb_con_none_no_ejecuta(self):
        self.db.insertDb("alertas", ["ana", None, 1, "[]"])
        self.cur.execute.assert_not_called()

    def test_searchTable_devuelve_una_fila_o_lista_vacia(self):
        self.cur.fetchall.return_value = [("X/1", "a")]
        self.assertEqual(self.db.searchTable("Licitaciones", {"COD": "X/1"}), ["X/1", "a"])
        self.assertEqual(self.cur.execute.call_args.args, ("SELECT * FROM Licitaciones WHERE COD = ?", ("X/1",)))
        self.cur.fetchall.return_value = []
        self.assertEqual(self.db.searchTable("Licitaciones", {"COD": "NO"}), [])

    def test_searchAllTable_devuelve_listas(self):
        self.cur.fetchall.return_value = [("1", "ana"), ("2", "ana")]
        self.assertEqual(self.db.searchAllTable("alertas", {"[user]": "ana"}), [["1", "ana"], ["2", "ana"]])
        self.assertEqual(self.cur.execute.call_args.args, ("SELECT * FROM alertas WHERE [user] = ?", ("ana",)))

    def test_updateObject_y_deleteObject(self):
        self.cur.rowcount = 1
        self.db.updateObject("Codigos", "COD", "X/1", {"DIR_URL": "u"})
        self.assertEqual(self.cur.execute.call_args.args, ("UPDATE Codigos SET DIR_URL = ? WHERE COD = ?", ("u", "X/1")))
        self.db.deleteObject("Licitaciones", "COD", "X/1")
        self.assertEqual(self.cur.execute.call_args.args, ("DELETE FROM Licitaciones WHERE COD = ?", ("X/1",)))

    def test_complement_of_intersection(self):
        self.cur.fetchall.return_value = [("A",), ("B",)]
        self.assertEqual(self.db.complement_of_intersection("Codigos", "Licitaciones"), ["A", "B"])
        sql = self.cur.execute.call_args.args[0]
        self.assertIn("LEFT JOIN Licitaciones", sql)
        self.assertIn("WHERE Licitaciones.COD IS NULL", sql)

    def test_insertNewUpdate_y_lecturas(self):
        self.cur.fetchone.return_value = (4,)
        self.assertEqual(self.db.insertNewUpdate()[0], 5)
        self.assertEqual(self.cur.execute.call_args.args[0], "INSERT INTO actualizaciones (id, fecha_actualizacion) VALUES (?, ?)")
        self.cur.fetchall.return_value = [("r",)]
        self.assertEqual(self.db.viewTable("Licitaciones"), [("r",)])
        self.assertEqual(self.db.getFullTable("actualizaciones"), [("r",)])

    def test_strings_de_tablas_reales_siguen_ahi(self):
        for tabla in ("Licitaciones", "Codigos", "Documentos", "AnexoI", "AnexoI_Fuentes", "alertas", "anexos_guardados"):
            with self.subTest(tabla):
                self.assertIn(tabla, db_manager.strings_base)
                self.assertIn(tabla + "V", db_manager.strings_base)


class ScraperTests(unittest.TestCase):
    def test_filter_detecta_anexo_i(self):
        self.assertEqual([sc.filter(t) for t in ("anexo i del pliego", "anexo i responsable", "annex1.pdf", "pliego tecnico")],
                         [True, False, True, False])

    def test_extraer_fechas(self):
        self.assertEqual(sc.extraer_fechas("Adjudicación: 01/02/2024 Formalización: 03/04/2024"),
                         ["01/02/2024", "03/04/2024", "", "", ""])

    def test_update_ejecuta_las_tres_fases_y_registra_la_actualizacion(self):
        with patch.object(sc, "poblar_db", new=AsyncMock()) as p, patch.object(sc, "scratchUrls", new=AsyncMock()) as u, \
                patch.object(sc, "scratchAnexo", new=AsyncMock()) as a, patch.object(sc, "DBManager") as db:
            sc.update()
        for fase in (p, u, a):
            fase.assert_awaited_once_with()
        db.return_value.insertNewUpdate.assert_called_once_with()


class DocumentHandlerTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(dh.idDocType("pliego.final.pdf"), "pdf")
        self.assertEqual(dh.preprocess_text("Plazo (ver art. 3) ☒ Si □ No\nfin"), "Plazo  [SELECCIONADO] Si \nfin")
        self.assertEqual(dh.section_identifier("A. Objeto\nAPARTADO B\nIV. Otros", "None"), ["None", "A", "B"])

    def test_spliter_trocea_y_solapa_con_la_pagina_siguiente(self):
        siguiente = "COLA" + "y" * 600
        chunks = dh.spliter("x " * 1000, siguiente)
        self.assertEqual(len(chunks), 5)
        self.assertLessEqual(max(map(len, chunks)), 800)
        self.assertTrue(chunks[-1].endswith(siguiente[:400]))

    def test_download_to_json_pdf_produce_chunks_y_secciones(self):
        resp = MagicMock(content=_pdf([["A. Objeto del contrato", "Suministro de material"], ["B. Presupuesto base", "Importe 1000 euros"]]),
                         headers={"Content-Disposition": 'attachment; filename="anexo.pdf"'})
        with patch.object(dh.requests, "get", return_value=resp):
            path = dh.download_to_json("http://example/doc")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([d["page"] for d in data], [1, 2])
        self.assertEqual([d["sections"] for d in data], [["None", "A"], ["A", "B"]])
        self.assertTrue(data[0]["text"].startswith("A. Objeto del contrato"))
        for d in data:
            self.assertTrue(d["chunks"] and all(isinstance(c, str) for c in d["chunks"]))


class ProcessPromptTests(unittest.TestCase):
    def test_process_prompt_usa_el_prompt_original(self):
        rag = MagicMock()
        rag.reformulate_query.side_effect = lambda p: p  # comportamiento real: siempre devolvía el prompt (H9)
        rag.union_top_chunks.return_value = (["c1", "c2"], 0.9, [3, 7])
        rag.generate_response_with_context.return_value = "48 meses"
        rag.format = {"Plazo": "texto"}

        result, response = ro.process_prompt(rag, "Plazo", "Cual es el plazo?")

        self.assertEqual(response, "48 meses")
        rag.union_top_chunks.assert_called_once_with("Cual es el plazo?")
        rag.generate_response_with_context.assert_called_once_with("Cual es el plazo?", ["c1", "c2"])
        self.assertEqual(result.model_dump(), {"prompt_key": "Plazo", "prompt": "Cual es el plazo?", "response": "48 meses",
                                               "score": 0.9, "index": [3, 7], "chunks": ["c1", "c2"], "format": "texto"})
