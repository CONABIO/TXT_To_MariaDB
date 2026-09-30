"""
Cargador de datos eBird -> MariaDB
-----------------------------------
Aplicacion de escritorio (tkinter) para que un usuario sin conocimientos
tecnicos pueda:
  1) Seleccionar un archivo CSV o TXT exportado de eBird.
  2) Revisar las columnas detectadas y elegir el tipo de dato de cada una.
  3) Crear (o reemplazar) la tabla en MariaDB y cargar los datos.

Requisitos (instalar una sola vez, con la terminal abierta donde este Python):
    pip install pymysql

Como generar un .exe para el usuario final (opcional, mas adelante):
    pip install pyinstaller
    pyinstaller --onefile --windowed ebird_loader.py
"""

import csv
import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pymysql
except ImportError:
    pymysql = None

# Tipos de dato disponibles para que el usuario elija por columna.
COLUMNAS = {
  "GLOBAL_UNIQUE_IDENTIFIER": "VARCHAR(255)",
  "LAST_EDITED_DATE": "VARCHAR(255)",
  "TAXONOMIC_ORDER": "VARCHAR(255)",
  "CATEGORY": "VARCHAR(255)",
  "TAXON_CONCEPT_ID": "VARCHAR(255)",
  "COMMON_NAME": "VARCHAR(255)",
  "SCIENTIFIC_NAME": "VARCHAR(255)",
  "SUBSPECIES_COMMON_NAME": "VARCHAR(255)",
  "SUBSPECIES_SCIENTIFIC_NAME": "VARCHAR(255)",
  "EXOTIC_CODE": "VARCHAR(255)",
  "OBSERVATION_COUNT": "VARCHAR(255)",
  "BREEDING_CODE": "VARCHAR(255)",
  "BREEDING_CATEGORY": "VARCHAR(255)",
  "BEHAVIOR_CODE": "VARCHAR(255)",
  "AGE/SEX": "TEXT",
  "COUNTRY": "VARCHAR(255)",
  "COUNTRY_CODE": "VARCHAR(255)",
  "STATE": "VARCHAR(255)",
  "STATE_CODE": "VARCHAR(255)",
  "COUNTY": "VARCHAR(255)",
  "COUNTY_CODE": "VARCHAR(255)",
  "IBA_CODE": "VARCHAR(255)",
  "BCR_CODE": "VARCHAR(255)",
  "USFWS_CODE": "VARCHAR(255)",
  "ATLAS_BLOCK": "VARCHAR(255)",
  "LOCALITY": "VARCHAR(255)",
  "LOCALITY_ID": "VARCHAR(255)",
  "LOCALITY_TYPE": "VARCHAR(255)",
  "LATITUDE": "DOUBLE",
  "LONGITUDE": "DOUBLE",
  "OBSERVATION_DATE": "DATETIME",
  "TIME_OBSERVATIONS_STARTED": "VARCHAR(255)",
  "OBSERVER_ID": "VARCHAR(255)",
  "OBSERVER_ORCID_ID": "TEXT",
  "SAMPLING_EVENT_IDENTIFIER": "VARCHAR(255)",
  "OBSERVATION_TYPE": "VARCHAR(255)",
  "PROTOCOL_NAME": "VARCHAR(255)",
  "PROTOCOL_CODE": "VARCHAR(255)",
  "PROJECT_NAMES": "VARCHAR(255)",
  "PROJECT_IDENTIFIERS": "VARCHAR(255)",
  "DURATION_MINUTES": "VARCHAR(255)",
  "EFFORT_DISTANCE_KM": "VARCHAR(255)",
  "EFFORT_AREA_HA": "VARCHAR(255)",
  "NUMBER_OBSERVERS": "VARCHAR(255)",
  "ALL_SPECIES_REPORTED": "INT",
  "GROUP_IDENTIFIER": "VARCHAR(255)",
  "HAS_MEDIA": "INT",
  "APPROVED": "INT",
  "REVIEWED": "INT",
  "REASON": "VARCHAR(255)",
  "CHECKLIST_COMMENTS": "TEXT",
  "SPECIES_COMMENTS": "TEXT",
}

TIPOS_DISPONIBLES = [
    "VARCHAR(100)",
    "VARCHAR(255)",
    "TEXT",
    "INT",
    "BIGINT",
    "DECIMAL(10,2)",
    "DOUBLE",
    "DATE",
    "DATETIME",
]

DELIMITADORES = {
    "Coma (,)": ",",
    "Punto y coma (;)": ";",
    "Tabulador": "\t",
    "Pipe (|)": "|",
}


