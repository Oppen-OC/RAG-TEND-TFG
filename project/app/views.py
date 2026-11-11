from app.util.db_manager import DBManager
from django.http import Http404, JsonResponse
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.views.decorators.http import require_POST
import json
import logging
import datetime
from django.shortcuts import render, redirect
from .forms import CustomUserCreationForm, UserSettingsForm
from django.contrib.auth.decorators import login_required

logger = logging.getLogger(__name__)

# Columnas de las tablas AnexoI y anexoI_fuentes, en orden
CAMPOS_ANEXO = [
    "COD", "Regulacion_armonizada", "Sometido_recurso_especial", "Plazo_ejecución", "Presupuesto_sinIVA",
    "Presupuesto_conIVA", "Importe_IVA", "Sistema_Retribucion", "Valor_estimado", "Revision_precios",
    "Garantia_definitiva", "Garantia_provisional", "Admisibilidad_variantes", "Clasificacion", "Grupo",
    "Subgrupo", "Categoria", "Criterio_Solvencia_economica", "Criterio_Solvencia_tecnica",
    "Condiciones_especiales", "Penalidad_incumplimiento", "Forma_pago", "Causas_modificacion",
    "Plazo_garantia", "Contratacion_precio_unit", "Tanto_alzado", "Tanto_alzado_con", "Criterio_juicio_val",
    "Evaluables_autom", "Criterio_ecónomico", "Obligaciones_ambientales", "Regimen_penalidades", "Ambiental",
    "Tecnico", "Precio", "Garantia", "Experiencia", "Calidad", "Social", "Seguridad", "Juicio_valor",
    "Formula_precio", "Formula_JuicioValor", "Criterios_valores_anormales", "Infraccion_grave",
    "Gastos_desistimiento", "Contratacion_control", "Tareas_criticas",
]


def _error_interno(mensaje):
    # La traza completa queda en el log del servidor; al cliente solo le llega un mensaje genérico
    logger.exception(mensaje)
    return JsonResponse({'success': False, 'error': 'Error interno'}, status=500)


def _json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}

@login_required
def licitaciones_view(request):
    db = DBManager()
    db.openConnection()
    data = db.viewTable("Licitaciones")

    # Procesar los datos para que coincidan con el formato esperado
    licitaciones = [
        {
            'COD': row[0],
            'ID_Publicacion_TED': row[1],
            'Organo_Contratacion': row[2],
            'ID_Organo_Contratacion': row[3],
            'Estado_Licitacion': row[4],
            'Objeto_Contrato': row[5],
            'Financiacion_UE': row[6],
            'Presupuesto_Base': row[7],
            'Valor_Estimado_Contrato': row[8],
            'Tipo_Contrato': row[9],
            'Codigo_CPV': row[10],
            'Lugar_Ejecucion': row[11],
            'Sistema_Contratacion': row[12],
            'Procedimiento_Contratacion': row[13],
            'Tipo_Tramitacion': row[14],
            'Metodo_Presentacion_Oferta': row[15],
            'Resultado': row[16],
            'Adjudicatario': row[17],
            'Numero_Licitaciones_Presentadas': row[18],
            'Importe_Adjudicacion': row[19],
            'Fecha_Adjudicacion': row[20],
            'Fecha_Formalizacion': row[21],
            'Fecha_Desistimiento': row[22],
            'Fecha_Presentacion_Oferta': row[23],
            'Fecha_Presentacion_Solicitud': row[24],
            "URL_Original": db.searchTable("Codigos", {"COD": row[0]})[1] if db.searchTable("Codigos", {"COD": row[0]}) else ""
        }
        for row in data
    ]

    num_licitaciones = len(licitaciones)

    total_euros = 0.0
    for price in data:
        # Convertir el precio a un número y sumarlo al total
        try:
            price = float(price[7].replace("€", "").replace(".", "").replace(",", ".").replace(" Euros", ""))
            total_euros += price
        except ValueError:
            continue

    total_euros = "{:,.2f}".format(total_euros).replace(",", "X").replace(".", ",").replace("X", ".")
    rows = db.getFullTable("actualizaciones")
    last_update = max(rows, key=lambda x: x[0])[1]

    # Procesar los datos de AnexoI
    for licitacion in licitaciones:
        cod = licitacion["COD"]
        data = db.searchTable("AnexoI", {"COD": cod})
        Modificado = db.searchTable("Documentos", {"COD": cod})[6] if db.searchTable("Documentos", {"COD": cod}) else ""
        valores = data[1:] if data else [""] * (len(CAMPOS_ANEXO) - 1)
        licitacion.update(zip(CAMPOS_ANEXO[1:], valores), Modificado=Modificado)

    db.closeConnection()

    # Renderizar la plantilla y pasar los datos al contexto
    return render(request, 'licitaciones.html', {
        'licitaciones': licitaciones,
        'num_licitaciones': num_licitaciones,
        'total_euros': total_euros,
        "last_update": invertir_dia_mes(last_update),
    })

