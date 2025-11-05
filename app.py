import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from oauth2client.service_account import ServiceAccountCredentials
import numpy as np

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Attendance Analysis",
    page_icon="📊",
    layout="wide"
)

# --- GOOGLE SHEETS CONNECTION ---
@st.cache_data(ttl=600)
def load_data_from_gsheets(sheet_url, sheet_name):
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet(sheet_name)
        df = get_as_dataframe(worksheet, evaluate_formulas=True)
        df.columns = df.columns.str.strip()
        df = df.dropna(how='all', axis=1).dropna(how='all', axis=0)
        return df
    except Exception as e:
        st.error(f"Error loading data from Google Sheets: {e}")
        return pd.DataFrame()

# --- DATA PREPROCESSING ---
def preprocess_data(df):
    if df.empty:
        return df
    # Consolidate statuses for 'After 1ST status'
    def consolidate_1st_status(status):
        if pd.isna(status) or status == '': return None
        if status in ['Cancelled', 'No-Show']: return 'No-Show Consolidated'
        else: return 'Showed Up'
    df['Status Consolidated 1ST'] = df['After 1ST status'].apply(consolidate_1st_status)
    # Consolidate statuses for 'After RCP Status'
    def consolidate_rcp_status(status):
        if pd.isna(status) or status == '': return None
        if status in ['Cancelled', 'No-Show', 'No-show']: return 'No-Show Consolidated'
        else: return 'Showed Up'
    df['Status Consolidated RCP'] = df['After RCP Status'].apply(consolidate_rcp_status)
    if 'TimeZones Dif vs COT' in df.columns:
        df['TimeZones Dif vs COT'] = pd.to_numeric(df['TimeZones Dif vs COT'], errors='coerce')
    return df

# --- STREAMLIT INTERFACE ---
st.title("📊 Attendance Analysis Dashboard")

# --- HARDCODED GOOGLE SHEET CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1PykSb5ZNTmtbv8oIrCAiJIGdBZ1PyYgwFU4U9p9YBU" # Paste your clean URL here
SHEET_NAME = "Sheet1" 

if "YOUR_GOOGLE_SHEET_URL_HERE" in SHEET_URL:
    st.info("👋 Welcome! Please update the `SHEET_URL` variable in the `app.py` script with your Google Sheets URL.")
