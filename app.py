import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from oauth2client.service_account import ServiceAccountCredentials

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Attendance Analysis",
    page_icon="📊",
    layout="wide"
)

# --- GOOGLE SHEETS CONNECTION ---
# Use Streamlit's cache to avoid reloading data on every interaction.
@st.cache_data(ttl=600) # Cache data for 10 minutes
def load_data_from_gsheets(sheet_url, sheet_name):
    """
    Loads data from a Google Sheet into a Pandas DataFrame.
    Uses Streamlit secrets for authentication.
    """
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        df = get_as_dataframe(worksheet, evaluate_formulas=True)
        
        # Basic cleanup for column names and empty rows/columns
        df.columns = df.columns.str.strip()
        df = df.dropna(how='all', axis=1).dropna(how='all', axis=0)
        
        return df
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {e}")
        return pd.DataFrame()

# --- DATA PREPROCESSING ---
def preprocess_data(df):
    """
    Performs necessary cleaning and transformations on the DataFrame.
    """
    if df.empty:
        return df

    # Consolidate statuses for 'After 1ST status'
    def consolidate_1st_status(status):
        if pd.isna(status) or status == '':
            return None
        if status in ['Cancelled', 'No-Show']:
            return 'No-Show Consolidated'
        else:
            return 'Showed Up'

    df['Status Consolidated 1ST'] = df['After 1ST status'].apply(consolidate_1st_status)

    # Consolidate statuses for 'After RCP Status'
    def consolidate_rcp_status(status):
        if pd.isna(status) or status == '':
            return None
        if status in ['Cancelled', 'No-Show', 'No-show']: # Include 'No-show' just in case
            return 'No-Show Consolidated'
        else:
            return 'Showed Up'
            
    df['Status Consolidated RCP'] = df['After RCP Status'].apply(consolidate_rcp_status)
    
    # Ensure the timezone difference column is numeric
    if 'TimeZones Dif vs COT' in df.columns:
        df['TimeZones Dif vs COT'] = pd.to_numeric(df['TimeZones Dif vs COT'], errors='coerce')

    return df

def create_crosstab_analysis(df, index_col, columns_col):
    """
    Creates a frequency table and a percentage table from the data.
    """
    crosstab_freq = pd.crosstab(df[index_col], df[columns_col])
    row_totals = crosstab_freq.sum(axis=1)
    crosstab_perc = crosstab_freq.div(row_totals, axis=0) * 100
    crosstab_freq['Total'] = row_totals
    
    return crosstab_freq, crosstab_perc

# --- STREAMLIT INTERFACE ---
st.title("📊 Attendance Analysis Dashboard")

# --- HARDCODED GOOGLE SHEET CONFIGURATION ---
# IMPORTANT: Replace the URL and Sheet Name with your own.
SHEET_URL = "https://docs.google.com/spreadsheets/d/1PykSb5ZNTmtbvv8oIrCAiJIGdBZ1PyYgwFU4U9p9YBU" 
SHEET_NAME = "Sheet1" 

# Check if the placeholder URL is still there
if "YOUR_GOOGLE_SHEET_URL_HERE" in SHEET_URL:
    st.info("👋 Welcome! Please update the `SHEET_URL` variable in the `app.py` script with your Google Sheets URL.")