def invertir_dia_mes(fecha):
    if isinstance(fecha, datetime.datetime):
        # Convertir el objeto datetime a una cadena en formato "YYYY-MM-DD HH:MM:SS"
        fecha = fecha.strftime("%Y-%m-%d %H:%M:%S")
    
    fecha_partes = fecha.split(" ")
    fecha_solo = fecha_partes[0]
    anio, mes, dia = fecha_solo.split("-")
    nueva_fecha = f"{anio}-{dia}-{mes}"
    if len(fecha_partes) > 1:
        nueva_fecha += f" {fecha_partes[1]}"

    return nueva_fecha

@login_required
def user_settings(request):
    context = {
        'username': request.user.username,
        'email': request.user.email,
    }
    return render(request, 'user_settings.html', context)


@login_required
@require_POST
def actualizar_usuario(request):
    # Solo nombre de usuario y email; la contraseña se cambia en cambiar_password
    username_anterior = request.user.username
    form = UserSettingsForm(request.POST, instance=request.user)
    if not form.is_valid():
        return JsonResponse({'success': False, 'error': form.errors.get_json_data()}, status=400)

    try:
        with transaction.atomic():
            user = form.save()
            if user.username != username_anterior:
                # alertas y anexos_guardados guardan el username: se reasignan para no perderlos
                # ni dejárselos a quien se registre después con el nombre antiguo
                db = DBManager()
                db.openConnection()
                try:
                    for tabla in ("alertas", "anexos_guardados"):
                        db.cursor.execute(
                            f"UPDATE {tabla} SET [user] = ? WHERE [user] = ?",
                            (user.username, username_anterior),
                        )
                    db.cnxn.commit()
                finally:
                    db.closeConnection()
    except Exception:
        return _error_interno("Error al actualizar el usuario")
    return JsonResponse({'success': True})


@login_required
@require_POST
def cambiar_password(request):
    form = PasswordChangeForm(request.user, request.POST)
    if not form.is_valid():
        return JsonResponse({'success': False, 'error': form.errors.get_json_data()}, status=400)
    form.save()
    update_session_auth_hash(request, form.user)
    return JsonResponse({'success': True})

