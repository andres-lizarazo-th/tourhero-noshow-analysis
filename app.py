import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Análisis de Asistencia",
    page_icon="📊",
    layout="wide"
)

# --- CONEXIÓN A GOOGLE SHEETS ---
# Usamos el cache de Streamlit para no tener que cargar los datos en cada interacción.
@st.cache_data(ttl=600) # Cache por 10 minutos
def load_data_from_gsheets(sheet_url, sheet_name):
    """
    Carga los datos desde una hoja de cálculo de Google Sheets a un DataFrame de Pandas.
    Utiliza los secretos de Streamlit para la autenticación.
    """
    try:
        # Definimos el alcance (scope) de los permisos
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # Autenticación usando los secretos de Streamlit
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        
        # Abrimos la hoja de cálculo y la hoja específica
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # Convertimos la hoja a un DataFrame de Pandas
        # header=1 asume que la primera fila es la cabecera
        df = get_as_dataframe(worksheet, evaluate_formulas=True)
        
        # Limpieza básica de columnas con nombres extraños o vacías
        df.columns = df.columns.str.strip()
        df = df.dropna(how='all', axis=1).dropna(how='all', axis=0)
        
        return df
    except Exception as e:
        st.error(f"Error al cargar los datos desde Google Sheets: {e}")
        return pd.DataFrame()

# --- PREPROCESAMIENTO DE DATOS ---
def preprocess_data(df):
    """
    Realiza la limpieza y transformaciones necesarias en el DataFrame.
    """
    if df.empty:
        return df

    # Consolidación de status para 'After 1ST status'
    def consolidate_1st_status(status):
        if pd.isna(status) or status == '':
            return None
        if status in ['Cancelled', 'No-Show']:
            return 'No-show Consolidado'
        else:
            return 'Showed Up'

    df['Status Consolidado 1ST'] = df['After 1ST status'].apply(consolidate_1st_status)

    # Consolidación de status para 'After RCP Status'
    def consolidate_rcp_status(status):
        if pd.isna(status) or status == '':
            return None
        if status in ['Cancelled', 'No-Show', 'No-show']: # Incluimos 'No-show' por si acaso
            return 'No-show Consolidado'
        else:
            return 'Showed Up'
            
    df['Status Consolidado RCP'] = df['After RCP Status'].apply(consolidate_rcp_status)
    
    # Asegurar que la columna de diferencia de zona horaria es numérica
    if 'TimeZones Dif vs COT' in df.columns:
        df['TimeZones Dif vs COT'] = pd.to_numeric(df['TimeZones Dif vs COT'], errors='coerce')

    return df

def create_crosstab_analysis(df, index_col, columns_col):
    """
    Crea una tabla de frecuencia y una de porcentajes.
    """
    # Crear la tabla de frecuencia (conteo)
    crosstab_freq = pd.crosstab(df[index_col], df[columns_col])
    
    # Calcular el total por fila para los porcentajes
    row_totals = crosstab_freq.sum(axis=1)
    
    # Crear la tabla de porcentajes
    crosstab_perc = crosstab_freq.div(row_totals, axis=0) * 100
    
    # Añadir columna de Total (conteo) a la tabla de frecuencias
    crosstab_freq['Total'] = row_totals
    
    return crosstab_freq, crosstab_perc


# --- INTERFAZ DE STREAMLIT ---
st.title("📊 Dashboard de Análisis de Asistencia")

sheet_url = "https://docs.google.com/spreadsheets/d/1PykSb5ZNTmtbv8oIrCAiJIGdBZ1PyYgwFU4U9p9YBU/edit?gid=0#gid=0" 
sheet_name = "Sheet1" 