else:
    # Load and preprocess the data
    df_raw = load_data_from_gsheets(SHEET_URL, SHEET_NAME)
    
    if not df_raw.empty:
        df = preprocess_data(df_raw.copy())
        
        st.sidebar.header("⚙️ Filters")

        # --- SIDEBAR FILTERS ---
        
        # Filter by Batch ID (multi-select)
        all_batches = df['batch_id'].dropna().unique()
        selected_batches = st.sidebar.multiselect(
            "Select Batch IDs",
            options=all_batches,
            default=all_batches
        )

        # Filter by time granularity (30min vs 2h)
        time_granularity = st.sidebar.radio(
            "Select time block granularity",
            ('30 minutes', '2 hours')
        )

        # Filter by timezone difference
        min_tz, max_tz = float(df['TimeZones Dif vs COT'].min()), float(df['TimeZones Dif vs COT'].max())
        selected_tz_range = st.sidebar.slider(
            'Filter by Timezone Difference vs COT',
            min_value=min_tz,
            max_value=max_tz,
            value=(min_tz, max_tz)
        )

        # Filter by email address
        email_query = st.sidebar.text_input("Search by email")

        # --- APPLYING FILTERS ---
        df_filtered = df.copy()

        if selected_batches:
            df_filtered = df_filtered[df_filtered['batch_id'].isin(selected_batches)]
        
        if 'TimeZones Dif vs COT' in df_filtered.columns:
            df_filtered = df_filtered[
                df_filtered['TimeZones Dif vs COT'].between(selected_tz_range[0], selected_tz_range[1])
            ]
        
        if email_query:
            df_filtered = df_filtered[
                df_filtered['public_email'].astype(str).str.contains(email_query, case=False, na=False) |
                df_filtered['public_email_biography'].astype(str).str.contains(email_query, case=False, na=False)
            ]

        # --- DISPLAY RESULTS ---
        if df_filtered.empty:
            st.warning("No data matches the selected filters.")
        else:
            st.success(f"Displaying {len(df_filtered)} records after applying filters.")

            # --- EXPLORATORY DATA ANALYSIS (EDA) ---
            st.header("🔍 Exploratory Data Analysis (EDA)")
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Filtered Leads", len(df_filtered))
            col2.metric("Unique Batch IDs", df_filtered['batch_id'].nunique())
            col3.metric("Avg. Timezone Diff", f"{df_filtered['TimeZones Dif vs COT'].mean():.2f} hours")

            st.subheader("Status Distribution (1ST Call)")
            st.bar_chart(df_filtered['After 1ST status'].value_counts())
            
            st.subheader("Status Distribution (RCP Call)")
            st.bar_chart(df_filtered['After RCP Status'].value_counts())

            # --- MAIN ATTENDANCE ANALYSIS ---
            st.header("📈 Attendance Rate Analysis")

            # Dynamically select columns based on the granularity filter
            if time_granularity == '30 minutes':
                col_block_1st = '1ST COL 30min Block'
                col_block_rcp = 'RCP COL 30min Block'
            else: # 2 hours
                col_block_1st = '1ST COL 2h Block'
                col_block_rcp = 'RCP COL 2h Block'

            # --- ANALYSIS 1: 1ST COL vs After 1ST status ---
            st.subheader(f"Analysis 1: {time_granularity} Blocks vs. Status (1ST Call)")
            
            df_analysis_1 = df_filtered.dropna(subset=[col_block_1st, 'Status Consolidated 1ST'])
            if not df_analysis_1.empty:
                freq_1, perc_1 = create_crosstab_analysis(df_analysis_1, col_block_1st, 'Status Consolidated 1ST')
                
                st.write("**Frequency Table (Count)**")
                st.dataframe(freq_1.style.background_gradient(cmap='viridis', axis=1))

                st.write("**Percentage Table (%)**")
                st.dataframe(perc_1.style.format("{:.2f}%").background_gradient(cmap='plasma_r', axis=1))
            else:
                st.info("Not enough data for Analysis 1 with the current filters.")

            # --- ANALYSIS 2: RCP COL vs After RCP Status ---
            st.subheader(f"Analysis 2: {time_granularity} Blocks vs. Status (RCP Call)")

            df_analysis_2 = df_filtered.dropna(subset=[col_block_rcp, 'Status Consolidated RCP'])
            if not df_analysis_2.empty:
                freq_2, perc_2 = create_crosstab_analysis(df_analysis_2, col_block_rcp, 'Status Consolidated RCP')
                
                st.write("**Frequency Table (Count)**")
                st.dataframe(freq_2.style.background_gradient(cmap='viridis', axis=1))

                st.write("**Percentage Table (%)**")
                st.dataframe(perc_2.style.format("{:.2f}%").background_gradient(cmap='plasma_r', axis=1))
            else:
                st.info("Not enough data for Analysis 2 with the current filters.")

            # --- DISPLAY FILTERED DATA ---
            with st.expander("View full filtered data"):
                st.dataframe(df_filtered)
