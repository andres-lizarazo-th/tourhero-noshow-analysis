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
    if 'TimeZones Dif vs COT' in df.columns:
        df['TimeZones Dif vs COT'] = pd.to_numeric(df['TimeZones Dif vs COT'], errors='coerce')
    
    # Create the short, 4-digit batch ID for easier filtering and display
    if 'batch_id' in df.columns:
        df['batch_id'] = pd.to_numeric(df['batch_id'], errors='coerce')
        # Create a temporary series of strings, slice, and assign back
        df['short_batch_id'] = df['batch_id'].dropna().astype(np.int64).astype(str).str[3:7]

    return df

# --- STREAMLIT INTERFACE ---
st.title("📊 Attendance Analysis Dashboard")

# --- HARDCODED GOOGLE SHEET CONFIGURATION ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/1PykSb5ZNTmtbvv8oIrCAiJIGdBZ1PyYgwFU4U9p9YBU"
SHEET_NAME = "Sheet1"

if "YOUR_GOOGLE_SHEET_URL_HERE" in SHEET_URL:
    st.info("👋 Welcome! Please update the `SHEET_URL` variable in the `app.py` script with your Google Sheets URL.")
else:
    df_raw = load_data_from_gsheets(SHEET_URL, SHEET_NAME)
    
    if not df_raw.empty:
        df = preprocess_data(df_raw.copy())
        
        st.sidebar.header("⚙️ Filters")

        # --- SIDEBAR FILTERS ---
        
        # BATCH ID FILTER using short IDs
        with st.sidebar.expander("Select Batch IDs", expanded=True):
            if 'short_batch_id' in df.columns:
                sorted_short_batches = sorted(df['short_batch_id'].dropna().unique())
                
                if not sorted_short_batches:
                    st.warning("No valid Batch IDs found.")
                    selected_batch_range = None
                else:
                    # This slider snaps to actual existing short batch IDs
                    selected_batch_range = st.select_slider(
                        'Filter by Short Batch ID Range',
                        options=sorted_short_batches,
                        value=(sorted_short_batches[0], sorted_short_batches[-1])
                    )
            else:
                st.warning("Batch ID column not found.")
                selected_batch_range = None

        # Filter by time granularity
        time_granularity = st.sidebar.radio("Select time block granularity", ('30 minutes', '2 hours'))

        # TIMEZONE SLIDER with 0.5 steps
        clean_tz = df['TimeZones Dif vs COT'].dropna()
        if not clean_tz.empty:
            min_tz, max_tz = float(clean_tz.min()), float(clean_tz.max())
            # Round min/max to the nearest 0.5 for a cleaner slider
            min_tz_rounded = np.floor(min_tz * 2) / 2
            max_tz_rounded = np.ceil(max_tz * 2) / 2
            
            selected_tz_range = st.sidebar.slider(
                'Filter by Timezone Difference vs COT',
                min_value=min_tz_rounded,
                max_value=max_tz_rounded,
                value=(min_tz_rounded, max_tz_rounded),
                step=0.5 # Set the step to 0.5
            )
        else:
            selected_tz_range = (0, 0)
            st.sidebar.warning("No valid Timezone data found.")

        # Filter by email
        email_query = st.sidebar.text_input("Search by email")

        # --- APPLYING FILTERS ---
        df_filtered = df.copy()
        
        if selected_batch_range:
            df_filtered = df_filtered[df_filtered['short_batch_id'].between(selected_batch_range[0], selected_batch_range[1])]
        else:
            df_filtered = pd.DataFrame(columns=df.columns)

        if selected_tz_range != (0, 0):
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
            # --- EDA SECTION ---
            st.header("🔍 Exploratory Data Analysis (EDA)")
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Filtered Leads", f"{len(df_filtered):,}")
            col2.metric("Unique Batch IDs", df_filtered['batch_id'].nunique())
            if not df_filtered['TimeZones Dif vs COT'].dropna().empty:
                col3.metric("Avg. Timezone Diff", f"{df_filtered['TimeZones Dif vs COT'].mean():.2f} hours")

            st.subheader("Distribution of Statuses (1ST Call)")
            st.bar_chart(df_filtered['After 1ST status'].value_counts())
            
            st.subheader("Distribution of Statuses (RCP Call)")
            st.bar_chart(df_filtered['After RCP Status'].value_counts())
            
            # --- MAIN ANALYSIS ---
            st.header("📈 Time Blocks vs After Call Status")

            if time_granularity == '30 minutes':
                col_block_1st = '1ST COL 30min Block'
                col_block_rcp = 'RCP COL 30min Block'
            else:
                col_block_1st = '1ST COL 2h Block'
                col_block_rcp = 'RCP COL 2h Block'

            # --- ANALYSIS 1: 1ST Call ---
            st.subheader(f"Analysis 1: {time_granularity} Blocks vs. Status (1ST Call)")
            
            df_analysis_1 = df_filtered.dropna(subset=[col_block_1st, 'After 1ST status'])
            if not df_analysis_1.empty:
                freq_detailed = pd.crosstab(df_analysis_1[col_block_1st], df_analysis_1['After 1ST status'])
                no_show_statuses = [col for col in ['Cancelled', 'No-Show'] if col in freq_detailed.columns]
                show_up_statuses = [col for col in freq_detailed.columns if col not in no_show_statuses]
                
                freq_detailed['Grand Total'] = freq_detailed.sum(axis=1)
                freq_detailed['No Show'] = freq_detailed[no_show_statuses].sum(axis=1)
                freq_detailed['Showed Up'] = freq_detailed[show_up_statuses].sum(axis=1)
                freq_detailed['Showed Up %'] = (freq_detailed['Showed Up'] / freq_detailed['Grand Total']) * 100
                freq_detailed['No Show %'] = (freq_detailed['No Show'] / freq_detailed['Grand Total']) * 100
                freq_detailed['Weight %'] = (freq_detailed['Grand Total'] / freq_detailed['Grand Total'].sum()) * 100
                
                total_row = freq_detailed.sum().rename('Grand Total')
                total_row['Showed Up %'] = (total_row['Showed Up'] / total_row['Grand Total']) * 100
                total_row['No Show %'] = (total_row['No Show'] / total_row['Grand Total']) * 100
                total_row['Weight %'] = 100.0
                freq_detailed = pd.concat([freq_detailed, total_row.to_frame().T])
                
                count_cols = [col for col in df_analysis_1['After 1ST status'].unique() if col in freq_detailed.columns]
                display_cols = count_cols + ['Grand Total', 'Showed Up %', 'No Show %', 'Weight %']
                
                styler = freq_detailed[display_cols].style \
                    .format("{:.2f}%", subset=['Showed Up %', 'No Show %', 'Weight %']) \
                    .format("{:,.0f}", subset=count_cols + ['Grand Total'], na_rep="") \
                    .background_gradient(cmap='Blues', subset=count_cols + ['Grand Total']) \
                    .background_gradient(cmap='RdYlGn', subset=['Showed Up %'], vmin=0, vmax=100) \
                    .background_gradient(cmap='RdYlGn_r', subset=['No Show %'], vmin=0, vmax=100)
                st.dataframe(styler, use_container_width=True)
            else:
                st.info("Not enough data for Analysis 1 with the current filters.")

            # --- ANALYSIS 2: RCP Call ---
            st.subheader(f"Analysis 2: {time_granularity} Blocks vs. Status (RCP Call)")
            
            df_analysis_2 = df_filtered.dropna(subset=[col_block_rcp, 'After RCP Status'])
            if not df_analysis_2.empty:
                freq_detailed_2 = pd.crosstab(df_analysis_2[col_block_rcp], df_analysis_2['After RCP Status'])
                no_show_statuses_2 = [col for col in ['Cancelled', 'No-Show', 'No-show'] if col in freq_detailed_2.columns]
                show_up_statuses_2 = [col for col in freq_detailed_2.columns if col not in no_show_statuses_2]

                freq_detailed_2['Grand Total'] = freq_detailed_2.sum(axis=1)
                freq_detailed_2['No Show'] = freq_detailed_2[no_show_statuses_2].sum(axis=1)
                freq_detailed_2['Showed Up'] = freq_detailed_2[show_up_statuses_2].sum(axis=1)
                freq_detailed_2['Showed Up %'] = (freq_detailed_2['Showed Up'] / freq_detailed_2['Grand Total']) * 100
                freq_detailed_2['No Show %'] = (freq_detailed_2['No Show'] / freq_detailed_2['Grand Total']) * 100
                freq_detailed_2['Weight %'] = (freq_detailed_2['Grand Total'] / freq_detailed_2['Grand Total'].sum()) * 100
                
                total_row_2 = freq_detailed_2.sum().rename('Grand Total')
                total_row_2['Showed Up %'] = (total_row_2['Showed Up'] / total_row_2['Grand Total']) * 100
                total_row_2['No Show %'] = (total_row_2['No Show'] / total_row_2['Grand Total']) * 100
                total_row_2['Weight %'] = 100.0
                freq_detailed_2 = pd.concat([freq_detailed_2, total_row_2.to_frame().T])
                
                count_cols_2 = [col for col in df_analysis_2['After RCP Status'].unique() if col in freq_detailed_2.columns]
                display_cols_2 = count_cols_2 + ['Grand Total', 'Showed Up %', 'No Show %', 'Weight %']
                
                styler_2 = freq_detailed_2[display_cols_2].style \
                    .format("{:.2f}%", subset=['Showed Up %', 'No Show %', 'Weight %']) \
                    .format("{:,.0f}", subset=count_cols_2 + ['Grand Total'], na_rep="") \
                    .background_gradient(cmap='Blues', subset=count_cols_2 + ['Grand Total']) \
                    .background_gradient(cmap='RdYlGn', subset=['Showed Up %'], vmin=0, vmax=100) \
                    .background_gradient(cmap='RdYlGn_r', subset=['No Show %'], vmin=0, vmax=100)
                st.dataframe(styler_2, use_container_width=True)
            else:
                st.info("Not enough data for Analysis 2 with the current filters.")

            # --- DISPLAY FILTERED DATA ---
            with st.expander("View full filtered data"):
                st.dataframe(df_filtered)
