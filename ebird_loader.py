"""
Migrador de datos eBird -> MariaDB
-----------------------------------
Aplicacion de escritorio (tkinter) para que usuarios sin conocimientos de SQL puedan:
  1) Seleccionar un archivo CSV o TXT (exportado de eBird o cualquier otro sistema).
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
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import pymysql
except ImportError:
    pymysql = None

# Tipos de dato disponibles para que el usuario elija por columna.
TIPOS_DISPONIBLES = [
    "VARCHAR(255)",
    "TEXT",
    "LONGTEXT",
    "INT",
    "BIGINT",
    "DECIMAL(10,2)",
    "DOUBLE",
    "DATE",
    "DATETIME"   
]

DELIMITADORES = {
    "Coma (,)": ",",
    "Punto y coma (;)": ";",
    "Tabulador": "\t",
    "Pipe (|)": "|",
}

# Tipos de dato conocidos para las columnas estandar del CSV de eBird.
# Las llaves deben ir en MAYUSCULAS: la comparacion se hace normalizando
# el encabezado del archivo a mayusculas antes de buscarlo aqui.
# Cualquier columna que NO aparezca en este diccionario usara VARCHAR(255)
# por defecto (ver _dibujar_filas_columna).
COLUMNAS = {
    "AGE/SEX": "TEXT",
    "LATITUDE": "DOUBLE",
    "LONGITUDE": "DOUBLE",
    "OBSERVATION_DATE": "DATETIME",
    "OBSERVER_ORCID_ID": "TEXT",
    "ALL_SPECIES_REPORTED": "INT",
    "HAS_MEDIA": "INT",
    "APPROVED": "INT",
    "REVIEWED": "INT",
    "LOCALITY": "TEXT",
    "CHECKLIST_COMMENTS": "LONGTEXT",
    "SPECIES_COMMENTS": "LONGTEXT",
}

# Se agregan al final de la lista los tipos especificos usados en COLUMNAS
# que no estuvieran ya en TIPOS_DISPONIBLES, para que el combo pueda
# mostrarlos y el usuario pueda volver a elegirlos si los cambia por error.
for _tipo in COLUMNAS.values():
    if _tipo not in TIPOS_DISPONIBLES:
        TIPOS_DISPONIBLES.append(_tipo)


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

        self.hilo_carga = None
        self.tiempo_inicio = None

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

        self.barra_progreso = ttk.Progressbar(frame_accion, mode="indeterminate", length=160)
        # Se muestra solo mientras dura la carga (ver _ejecutar_carga).

        self.status_var = tk.StringVar(value="Listo.")
        ttk.Label(frame_accion, textvariable=self.status_var, foreground="#555").pack(
            side="left", padx=10
        )

        # Aviso para archivos grandes.
        ttk.Label(
            frame_accion,
            text="Archivos muy grandes (millones de filas) pueden tardar varios minutos.",
            foreground="#888", font=("", 8)
        ).pack(side="left", padx=10)

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

        if self.hilo_carga is not None and self.hilo_carga.is_alive():
            return  # ya hay una carga en curso, evita doble clic

        # Empaquetamos todos los datos que el hilo va a necesitar; nunca se
        # deben tocar los widgets de tkinter desde dentro del hilo.
        datos = {
            "tabla": sanitizar_nombre_columna(self.nombre_tabla.get()),
            "delim": DELIMITADORES[self.delimitador_label.get()],
            "ruta": self.ruta_archivo.get(),
            "reemplazar": self.reemplazar_tabla.get(),
            "columnas_sql": [
                f"`{f['nombre_var'].get().strip()}` {f['tipo_var'].get()}"
                for f in self.filas_columna
            ],
            "nombres_columnas": [f["nombre_var"].get().strip() for f in self.filas_columna],
            "host": self.db_host.get().strip(),
            "port": int(self.db_port.get().strip() or 3306),
            "user": self.db_user.get().strip(),
            "password": self.db_pass.get(),
            "database": self.db_name.get().strip(),
        }

        # --- Preparar la interfaz para el modo "cargando" ---
        self.boton_cargar.config(state="disabled")
        self.barra_progreso.pack(side="right", padx=(0, 10))
        self.barra_progreso.start(12)
        self.tiempo_inicio = time.time()
        self._actualizar_tiempo_transcurrido()

        self.hilo_carga = threading.Thread(
            target=self._proceso_carga_hilo, args=(datos,), daemon=True
        )
        self.hilo_carga.start()

    def _actualizar_tiempo_transcurrido(self):
        """Se reprograma cada segundo mientras el hilo de carga sigue vivo."""
        if self.hilo_carga is None or not self.hilo_carga.is_alive():
            return
        segundos = int(time.time() - self.tiempo_inicio)
        minutos, segs = divmod(segundos, 60)
        self.status_var.set(f"Cargando datos... ({minutos:02d}:{segs:02d} transcurridos)")
        self.after(1000, self._actualizar_tiempo_transcurrido)

    def _proceso_carga_hilo(self, datos):
        """
        Se ejecuta en un hilo separado para que la ventana no se congele
        durante cargas grandes (millones de filas). No debe tocar widgets
        directamente: solo agenda actualizaciones con self.after(...).
        """
        conexion = None
        resultado = {"exito": False, "mensaje": "", "detalle": "", "filas": 0, "avisos": 0}
        try:
            conexion = pymysql.connect(
                host=datos["host"],
                port=datos["port"],
                user=datos["user"],
                password=datos["password"],
                database=datos["database"],
                local_infile=True,
                charset="utf8mb4",
                # Sin limite de tiempo de lectura/escritura: una carga de
                # millones de filas puede tardar mas que el timeout por
                # defecto de una conexion normal.
                read_timeout=None,
                write_timeout=None,
                connect_timeout=15,
            )
            cursor = conexion.cursor()

            if datos["reemplazar"]:
                cursor.execute(f"DROP TABLE IF EXISTS `{datos['tabla']}`")

            ddl = f"CREATE TABLE `{datos['tabla']}` ({', '.join(datos['columnas_sql'])}) ENGINE=InnoDB"
            cursor.execute(ddl)

            # Optimizaciones para inserciones masivas: se desactivan
            # temporalmente las verificaciones que mas ralentizan un LOAD
            # DATA grande. Como la tabla se acaba de crear sin llaves
            # foraneas ni indices unicos propios, esto es seguro aqui.
            cursor.execute("SET SESSION unique_checks = 0")
            cursor.execute("SET SESSION foreign_key_checks = 0")

            ruta_sql = datos["ruta"].replace("\\", "\\\\").replace("'", "\\'")
            delim_sql = datos["delim"].replace("\\", "\\\\").replace("'", "\\'")
            columnas_join = ", ".join(f"`{c}`" for c in datos["nombres_columnas"])

            load_sql = (
                f"LOAD DATA LOCAL INFILE '{ruta_sql}' "
                f"INTO TABLE `{datos['tabla']}` "
                f"FIELDS TERMINATED BY '{delim_sql}' "
                f"LINES TERMINATED BY '\\n' "
                f"IGNORE 1 LINES "                
            )
            cursor.execute(load_sql)
            resultado["filas"] = cursor.rowcount

            # Cuantos valores tuvieron que truncarse o volverse NULL porque
            # no calzaban con el tipo elegido (ej. una fecha con formato
            # distinto). MySQL/MariaDB no falla el LOAD DATA por esto, solo
            # avisa, asi que se lo reportamos al usuario.
            cursor.execute("SELECT @@warning_count")
            resultado["avisos"] = cursor.fetchone()[0]

            cursor.execute("SET SESSION unique_checks = 1")
            cursor.execute("SET SESSION foreign_key_checks = 1")

            conexion.commit()
            resultado["exito"] = True

        except pymysql.MySQLError as e:
            resultado["mensaje"] = "Error al cargar los datos"
            resultado["detalle"] = (
                f"No se pudo completar la carga.\n\nDetalle tecnico: {e}\n\n"
                "Si el error menciona una columna, es posible que la estructura del "
                "archivo haya cambiado. Avisa al desarrollador."
            )
        except Exception as e:
            resultado["mensaje"] = "Error inesperado"
            resultado["detalle"] = str(e)
        finally:
            if conexion is not None:
                conexion.close()

        # De vuelta al hilo principal para tocar la interfaz.
        self.after(0, self._carga_terminada, resultado, datos["tabla"])

    def _carga_terminada(self, resultado, tabla):
        self.barra_progreso.stop()
        self.barra_progreso.pack_forget()
        self.boton_cargar.config(state="normal")
        self.hilo_carga = None

        if resultado["exito"]:
            self.status_var.set(f"Listo. {resultado['filas']} filas cargadas en '{tabla}'.")
            if resultado["avisos"] > 0:
                messagebox.showwarning(
                    "Carga completada con avisos",
                    f"Se cargaron {resultado['filas']} filas en '{tabla}', pero MariaDB "
                    f"reporto {resultado['avisos']} avisos (por ejemplo, valores que no "
                    "coincidian con el tipo de dato elegido y se guardaron vacios o "
                    "truncados).\n\nRevisa con el desarrollador si esto es esperado."
                )
            else:
                messagebox.showinfo(
                    "Carga exitosa",
                    f"Se creo la tabla '{tabla}' y se cargaron {resultado['filas']} filas correctamente."
                )
        else:
            self.status_var.set("Ocurrio un error durante la carga.")
            messagebox.showerror(resultado["mensaje"], resultado["detalle"])


if __name__ == "__main__":
    app = EbirdLoaderApp()
    app.mainloop()