@login_required
def detalles_licitacion(request, cod):
    db = DBManager()
    db.openConnection()

    # Obtener los datos de la licitación
    data = db.searchTable("Licitaciones", {"COD": cod})

    # Verificar si se encontró la licitación
    if not data:
        db.closeConnection()
        raise Http404("Licitación no encontrada")

    documentos = db.searchTable("Documentos", {"COD": cod})

    licitacion = {
        'COD': data[0],
        'ID_publicacion_TED': data[1],
        'Organo_Contratacion': data[2],
        'ID_Organo_contratacion': data[3],
        'Estado_Licitacion': data[4],
        'Objeto_contrato': data[5],
        'Financiacion_UE': data[6],
        'Presupuesto_base': data[7],
        'Valor_Estimado_Contrato': data[8],
        'Tipo_contrato': data[9],
        'Codigo_CPV': data[10],
        'Lugar_ejecucion': data[11],
        'Sistema_contratacion': data[12],
        'Procedimiento_contratacion': data[13],
        'Tipo_contratacion': data[14],
        'Metodo_presentacion_oferta': data[15],
        'Resultado': data[16],
        'Adjudicatario': data[17],
        'Numero_licitaciones_presentadas': data[18],
        'Importe_adjudicacion': data[19],
        'Fecha_Adjudicacion': data[20],
        'Fecha_Formalizacion': data[21],
        'Fecha_Desistimiento': data[22],
        'Fecha_Presentacion_Oferta': data[23],
        'Fecha_Presentacion_Solicitud': data[24],
        "Modificado": documentos[6] if documentos else ""
    }

    # Obtener los documentos relacionados desde la tabla "Documentos"
    data1 = db.searchTable("Anexoi_fuentes", {"COD": cod})
    url_original = db.searchTable("Codigos", {"COD": cod})[1] if db.searchTable("Codigos", {"COD": cod}) else ""

    # --- NUEVO: Comprobar si el anexo ya está guardado para el usuario ---
    user = request.user.username
    existe = db.searchTable("anexos_guardados", {"[user]": user, "cod_licitacion": cod})
    anexo_guardado = bool(existe)
    # ---------------------------------------------------------------------

    db.closeConnection()

    anexoI_fuentes = dict(zip(CAMPOS_ANEXO, data1)) if data1 else dict.fromkeys(CAMPOS_ANEXO, "")

    pliego_administrativo_url = documentos[2] if documentos else ""
    anexo_url = documentos[1] if documentos else ""
    titulo_anexo = documentos[3] if documentos else ""

    contexto = {
        'licitacion': licitacion,
        'pliego_administrativo_url': pliego_administrativo_url,
        'anexo_url': anexo_url,
        'titulo_anexo': titulo_anexo,
        'pliego_original_url': url_original,
        'anexoI_fuentes': anexoI_fuentes,
        'anexo_guardado': anexo_guardado,  # <-- Esto controla el botón en el template
    }

    return render(request, 'detalles_licitacion.html', contexto)


@login_required
def alertas(request):
    db = DBManager()
    db.openConnection()
    user = request.user.username
    data = db.searchAllTable("alertas", {"[user]": user})
    db.closeConnection()

    alertas = []
    for row in data:
        try:
            condiciones = json.loads(row[4]) if row[4] else []
        except Exception:
            condiciones = []
        alerta = {
            'id': row[0],
            '[user]': row[1],
            'nombre': row[2],
            'activo': row[3],
            'condiciones': condiciones,
        }
        alertas.append(alerta)

    return render(request, 'alertas.html', {'alertas': alertas})

@login_required
def ajustar_filtro(request, filtro_id):
    if request.method == 'POST':
        # Obtén los datos del formulario
        nombre = request.POST.get('nombre')
        frecuencia = request.POST.get('frecuencia')
        activo = request.POST.get('activo') == 'on'

        # Aquí puedes actualizar la base de datos con los nuevos valores
        # Por ejemplo:
        # alerta = Alerta.objects.get(id=filtro_id)
        # alerta.nombre = nombre
        # alerta.frecuencia = frecuencia
        # alerta.activo = activo
        # alerta.save()

        # Responde con los datos actualizados
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'id': filtro_id,
                'nombre': nombre,
                'frecuencia': frecuencia,
                'activo': activo,
            })

    # Si no es una solicitud AJAX, redirige a la lista de alertas
    return redirect('app:alertas')