else:
    df_raw = load_data_from_gsheets(SHEET_URL, SHEET_NAME)
    
    if not df_raw.empty:
        df = preprocess_data(df_raw.copy())
        st.sidebar.header("⚙️ Filters")

        # --- SIDEBAR FILTERS ---
        all_batches = df['batch_id'].dropna().unique()
        selected_batches = st.sidebar.multiselect("Select Batch IDs", options=all_batches, default=all_batches)
        
        time_granularity = st.sidebar.radio("Select time block granularity", ('30 minutes', '2 hours'))

        min_tz, max_tz = float(df['TimeZones Dif vs COT'].min()), float(df['TimeZones Dif vs COT'].max())
        selected_tz_range = st.sidebar.slider(
            'Filter by Timezone Difference vs COT',
            min_value=min_tz, max_value=max_tz, value=(min_tz, max_tz)
        )
        
        email_query = st.sidebar.text_input("Search by email")

        # --- APPLYING FILTERS ---
        df_filtered = df.copy()
        if selected_batches:
            df_filtered = df_filtered[df_filtered['batch_id'].isin(selected_batches)]
        
        # CORRECTED TIMEZONE FILTER LOGIC
        if 'TimeZones Dif vs COT' in df_filtered.columns:
            # Keep rows that are within the range OR where timezone is not specified (NaN)
            df_filtered = df_filtered[
                (df_filtered['TimeZones Dif vs COT'].between(selected_tz_range[0], selected_tz_range[1])) |
                (df_filtered['TimeZones Dif vs COT'].isna())
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
            
            # --- MAIN ANALYSIS ---
            st.header("📈 Attendance Rate Analysis")

            if time_granularity == '30 minutes':
                col_block_1st = '1ST COL 30min Block'
                col_block_rcp = 'RCP COL 30min Block'
            else:
                col_block_1st = '1ST COL 2h Block'

            # --- ANALYSIS 1: NEW DETAILED TABLE (LIKE EXCEL) ---
            st.subheader(f"Analysis 1: {time_granularity} Blocks vs. Status (1ST Call)")
            
            df_analysis_1 = df_filtered.dropna(subset=[col_block_1st, 'After 1ST status'])
            
            if not df_analysis_1.empty:
                # Create detailed crosstab with original statuses
                freq_detailed = pd.crosstab(df_analysis_1[col_block_1st], df_analysis_1['After 1ST status'])
                
                # Calculate new columns based on the detailed crosstab
                freq_detailed['Grand Total'] = freq_detailed.sum(axis=1)
                
                no_show_statuses = [col for col in ['Cancelled', 'No-Show'] if col in freq_detailed.columns]
                show_up_statuses = [col for col in freq_detailed.columns if col not in no_show_statuses + ['Grand Total']]
                
                freq_detailed['No Show'] = freq_detailed[no_show_statuses].sum(axis=1)
                freq_detailed['Showed Up'] = freq_detailed[show_up_statuses].sum(axis=1)
                
                # Calculate percentages
                freq_detailed['Showed Up %'] = (freq_detailed['Showed Up'] / freq_detailed['Grand Total']) * 100
                freq_detailed['No Show %'] = (freq_detailed['No Show'] / freq_detailed['Grand Total']) * 100
                freq_detailed['Weight %'] = (freq_detailed['Grand Total'] / freq_detailed['Grand Total'].sum()) * 100
                
                # Add Grand Total row
                total_row = freq_detailed.sum().rename('Grand Total')
                total_row['Showed Up %'] = (total_row['Showed Up'] / total_row['Grand Total']) * 100
                total_row['No Show %'] = (total_row['No Show'] / total_row['Grand Total']) * 100
                total_row['Weight %'] = 100.0
                freq_detailed = pd.concat([freq_detailed, total_row.to_frame().T])

                # Define column order for display
                count_cols = [col for col in df_analysis_1['After 1ST status'].unique() if col in freq_detailed.columns]
                display_cols = count_cols + ['Grand Total', 'Showed Up %', 'No Show %', 'Weight %']
                
                # Apply improved styling
                styler = freq_detailed[display_cols].style \
                    .format("{:.2f}%", subset=['Showed Up %', 'No Show %', 'Weight %']) \
                    .format("{:,.0f}", subset=count_cols + ['Grand Total'], na_rep="") \
                    .background_gradient(cmap='Blues', subset=count_cols + ['Grand Total']) \
                    .background_gradient(cmap='RdYlGn', subset=['Showed Up %']) \
                    .background_gradient(cmap='RdYlGn_r', subset=['No Show %'])
                
                st.dataframe(styler, use_container_width=True)

            else:
                st.info("Not enough data for Analysis 1 with the current filters.")

            # --- ANALYSIS 2: RCP COL vs After RCP Status ---
            st.subheader(f"Analysis 2: {time_granularity} Blocks vs. Status (RCP Call)")
            
            df_analysis_2 = df_filtered.dropna(subset=[col_block_rcp, 'Status Consolidated RCP'])
            if not df_analysis_2.empty:
                freq_2 = pd.crosstab(df_analysis_2[col_block_rcp], df_analysis_2['Status Consolidated RCP'])
                freq_2['Total'] = freq_2.sum(axis=1)

                # Create percentage table separately for better styling control
                perc_2 = freq_2.div(freq_2['Total'], axis=0) * 100
                
                # Combine for display
                combined_2 = pd.concat([freq_2, perc_2.rename(columns=lambda c: c + ' %')], axis=1)

                # Define columns for styling
                count_cols_2 = freq_2.columns
                show_up_col_2 = 'Showed Up %' if 'Showed Up' in freq_2.columns else None
                no_show_col_2 = 'No-Show Consolidated %' if 'No-Show Consolidated' in freq_2.columns else None

                styler_2 = combined_2.style
                styler_2 = styler_2.format("{:,.0f}", subset=count_cols_2)
                if show_up_col_2:
                    styler_2 = styler_2.format("{:.2f}%", subset=[show_up_col_2]).background_gradient(cmap='RdYlGn', subset=[show_up_col_2])
                if no_show_col_2:
                    styler_2 = styler_2.format("{:.2f}%", subset=[no_show_col_2]).background_gradient(cmap='RdYlGn_r', subset=[no_show_col_2])

                st.dataframe(styler_2, use_container_width=True)
            else:
                st.info("Not enough data for Analysis 2 with the current filters.")

            # --- DISPLAY FILTERED DATA ---
            with st.expander("View full filtered data"):
                st.dataframe(df_filtered)