def sanitizar_nombre_columna(nombre: str) -> str:
    """Convierte el encabezado del CSV en un nombre de columna SQL valido."""
    nombre = nombre.strip().strip('"').strip("'")
    nombre = re.sub(r"[^0-9a-zA-Z_]", "_", nombre)
    if not nombre:
        nombre = "columna"
    if nombre[0].isdigit():
        nombre = "c_" + nombre
    return nombre


class EbirdLoaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Migrador de datos eBird -> MariaDB")
        self.geometry("780x640")
        self.minsize(700, 560)

        self.ruta_archivo = tk.StringVar()
        self.delimitador_label = tk.StringVar(value="Coma (,)")
        self.nombre_tabla = tk.StringVar(value="ebird_")
        self.reemplazar_tabla = tk.BooleanVar(value=True)

        self.db_host = tk.StringVar(value="172.16.1.81")
        self.db_port = tk.StringVar(value="3306")
        self.db_user = tk.StringVar(value="")
        self.db_pass = tk.StringVar(value="")
        self.db_name = tk.StringVar(value="ebird")

        self.columnas_originales = []   # encabezados tal como vienen en el archivo
        self.filas_columna = []         # lista de dicts: {entry_nombre, combo_tipo}

        self._construir_interfaz()

    # ------------------------------------------------------------------ UI
    def _construir_interfaz(self):
        pad = {"padx": 10, "pady": 6}

        # --- Seccion 1: Archivo ---
        frame_archivo = ttk.LabelFrame(self, text="1. Archivo de datos (CSV o TXT)")
        frame_archivo.pack(fill="x", **pad)

        ttk.Entry(frame_archivo, textvariable=self.ruta_archivo, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(10, 5), pady=8
        )
        ttk.Button(frame_archivo, text="Examinar...", command=self._elegir_archivo).pack(
            side="left", padx=(0, 10), pady=8
        )

        # --- Seccion 2: Delimitador + tabla destino ---
        frame_opciones = ttk.LabelFrame(self, text="2. Opciones")
        frame_opciones.pack(fill="x", **pad)

        ttk.Label(frame_opciones, text="Delimitador:").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.combo_delim = ttk.Combobox(
            frame_opciones, textvariable=self.delimitador_label,
            values=list(DELIMITADORES.keys()), state="readonly", width=18
        )
        self.combo_delim.grid(row=0, column=1, padx=5, pady=6, sticky="w")
        self.combo_delim.bind("<<ComboboxSelected>>", lambda e: self._releer_encabezado())

        ttk.Label(frame_opciones, text="Nombre de la tabla:").grid(row=0, column=2, padx=10, pady=6, sticky="w")
        ttk.Entry(frame_opciones, textvariable=self.nombre_tabla, width=25).grid(
            row=0, column=3, padx=5, pady=6, sticky="w"
        )

        ttk.Checkbutton(
            frame_opciones, text="Reemplazar la tabla si ya existe",
            variable=self.reemplazar_tabla
        ).grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 8), sticky="w")

        # --- Seccion 3: Columnas detectadas ---
        frame_cols = ttk.LabelFrame(self, text="3. Columnas detectadas: elige el tipo de dato")
        frame_cols.pack(fill="both", expand=True, **pad)

        cabecera = ttk.Frame(frame_cols)
        cabecera.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(cabecera, text="Columna en el archivo", width=28, font=("", 9, "bold")).grid(row=0, column=0)
        ttk.Label(cabecera, text="Nombre en la tabla", width=28, font=("", 9, "bold")).grid(row=0, column=1)
        ttk.Label(cabecera, text="Tipo de dato", width=18, font=("", 9, "bold")).grid(row=0, column=2)

        contenedor_canvas = ttk.Frame(frame_cols)
        contenedor_canvas.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self.canvas = tk.Canvas(contenedor_canvas, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(contenedor_canvas, orient="vertical", command=self.canvas.yview)
        self.frame_filas = ttk.Frame(self.canvas)

        self.frame_filas.bind(
            "<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.create_window((0, 0), window=self.frame_filas, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.label_sin_columnas = ttk.Label(
            self.frame_filas, text="Selecciona un archivo para ver sus columnas aqui."
        )
        self.label_sin_columnas.grid(row=0, column=0, pady=10, padx=5)

        # --- Seccion 4: Conexion a MariaDB ---
        frame_db = ttk.LabelFrame(self, text="4. Conexion a la base de datos")
        frame_db.pack(fill="x", **pad)

        campos = [
            ("Servidor:", self.db_host, 15),
            ("Puerto:", self.db_port, 6),
            ("Usuario:", self.db_user, 15),
            ("Contrasena:", self.db_pass, 15),
            ("Base de datos:", self.db_name, 15),
        ]
        for i, (etiqueta, var, ancho) in enumerate(campos):
            ttk.Label(frame_db, text=etiqueta).grid(row=0, column=i * 2, padx=(10, 3), pady=8, sticky="w")
            show = "*" if etiqueta == "Contrasena:" else None
            ttk.Entry(frame_db, textvariable=var, width=ancho, show=show).grid(
                row=0, column=i * 2 + 1, padx=(0, 8), pady=8, sticky="w"
            )

        # --- Seccion 5: Accion ---
        frame_accion = ttk.Frame(self)
        frame_accion.pack(fill="x", **pad)

        self.boton_cargar = ttk.Button(
            frame_accion, text="Crear tabla y cargar datos", command=self._ejecutar_carga
        )
        self.boton_cargar.pack(side="right", padx=10, pady=6)

        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(frame_accion, textvariable=self.status_var, foreground="#555").pack(
            side="left", padx=10
        )

    # ------------------------------------------------------------- acciones
    def _elegir_archivo(self):
        ruta = filedialog.askopenfilename(
            title="Selecciona el archivo exportado de eBird",
            filetypes=[("Archivos CSV o TXT", "*.csv *.txt"), ("Todos los archivos", "*.*")],
        )
        if not ruta:
            return
        self.ruta_archivo.set(ruta)
        self._releer_encabezado()

    def _detectar_delimitador(self, muestra: str) -> str:
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
            return dialecto.delimiter
        except csv.Error:
            return ","

    def _releer_encabezado(self):
        ruta = self.ruta_archivo.get()
        if not ruta or not os.path.isfile(ruta):
            return

        try:
            with open(ruta, "r", encoding="utf-8-sig", errors="replace") as f:
                primera_linea = f.readline()
                muestra = primera_linea + f.readline()
        except OSError as e:
            messagebox.showerror("Error al abrir el archivo", f"No se pudo leer el archivo:\n{e}")
            return

        if not primera_linea.strip():
            messagebox.showwarning("Archivo vacio", "El archivo seleccionado esta vacio.")
            return

        # Si el usuario no ha tocado el combo manualmente todavia, autodetectamos.
        delim_actual = DELIMITADORES[self.delimitador_label.get()]
        delim_detectado = self._detectar_delimitador(muestra)
        if delim_detectado != delim_actual:
            for etiqueta, val in DELIMITADORES.items():
                if val == delim_detectado:
                    self.delimitador_label.set(etiqueta)
                    delim_actual = delim_detectado
                    break

        lector = csv.reader([primera_linea], delimiter=delim_actual)
        encabezados = next(lector, [])
        encabezados = [h for h in encabezados if h.strip() != ""] or encabezados

        if not encabezados:
            messagebox.showwarning("Sin columnas", "No se detectaron columnas en el archivo.")
            return

        self.columnas_originales = encabezados
        self._dibujar_filas_columna(encabezados)
        self.status_var.set(f"Se detectaron {len(encabezados)} columnas.")

    def _dibujar_filas_columna(self, encabezados):
        for widget in self.frame_filas.winfo_children():
            widget.destroy()
        self.filas_columna = []

        for i, original in enumerate(encabezados):
            nombre_sugerido = sanitizar_nombre_columna(original)

            ttk.Label(self.frame_filas, text=original, width=28).grid(
                row=i, column=0, padx=5, pady=3, sticky="w"
            )

            var_nombre = tk.StringVar(value=nombre_sugerido)
            ttk.Entry(self.frame_filas, textvariable=var_nombre, width=28).grid(
                row=i, column=1, padx=5, pady=3
            )

            tipo_sugerido = COLUMNAS.get(nombre_sugerido, "VARCHAR(255)")
            var_tipo = tk.StringVar(value=tipo_sugerido)
            combo = ttk.Combobox(
                self.frame_filas, textvariable=var_tipo, values=TIPOS_DISPONIBLES,
                state="readonly", width=16
            )
            combo.grid(row=i, column=2, padx=5, pady=3)

            self.filas_columna.append({
                "original": original,
                "nombre_var": var_nombre,
                "tipo_var": var_tipo,
            })

    # --------------------------------------------------------------- carga
    def _validar_antes_de_cargar(self):
        if pymysql is None:
            messagebox.showerror(
                "Falta un componente",
                "Falta instalar el conector a la base de datos.\n\n"
                "Pide al desarrollador que ejecute:\n    pip install pymysql"
            )
            return False

        if not self.ruta_archivo.get():
            messagebox.showwarning("Falta el archivo", "Primero selecciona un archivo CSV o TXT.")
            return False

        if not self.filas_columna:
            messagebox.showwarning("Sin columnas", "No hay columnas para crear la tabla.")
            return False

        if not self.nombre_tabla.get().strip():
            messagebox.showwarning("Falta el nombre de la tabla", "Escribe un nombre para la tabla.")
            return False

        nombres = [f["nombre_var"].get().strip() for f in self.filas_columna]
        if any(not n for n in nombres):
            messagebox.showwarning("Nombre de columna vacio", "Todas las columnas necesitan un nombre.")
            return False
        if len(nombres) != len(set(nombres)):
            messagebox.showwarning(
                "Nombres repetidos", "Hay dos o mas columnas con el mismo nombre. Corrige los nombres."
            )
            return False

        for campo, valor in [("Servidor", self.db_host.get()), ("Usuario", self.db_user.get()),
                              ("Base de datos", self.db_name.get())]:
            if not valor.strip():
                messagebox.showwarning("Falta informacion de conexion", f"Falta el campo: {campo}")
                return False

        return True

    def _ejecutar_carga(self):
        if not self._validar_antes_de_cargar():
            return

        self.boton_cargar.config(state="disabled")
        self.status_var.set("Conectando con la base de datos...")
        self.update_idletasks()

        tabla = sanitizar_nombre_columna(self.nombre_tabla.get())
        delim = DELIMITADORES[self.delimitador_label.get()]
        ruta = self.ruta_archivo.get()

        columnas_sql = [
            f"`{f['nombre_var'].get().strip()}` {f['tipo_var'].get()}"
            for f in self.filas_columna
        ]
        nombres_columnas = [f["nombre_var"].get().strip() for f in self.filas_columna]

        conexion = None
        try:
            conexion = pymysql.connect(
                host=self.db_host.get().strip(),
                port=int(self.db_port.get().strip() or 3306),
                user=self.db_user.get().strip(),
                password=self.db_pass.get(),
                database=self.db_name.get().strip(),
                local_infile=True,
                VARCHARset="utf8mb4",
            )
            cursor = conexion.cursor()

            if self.reemplazar_tabla.get():
                cursor.execute(f"DROP TABLE IF EXISTS `{tabla}`")

            ddl = f"CREATE TABLE `{tabla}` ({', '.join(columnas_sql)})"
            cursor.execute(ddl)

            ruta_sql = ruta.replace("\\", "\\\\").replace("'", "\\'")
            delim_sql = delim.replace("\\", "\\\\").replace("'", "\\'")
            columnas_join = ", ".join(f"`{c}`" for c in nombres_columnas)

            load_sql = (
                f"LOAD DATA LOCAL INFILE '{ruta_sql}' "
                f"INTO TABLE `{tabla}` "
                f"FIELDS TERMINATED BY '{delim_sql}' OPTIONALLY ENCLOSED BY '\"' "
                f"LINES TERMINATED BY '\\n' "
                f"IGNORE 1 LINES "
                f"({columnas_join})"
            )
            cursor.execute(load_sql)
            filas_cargadas = cursor.rowcount
            conexion.commit()

            self.status_var.set(f"Listo. {filas_cargadas} filas cargadas en '{tabla}'.")
            messagebox.showinfo(
                "Carga exitosa",
                f"Se creo la tabla '{tabla}' y se cargaron {filas_cargadas} filas correctamente."
            )

        except pymysql.MySQLError as e:
            self.status_var.set("Ocurrio un error durante la carga.")
            messagebox.showerror(
                "Error al cargar los datos",
                "No se pudo completar la carga.\n\n"
                f"Detalle tecnico: {e}\n\n"
                "Si el error menciona una columna, es posible que la estructura del "
                "archivo haya cambiado. Avisa al desarrollador."
            )
        except Exception as e:
            self.status_var.set("Ocurrio un error inesperado.")
            messagebox.showerror("Error inesperado", str(e))
        finally:
            if conexion is not None:
                conexion.close()
            self.boton_cargar.config(state="normal")


if __name__ == "__main__":
    app = EbirdLoaderApp()
    app.mainloop()