if sheet_url and sheet_name:
    # Cargar y preprocesar los datos
    df_raw = load_data_from_gsheets(sheet_url, sheet_name)
    
    if not df_raw.empty:
        df = preprocess_data(df_raw.copy())
        
        st.sidebar.header("⚙️ Filtros")

        # --- FILTROS EN LA BARRA LATERAL ---
        
        # Filtro de Batch ID (selección múltiple)
        all_batches = df['batch_id'].dropna().unique()
        selected_batches = st.sidebar.multiselect(
            "Selecciona Batch IDs",
            options=all_batches,
            default=all_batches
        )

        # Filtro de granularidad de tiempo (30min vs 2h)
        time_granularity = st.sidebar.radio(
            "Selecciona la granularidad del bloque de tiempo",
            ('30 minutos', '2 horas')
        )

        # Filtro por diferencia de zona horaria
        min_tz, max_tz = float(df['TimeZones Dif vs COT'].min()), float(df['TimeZones Dif vs COT'].max())
        selected_tz_range = st.sidebar.slider(
            'Filtra por Diferencia Horaria vs COT',
            min_value=min_tz,
            max_value=max_tz,
            value=(min_tz, max_tz)
        )

        # Filtro por correo electrónico
        email_query = st.sidebar.text_input("Buscar por correo electrónico")

        # --- APLICACIÓN DE FILTROS ---
        df_filtrado = df.copy()

        if selected_batches:
            df_filtrado = df_filtrado[df_filtrado['batch_id'].isin(selected_batches)]
        
        if 'TimeZones Dif vs COT' in df_filtrado.columns:
            df_filtrado = df_filtrado[
                df_filtrado['TimeZones Dif vs COT'].between(selected_tz_range[0], selected_tz_range[1])
            ]
        
        if email_query:
            df_filtrado = df_filtrado[
                df_filtrado['public_email'].astype(str).str.contains(email_query, case=False, na=False) |
                df_filtrado['public_email_biography'].astype(str).str.contains(email_query, case=False, na=False)
            ]

        # --- MOSTRAR RESULTADOS ---
        if df_filtrado.empty:
            st.warning("No hay datos que coincidan con los filtros seleccionados.")
        else:
            st.success(f"Mostrando {len(df_filtrado)} registros después de aplicar los filtros.")

            # --- ANÁLISIS EXPLORATORIO DE DATOS (EDA) ---
            st.header("🔍 Análisis Exploratorio de Datos (EDA)")
            col1, col2, col3 = st.columns(3)
            col1.metric("Total de Leads Filtrados", len(df_filtrado))
            col2.metric("Batch IDs Únicos", df_filtrado['batch_id'].nunique())
            col3.metric("Promedio Dif. Horaria", f"{df_filtrado['TimeZones Dif vs COT'].mean():.2f} horas")

            st.subheader("Distribución de Status (1ST COL)")
            st.bar_chart(df_filtrado['After 1ST status'].value_counts())
            
            st.subheader("Distribución de Status (RCP COL)")
            st.bar_chart(df_filtrado['After RCP Status'].value_counts())


            # --- ANÁLISIS PRINCIPAL DE ASISTENCIA ---
            st.header("📈 Análisis de Tasa de Asistencia")

            # Selección dinámica de columnas según el filtro de granularidad
            if time_granularity == '30 minutos':
                col_bloque_1st = '1ST COL 30min Block'
                col_bloque_rcp = 'RCP COL 30min Block'
            else: # 2 horas
                col_bloque_1st = '1ST COL 2h Block'
                col_bloque_rcp = 'RCP COL 2h Block'

            # --- ANÁLISIS 1: 1ST COL vs After 1ST status ---
            st.subheader(f"Análisis 1: Bloques de {time_granularity} vs. Status (1ST Call)")
            
            df_analisis_1 = df_filtrado.dropna(subset=[col_bloque_1st, 'Status Consolidado 1ST'])
            if not df_analisis_1.empty:
                freq_1, perc_1 = create_crosstab_analysis(df_analisis_1, col_bloque_1st, 'Status Consolidado 1ST')
                
                st.write("**Tabla de Frecuencia (Conteo)**")
                st.dataframe(freq_1.style.background_gradient(cmap='viridis', axis=1))

                st.write("**Tabla de Porcentajes (%)**")
                st.dataframe(perc_1.style.format("{:.2f}%").background_gradient(cmap='plasma_r', axis=1))
            else:
                st.info("No hay datos suficientes para el Análisis 1 con los filtros actuales.")


            # --- ANÁLISIS 2: RCP COL vs After RCP Status ---
            st.subheader(f"Análisis 2: Bloques de {time_granularity} vs. Status (RCP Call)")

            df_analisis_2 = df_filtrado.dropna(subset=[col_bloque_rcp, 'Status Consolidado RCP'])
            if not df_analisis_2.empty:
                freq_2, perc_2 = create_crosstab_analysis(df_analisis_2, col_bloque_rcp, 'Status Consolidado RCP')
                
                st.write("**Tabla de Frecuencia (Conteo)**")
                st.dataframe(freq_2.style.background_gradient(cmap='viridis', axis=1))

                st.write("**Tabla de Porcentajes (%)**")
                st.dataframe(perc_2.style.format("{:.2f}%").background_gradient(cmap='plasma_r', axis=1))
            else:
                st.info("No hay datos suficientes para el Análisis 2 con los filtros actuales.")


            # --- MOSTRAR DATOS FILTRADOS ---
            with st.expander("Ver datos filtrados completos"):
                st.dataframe(df_filtrado)
    else:
        st.info("Esperando a que se ingresen la URL y el nombre de la hoja para cargar los datos.")
