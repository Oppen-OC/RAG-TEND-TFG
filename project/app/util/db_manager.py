import pyodbc
import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()

cnxn_str_base = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    f"SERVER={os.getenv('DB_HOST', 'localhost')};"
    f"DATABASE={os.getenv('DB_NAME', 'TFG')};"
    "Trusted_Connection=yes;"
)

# Construct the absolute path to Strings.json
base_dir = os.path.dirname(os.path.abspath(__file__))
strings_path = os.path.join(base_dir, 'JSON/Strings.json')

with open(strings_path, 'r', encoding='utf-8') as f:
    strings = json.load(f)
    strings_base = strings["dataBase"]

# Configuración del logger específico para db_manager
# Define the logs directory path
logs_dir = os.path.join(base_dir, 'logs')

# Create the logs directory if it doesn't exist
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

# Define the log file path inside the logs directory
log_file_path = os.path.join(logs_dir, 'db_manager.log')

db_logger = logging.getLogger('db_manager')
db_logger.setLevel(logging.INFO)

# Configure the file handler to write logs to the logs directory
db_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')  # Cambia la codificación a utf-8
db_handler.setLevel(logging.INFO)
db_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
db_handler.setFormatter(db_formatter)
db_logger.addHandler(db_handler)

class DBManager:
    def __init__(self, cnxn_str=cnxn_str_base, strings=strings_base):
        
        self.cnxn_str = cnxn_str
        self.strings = strings
        self.cnxn = None
        self.cursor = None

        self.logger = db_logger

    def openConnection(self):
        self.cnxn = pyodbc.connect(self.cnxn_str)
        self.cursor = self.cnxn.cursor()
        self.logger.info("Conectado a la base de datos exitosamente.")

    def ensure_connection(self):
        if self.cnxn is None or self.cursor is None:
            self.openConnection()

    def closeConnection(self):
        self.cursor.close()
        self.cnxn.close()
        self.logger.info("Desconexión a la base de datos completada.")

    def insertDb(self, table, values):
        query = None  # <-- Añade esto
        if not all(value is not None for value in values):
            self.logger.error(f"Invalid data: {values}")
            return

        try:
            query = f"INSERT INTO {table} {self.strings[table]} {self.strings[table + 'V']}"
            self.cursor.execute(query, values)
            self.cnxn.commit()
            self.logger.info(f"Se ha insertado correctamente los valores en la tabla {table}.")

        except Exception as e:
            self.logger.error(f"Error inserting values into table {table}: {e}")
            self.logger.error(f"Query: {query}")
            self.logger.error(f"Values: {values}")

    def deleteObject(self, table, pk_name, pk_value):
        sql = f"DELETE FROM {table} WHERE {pk_name} = ?"
        try:
            self.cursor.execute(sql, (pk_value,))
            self.cnxn.commit()
            self.logger.info(f"Eliminado correctamente el elemento {pk_value} de la tabla {table}.")
        except pyodbc.Error as e:
            self.logger.error(f"Error al eliminar el elemento {pk_value} de la tabla {table}: {e}")

    def viewTable(self, table):
        query = f"SELECT * FROM {table}"
        self.cursor.execute(query)
        try:
            rows = self.cursor.fetchall()
            self.logger.info(f"{len(rows)} Elementos recuperados:")
            self.logger.info(f"Consulta exitosa, fin de la tabla {table}.")
            return rows  # Devuelve los datos obtenidos
        except pyodbc.Error as e:
            self.logger.error(f"Error al consultar la tabla {table}: {e}")
            return None  # Devuelve None en caso de error

    def getFullTable(self, table_name):
        """
        Devuelve todos los registros de una tabla.
        :param table_name: Nombre de la tabla.
        :return: Lista de registros de la tabla.
        """
        try:
            # Asegurarse de que la conexión esté activa
            self.ensure_connection()

            query = f"SELECT * FROM {table_name}"
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            self.logger.info(f"Se han recuperado {len(rows)} registros de la tabla {table_name}.")
            return rows
        except pyodbc.Error as e:
            self.logger.error(f"Error al obtener los registros de la tabla {table_name}: {e}")
            return []

    def updateObject(self, table, pk_name, pk_value, update_values):
        set_clause = ", ".join([f"{col} = ?" for col in update_values.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {pk_name} = ?"
        try:
            self.cursor.execute(sql, (*update_values.values(), pk_value))
            if self.cursor.rowcount == 0:
                self.logger.error(f"No se encontró el elemento {pk_value} en la tabla {table}.")
            else:
                self.cnxn.commit()
                self.logger.info(f"Actualizado correctamente el elemento {pk_value} de la tabla {table}.")
        except pyodbc.Error as e:
            self.logger.error(f"Error al actualizar el elemento {pk_value} de la tabla {table}: {e}")

    def searchTable(self, table, search_criteria) -> list:
        where_clause = " AND ".join([f"{col} = ?" for col in search_criteria.keys()])
        sql = f"SELECT * FROM {table} WHERE {where_clause}"
        try:
            self.cursor.execute(sql, tuple(search_criteria.values()))
            rows = self.cursor.fetchall()[0]
            self.logger.info(f"Resultados de la búsqueda en la tabla {table}: {rows}")
            #for cont, row in enumerate(rows):
                # self.logger.info(f"{cont}- {row}")
            return list(rows)
        except pyodbc.Error as e:
            self.logger.error(f"Error al buscar en la tabla {table}: {e}")
            return []
        
        except Exception as e:
            self.logger.warning(f"No se encontraron resultados en la tabla {table} para los criterios: {search_criteria}")
            return []

    def searchAllTable(self, table, search_criteria, columns="*") -> list:
        where_clause = " AND ".join([f"{col} = ?" for col in search_criteria.keys()])
        sql = f"SELECT {columns} FROM {table} WHERE {where_clause}"
        try:
            self.cursor.execute(sql, tuple(search_criteria.values()))
            rows = self.cursor.fetchall()
            self.logger.info(f"Resultados de la búsqueda en la tabla {table}: {rows}")
            return [list(row) for row in rows]
        except pyodbc.Error as e:
            self.logger.error(f"Error al buscar en la tabla {table}: {e}")
            return []
        except Exception as e:
            self.logger.warning(f"No se encontraron resultados en la tabla {table} para los criterios: {search_criteria}")
            return []

    def insertNewUpdate(self):
        try:
            # Buscar el valor máximo de la columna
            query_max = f"SELECT MAX(id) FROM actualizaciones"
            self.cursor.execute(query_max)
            max_value = self.cursor.fetchone()[0]

            # Calcular el nuevo valor de la clave primaria
            new_pk = max_value + 1 if max_value is not None else 1

            # Obtener la fecha y hora actual
            from datetime import datetime
            current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Insertar el nuevo registro
            query_insert = f"INSERT INTO actualizaciones (id, fecha_actualizacion) VALUES (?, ?)"
            self.cursor.execute(query_insert, (new_pk, current_datetime))
            self.cnxn.commit()

            self.logger.info(f"Nuevo registro insertado en actualizaciones: id={new_pk}, fecha_actualizacion={current_datetime}")
            return new_pk, current_datetime

        except Exception as e:
            self.logger.error(f"Error al insertar un nuevo registro en actualizaciones: {e}")
            return None, None

    def complement_of_intersection(self, table1, table2, pk_column="COD"):
        sql = f"""
            SELECT {table1}.{pk_column} FROM {table1}
            LEFT JOIN {table2}
            ON TRIM(UPPER({table1}.{pk_column})) = TRIM(UPPER({table2}.{pk_column}))
            WHERE {table2}.{pk_column} IS NULL
        """
        try:
            self.cursor.execute(sql)
            rows = self.cursor.fetchall()
            self.logger.info(f"Complemento de la intersección entre las PK de {table1} y {table2}: {rows}")
            return [row[0] for row in rows]
        except Exception as e:
            self.logger.error(f"Error al obtener el complemento de la intersección entre las PK de {table1} y {table2}: {e}")
            return []