@login_required
def mis_licitaciones(request):
    db = DBManager()
    db.openConnection()
    user = request.user.username

    # 1. Busca los códigos de licitaciones guardados por el usuario en anexos_guardados
    guardadas = db.searchAllTable("anexos_guardados", {"[user]": user})
    codigos = [row[1] for row in guardadas]  # row[1] es cod_licitacion

    licitaciones = []
    if codigos:
        # 2. Busca los datos de cada licitación guardada
        for cod in codigos:
            data = db.searchTable("Licitaciones", {"COD": cod})
            if data:
                licitaciones.append({
                    'COD': data[0],
                    'ID_Publicacion_TED': data[1],
                    'Organo_Contratacion': data[2],
                    'ID_Organo_Contratacion': data[3],
                    'Estado_Licitacion': data[4],
                    'Objeto_Contrato': data[5],
                    'Financiacion_UE': data[6],
                    'Presupuesto_Base_Licitacion': data[7],
                    'Valor_Estimado_Contrato': data[8],
                    'Tipo_Contrato': data[9],
                    'Codigo_CPV': data[10],
                    'Lugar_Ejecucion': data[11],
                    'Sistema_Contratacion': data[12],
                    'Procedimiento_Contratacion': data[13],
                    'Tipo_Tramitacion': data[14],
                    'Metodo_Presentacion_Oferta': data[15],
                    'Resultado': data[16],
                    'Adjudicatario': data[17],
                    'Num_Licitadores_Presentados': data[18],
                    'Importe_Adjudicacion': data[19],
                })
    db.closeConnection()

    return render(request, 'mis_licitaciones.html', {
        'licitaciones': licitaciones,
        'num_licitaciones': len(licitaciones),
    })

@login_required
@require_POST
def update_database(request):
    try:
        # Llama a la función `update` en scrapper.py
        from app.util.scrapper import update
        update()
    except Exception:
        return _error_interno("Error al actualizar las licitaciones")
    return JsonResponse({'success': True, 'message': 'Licitaciones actualizadas correctamente.'})


@login_required
@require_POST
def cargar_anexo(request):
    cod = _json_body(request).get('cod')
    if not cod:
        return JsonResponse({'error': 'Código no proporcionado'}, status=400)

    try:
        db = DBManager()
        db.openConnection()
        try:
            data = db.searchTable("AnexoI", {"COD": cod})
            data1 = db.searchTable("anexoI_fuentes", {"COD": cod})
            documentos = db.searchTable("Documentos", {"COD": cod})[6]

            if data == []:
                # Carga el anexo I a la base de datos
                from app.util.main import main as util_main
                util_main(cod)
                data = db.searchTable("AnexoI", {"COD": cod})
                data1 = db.searchTable("anexoI_fuentes", {"COD": cod})
        finally:
            db.closeConnection()

        if not data:
            return JsonResponse({'error': 'Licitación no encontrada'}, status=404)

        anexoI = dict(zip(CAMPOS_ANEXO, data), Modificado=documentos)
        anexoI_fuentes = dict(zip(CAMPOS_ANEXO, data1), Modificado=documentos)
    except Exception:
        return _error_interno("Error al cargar el anexo")

    return JsonResponse({'anexoI': anexoI, 'anexoI_fuentes': anexoI_fuentes})


@login_required
@require_POST
def get_anexoI_data(request):
    cod_list = _json_body(request).get('cod_list', [])
    if not cod_list:
        return JsonResponse({'error': 'No se proporcionó una lista de códigos'}, status=400)

    try:
        db = DBManager()
        db.openConnection()
        try:
            data = []
            for cod in cod_list:
                row = db.searchTable("anexoI", {"COD": cod})  # una fila (lista de columnas) o []
                if row:
                    column_names = [col[0] for col in db.cursor.description]
                    data.append(dict(zip(column_names, row)))
        finally:
            db.closeConnection()
    except Exception:
        return _error_interno("Error al obtener los datos de anexoI")

    if not data:
        return JsonResponse({'error': 'No se encontraron datos para los códigos proporcionados'}, status=404)
    return JsonResponse(data, safe=False)


