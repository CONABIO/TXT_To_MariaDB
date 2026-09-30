# Migrador de datos eBird → MariaDB

Aplicación de escritorio con interfaz gráfica (Tkinter) que permite a usuarios **sin conocimientos de SQL** importar archivos CSV o TXT exportados de eBird (o de cualquier otro sistema) directamente a una base de datos MariaDB.

La herramienta detecta automáticamente las columnas del archivo, sugiere el tipo de dato más adecuado para cada una y se encarga de crear la tabla y cargar todos los registros con un solo clic.

---

## ✨ Características

- 🖱️ **Interfaz gráfica amigable** — no se necesita escribir SQL ni usar la terminal.
- 📂 **Soporte para CSV y TXT** con detección automática del delimitador (coma, punto y coma, tabulador o pipe).
- 🧠 **Tipos de dato sugeridos automáticamente** para las columnas estándar de eBird (fechas, coordenadas, banderas, comentarios, etc.).
- ✏️ **Edición manual** del nombre y tipo de cada columna antes de cargar.
- ⚡ **Carga masiva optimizada** mediante `LOAD DATA LOCAL INFILE`, capaz de procesar millones de filas en poco tiempo.
- 🔄 **Opción de reemplazar** la tabla destino si ya existe.
- ⏱️ **Barra de progreso** con contador de tiempo transcurrido para cargas largas.
- 🛡️ **Reporte de avisos** cuando algún valor no coincide con el tipo de dato elegido.
- 🧵 **Carga en segundo plano** — la ventana no se congela mientras se importan los datos.

---

## 📋 Requisitos

### Para el usuario final (versión ejecutable)

- Windows 10 o superior.
- Acceso de red al servidor MariaDB.
- Credenciales válidas (usuario y contraseña) con permisos para crear tablas y cargar datos.

### Para ejecutar desde el código fuente

- Python 3.8 o superior.
- La librería `pymysql`:

```bash
pip install pymysql