@login_required
@require_POST
def crear_alerta(request):
    nombre = request.POST.get('nombre_alerta')
    condiciones = request.POST.get('condiciones')
    if not nombre or not condiciones:
        return JsonResponse({'success': False, 'error': 'Datos incompletos'}, status=400)

    try:
        condiciones_json = json.loads(condiciones)
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Condiciones mal formateadas'}, status=400)

    try:
        db = DBManager()
        db.openConnection()
        try:
            # INSERT directo: insertDb se traga los errores y la vista respondería éxito sin guardar
            db.cursor.execute(
                "INSERT INTO alertas ([user], nombre, activo, condiciones) VALUES (?, ?, ?, ?)",
                (request.user.username, nombre, 1, json.dumps(condiciones_json)),
            )
            db.cnxn.commit()
        finally:
            db.closeConnection()
    except Exception:
        return _error_interno("Error al guardar la alerta")

    return JsonResponse({
        'success': True,
        'nombre': nombre,
        'activo': True,
        'condiciones': condiciones_json,
    })


@login_required
@require_POST
def eliminar_alerta(request):
    try:
        alerta_id = int(request.POST.get('id', ''))
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Datos incompletos'}, status=400)

    try:
        db = DBManager()
        db.openConnection()
        try:
            # Solo borra la alerta si pertenece al usuario autenticado
            db.cursor.execute(
                "DELETE FROM alertas WHERE id = ? AND [user] = ?",
                (alerta_id, request.user.username),
            )
            borradas = db.cursor.rowcount
            db.cnxn.commit()
        finally:
            db.closeConnection()
    except Exception:
        return _error_interno("Error al eliminar la alerta")

    if borradas == 0:
        return JsonResponse({'success': False, 'error': 'Alerta no encontrada'}, status=404)
    return JsonResponse({'success': True})


@login_required
@require_POST
def guardar_anexo(request):
    cod_licitacion = request.POST.get('cod_licitacion')
    if not cod_licitacion:
        return JsonResponse({'success': False, 'error': 'Datos incompletos'}, status=400)

    try:
        db = DBManager()
        db.openConnection()
        try:
            # INSERT directo: insertDb se traga los errores y la vista respondería éxito sin guardar
            db.cursor.execute(
                "INSERT INTO anexos_guardados (cod_licitacion, [user]) VALUES (?, ?)",
                (cod_licitacion, request.user.username),
            )
            db.cnxn.commit()
        finally:
            db.closeConnection()
    except Exception:
        return _error_interno("Error al guardar el anexo")
    return JsonResponse({'success': True})


@login_required
@require_POST
def quitar_guardada(request):
    # Quita la licitación de "Mis licitaciones" del usuario; no toca los datos globales
    cod_licitacion = _json_body(request).get('cod_licitacion')
    if not cod_licitacion:
        return JsonResponse({'success': False, 'error': 'Código de licitación no proporcionado'}, status=400)

    try:
        db = DBManager()
        db.openConnection()
        try:
            db.cursor.execute(
                "DELETE FROM anexos_guardados WHERE cod_licitacion = ? AND [user] = ?",
                (cod_licitacion, request.user.username),
            )
            borradas = db.cursor.rowcount
            db.cnxn.commit()
        finally:
            db.closeConnection()
    except Exception:
        return _error_interno("Error al quitar la licitación guardada")

    if borradas == 0:
        return JsonResponse({'success': False, 'error': 'Licitación no encontrada en tu lista'}, status=404)
    return JsonResponse({'success': True})


@login_required
def estadisticas(request):
    db = DBManager()
    db.openConnection()
    data = db.viewTable("Licitaciones")
    db.closeConnection()
    # Suponiendo que Estado_Licitacion es la columna 5 (índice 4)
    estados = [row[4] for row in data]
    financiacion = [row[6] for row in data]
    presupuesto = [row[7] for row in data]
    valor_estimado = [row[8] for row in data]
    tipo_contrato = [row[9] for row in data]
    cpv = [row[10] for row in data]
    lugar = [row[11] for row in data]
    procedimiento = [row[13] for row in data]

    contexto = {'estados': estados, 
                'financiacion': financiacion, 
                'presupuesto': presupuesto, 
                'valor_estimado': valor_estimado,
                'tipo_contrato': tipo_contrato,
                'cpv': cpv,
                'lugar': lugar,
                'procedimiento': procedimiento
                }

    return render(request, 'estadisticas.html', contexto)


def register(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'registration/register.html', {'form': form})