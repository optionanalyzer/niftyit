import streamlit as st
import pandas as pd
import requests
import urllib.parse
from datetime import datetime
import pytz
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objects as go

# ===================================================================
# ⚠️ HARDCODE YOUR ACCESS TOKEN HERE 
# ===================================================================
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzTUJDMzIiLCJqdGkiOiI2YTc1NGVjMTdmZDBhOTQ2ODkyZTc5N2QiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4NjA3Mjc2OSwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzg2MTQwMDAwfQ.9sVQbkro78JaiU7H2HLugJqaFgB-xV7SnH2wQyLx6fw" 

# ===================================================================
# 📲 TELEGRAM ALERT CONFIGURATION
# ===================================================================
TELEGRAM_BOT_TOKEN = "8968266056:AAFlTouDWGZQInTpp3SFEZINw3Nj8YL5cxI"
TELEGRAM_CHAT_ID = "-5311750328"

def send_telegram_alert(message):
    """Fires a Telegram message asynchronously to prevent Streamlit UI lag."""
    if TELEGRAM_BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload, timeout=2) 
    except Exception:
        pass

# ===================================================================
# 🚀 INITIALIZATION ALERT (SERVER-LEVEL CACHE)
# ===================================================================
@st.cache_resource
def notify_server_start():
    send_telegram_alert("🚀 *FnO Terminal Started Successfully*")
    return True

# This will only execute once per server boot, completely ignoring page refreshes
notify_server_start()
        
# -------------------------------------------------------------------
# 0. PAGE CONFIGURATION & AUTO REFRESH
# -------------------------------------------------------------------
st.set_page_config(page_title="FnO Intelligence Terminal", layout="wide")

# Run a seamless background refresh every 15 seconds
st_autorefresh(interval=15000, limit=None, key="fno_terminal_refresh")

# -------------------------------------------------------------------
# 1. FETCH AND PROCESS UPSTOX INSTRUMENT DATA
# -------------------------------------------------------------------
@st.cache_data(show_spinner="Fetching Master Instrument List from Upstox...")
def load_instruments():
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    df = pd.read_csv(url)
    
    fno_df = df[
        df['instrument_key'].str.startswith('NSE_FO|') | 
        df['instrument_key'].str.startswith('NSE_INDEX|') |
        df['instrument_key'].str.startswith('BSE_FO|') |
        df['instrument_key'].str.startswith('BSE_INDEX|')
    ]
    
    unique_symbols = fno_df['name'].dropna().unique().tolist()
    unique_symbols.sort()
    
    return df, fno_df, unique_symbols

master_df, fno_df, fno_symbols = load_instruments()

# -------------------------------------------------------------------
# 2. CORE API DATA FETCHERS
# -------------------------------------------------------------------
def get_expiries_for_symbol(symbol, df):
    symbol_data = df[df['name'] == symbol]
    expiries = symbol_data['expiry'].dropna().unique().tolist()
    return sorted(expiries)

def get_underlying_ltp(instrument_key, access_token):
    safe_key = urllib.parse.quote(instrument_key)
    url = f"https://api.upstox.com/v3/market-quote/ltp?instrument_key={safe_key}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {access_token}'}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json().get('data', {})
            if data:
                return list(data.values())[0].get('last_price')
    except Exception:
        pass
    return None

def fetch_live_vix(access_token):
    if not access_token or access_token == "YOUR_UPSTOX_ACCESS_TOKEN_HERE":
        return "N/A"
        
    safe_key = urllib.parse.quote("NSE_INDEX|India VIX")
    url = f"https://api.upstox.com/v3/market-quote/ltp?instrument_key={safe_key}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {access_token}'}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json().get('data', {})
            if data:
                ltp = list(data.values())[0].get('last_price')
                if ltp is not None:
                    return str(ltp)
        return f"Err: {response.status_code}"
    except Exception:
        return "N/A"

def get_option_chain_data(instrument_key, expiry_date, access_token, spot_price):
    if not access_token or access_token == "YOUR_UPSTOX_ACCESS_TOKEN_HERE" or not spot_price:
        return None, None

    safe_key = urllib.parse.quote(instrument_key)
    url = f"https://api.upstox.com/v2/option/chain?instrument_key={safe_key}&expiry_date={expiry_date}"
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return None, None
        
        data = response.json().get('data', [])
        if not data:
            return None, None

        chain_df = pd.json_normalize(data)
        chain_df.fillna(0, inplace=True)
        
        chain_df['distance_from_spot'] = abs(chain_df['strike_price'] - spot_price)
        atm_index = chain_df['distance_from_spot'].idxmin()
        atm_strike = chain_df.loc[atm_index, 'strike_price']

        return chain_df, atm_strike
    except Exception:
        return None, None

# -------------------------------------------------------------------
# 3. TERMINAL HEADER USER INTERFACE
# -------------------------------------------------------------------
st.markdown("### 📊 FnO Intelligence Terminal")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns([1.5, 1.5, 1, 1, 1])

with col1:
    selected_symbol = st.selectbox("Select Instrument", options=fno_symbols, index=None, placeholder="Search for an instrument...", label_visibility="collapsed")
with col2:
    available_expiries = get_expiries_for_symbol(selected_symbol, fno_df) if selected_symbol else []
    selected_expiry = st.selectbox("Select Expiry", options=available_expiries if available_expiries else ["No Expiry Found"], label_visibility="collapsed")

INDEX_MAP = {
    "NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX", "BANKEX": "BSE_INDEX|BANKEX"
}

if selected_symbol in INDEX_MAP: target_instrument_key = INDEX_MAP[selected_symbol]
elif selected_symbol:
    eq_rows = master_df[(master_df['name'] == selected_symbol) & (master_df['instrument_key'].str.startswith('NSE_EQ|'))]
    target_instrument_key = eq_rows['instrument_key'].iloc[0] if not eq_rows.empty else ""
else: target_instrument_key = ""

# -------------------------------------------------------------------
# 4. EXECUTE DATA STREAMS (MACRO vs MICRO)
# -------------------------------------------------------------------
live_vix = fetch_live_vix(ACCESS_TOKEN)
underlying_spot = get_underlying_ltp(target_instrument_key, ACCESS_TOKEN) if target_instrument_key else None
chain_df, atm_strike = get_option_chain_data(target_instrument_key, selected_expiry, ACCESS_TOKEN, underlying_spot) if available_expiries and target_instrument_key else (None, None)

live_pcr = None
micro_pcr = None
active_strikes_df = pd.DataFrame()

if chain_df is not None:
    atm_idx = chain_df['distance_from_spot'].idxmin()
    
    # MACRO PCR (ATM ± 5) - For overarching daily trend
    active_strikes_df = chain_df.iloc[max(0, atm_idx - 5):min(len(chain_df) - 1, atm_idx + 5) + 1].copy()
    total_call_oi = active_strikes_df.get('call_options.market_data.oi', pd.Series([0])).sum()
    total_put_oi = active_strikes_df.get('put_options.market_data.oi', pd.Series([0])).sum()
    live_pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 99.9

    # MICRO PCR (ATM ± 2) - For instant, hyper-local momentum
    micro_strikes_df = chain_df.iloc[max(0, atm_idx - 2):min(len(chain_df) - 1, atm_idx + 2) + 1].copy()
    micro_call_oi = micro_strikes_df.get('call_options.market_data.oi', pd.Series([0])).sum()
    micro_put_oi = micro_strikes_df.get('put_options.market_data.oi', pd.Series([0])).sum()
    micro_pcr = round(micro_put_oi / micro_call_oi, 2) if micro_call_oi > 0 else 99.9

with col3:
    if live_pcr is not None:
        pcr_color = "normal" if live_pcr >= 1 else "inverse"
        st.metric(label="MACRO PCR (±5)", value=live_pcr, delta=f"ATM: {int(atm_strike)}", delta_color=pcr_color)
    else:
        st.metric(label="MACRO PCR (±5)", value="---", delta="No Data", delta_color="off")

with col4:
    if micro_pcr is not None:
        mpcr_color = "normal" if micro_pcr >= 1 else "inverse"
        st.metric(label="MICRO PCR (±2)", value=micro_pcr, delta="Hyper-Local", delta_color=mpcr_color)
    else:
        st.metric(label="MICRO PCR (±2)", value="---", delta="No Data", delta_color="off")

with col5:
    st.metric(label="INDIA VIX", value=live_vix)

# -------------------------------------------------------------------
# 5. ROLLING INTRADAY OI MOMENTUM TRACKER (3-Minute Auto-Window)
# -------------------------------------------------------------------
import time

if not active_strikes_df.empty:
    state_prefix = f"{target_instrument_key}_{selected_expiry}"
    
    # 1. Reset memory cleanly if you switch instruments or expiries
    if st.session_state.get('oi_instrument_tracker') != state_prefix:
        st.session_state.oi_rolling_history = []
        st.session_state.oi_instrument_tracker = state_prefix

    if 'oi_rolling_history' not in st.session_state:
        st.session_state.oi_rolling_history = []
        
    current_timestamp = time.time()
    current_snapshot = {}

    # 2. Capture the current exact micro-state of the Option Chain
    for index, row in active_strikes_df.iterrows():
        strike = row['strike_price']
        current_snapshot[strike] = {
            'call_oi': row.get('call_options.market_data.oi', 0),
            'put_oi': row.get('put_options.market_data.oi', 0)
        }

    # 3. Append to our rolling memory
    st.session_state.oi_rolling_history.append({
        'time': current_timestamp,
        'data': current_snapshot
    })

    # 4. THE MAGIC: Purge any data older than 3 minutes (180 seconds)
    # Adjust the 180 below if you want a 5-min (300) or 1-min (60) window
    lookback_window = 180 
    st.session_state.oi_rolling_history = [
        snap for snap in st.session_state.oi_rolling_history 
        if current_timestamp - snap['time'] <= lookback_window
    ]

    # 5. The baseline is always dynamically anchored to the oldest snapshot in the window
    baseline_snapshot = st.session_state.oi_rolling_history[0]['data']

    call_chg_list = []
    put_chg_list = []

    for index, row in active_strikes_df.iterrows():
        strike = row['strike_price']
        curr_call = row.get('call_options.market_data.oi', 0)
        curr_put = row.get('put_options.market_data.oi', 0)
        
        # Fallback to current OI if the strike is newly active and wasn't in the baseline
        base_call = baseline_snapshot.get(strike, {}).get('call_oi', curr_call)
        base_put = baseline_snapshot.get(strike, {}).get('put_oi', curr_put)
        
        call_chg_list.append(curr_call - base_call)
        put_chg_list.append(curr_put - base_put)
        
    # Attach rolling data globally for the rest of the app to use
    active_strikes_df['call_chg_oi'] = call_chg_list
    active_strikes_df['put_chg_oi'] = put_chg_list

# -------------------------------------------------------------------
# 6. GLOBAL DATA PREPARATION 
# -------------------------------------------------------------------
# Calculate dependent variables here so blocks can be rendered in any order
greeks_display_df = pd.DataFrame()
resistance_strike = 0
support_strike = 0
battleground_strike = 0
current_vix = 15.0

if chain_df is not None and not active_strikes_df.empty:
    # --- Greeks Data Prep ---
    required_cols = {
        'call_options.option_greeks.iv': 'Call IV',
        'call_options.option_greeks.delta': 'Call Delta',
        'call_options.option_greeks.gamma': 'Call Gamma',
        'call_options.option_greeks.theta': 'Call Theta',
        'call_options.option_greeks.vega': 'Call Vega',
        'strike_price': 'STRIKE',
        'put_options.option_greeks.iv': 'Put IV',
        'put_options.option_greeks.delta': 'Put Delta',
        'put_options.option_greeks.gamma': 'Put Gamma',
        'put_options.option_greeks.theta': 'Put Theta',
        'put_options.option_greeks.vega': 'Put Vega',
    }
    available_cols = [c for c in required_cols.keys() if c in active_strikes_df.columns]
    greeks_display_df = active_strikes_df[available_cols].rename(columns=required_cols).round(4)

    # --- S&R and Battleground Prep ---
    try:
        res_idx = active_strikes_df['call_options.market_data.oi'].idxmax()
        resistance_strike = active_strikes_df.loc[res_idx, 'strike_price']
        sup_idx = active_strikes_df['put_options.market_data.oi'].idxmax()
        support_strike = active_strikes_df.loc[sup_idx, 'strike_price']
    except Exception:
        resistance_strike, support_strike = 0, 0

    active_strikes_df['Total_Activity'] = active_strikes_df.get('call_options.market_data.oi', 0) + active_strikes_df.get('put_options.market_data.oi', 0)
    try:
        bg_idx = active_strikes_df['Total_Activity'].idxmax()
        battleground_strike = active_strikes_df.loc[bg_idx, 'strike_price'] if pd.notna(bg_idx) else 0
    except Exception:
        battleground_strike = 0

    # --- Time-Series & VIX Prep ---
    try:
        current_vix = float(live_vix)
    except Exception:
        current_vix = 15.0

    if 'history_df' not in st.session_state:
        st.session_state.history_df = pd.DataFrame(columns=['Time_IST', 'PCR', 'VIX'])
    ist = pytz.timezone('Asia/Kolkata')
    current_time_str = datetime.now(ist).strftime('%H:%M:%S')
    
    new_data = pd.DataFrame([{'Time_IST': current_time_str, 'PCR': live_pcr, 'VIX': current_vix}])
    st.session_state.history_df = pd.concat([st.session_state.history_df, new_data], ignore_index=True)
    st.session_state.history_df = st.session_state.history_df.tail(20)


# ===================================================================
# UI RENDERING - NEW LAYOUT ORDER
# ===================================================================

# -------------------------------------------------------------------
# 7. LIVE OPTION CHAIN DYNAMIC TABLE (ATM ± 5 Strikes)
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.markdown("---")
    
    st.markdown("#### 🔗 Rolling Position Tracker (3-Min Shift)")

    oc_required_cols = {
        'put_options.market_data.ltp': 'Put LTP',
        'put_chg_oi': 'Bull Activity',
        'put_options.market_data.oi': 'Bull Positions',
        'strike_price': 'STRIKE',
        'call_options.market_data.oi': 'Bear Positions',
        'call_chg_oi': 'Bear Activity',
        'call_options.market_data.ltp': 'Call LTP'        
    }

    oc_available = [c for c in oc_required_cols.keys() if c in active_strikes_df.columns]
    oc_display_df = active_strikes_df[oc_available].rename(columns=oc_required_cols)

    ordered_cols = ['Bull Positions', 'Bull Activity', 'Call LTP', 'STRIKE', 'Put LTP', 'Bear Activity', 'Bear Positions']
    final_cols = [c for c in ordered_cols if c in oc_display_df.columns]
    oc_display_df = oc_display_df[final_cols]

    for c in final_cols:
        oc_display_df[c] = pd.to_numeric(oc_display_df[c], errors='coerce').fillna(0)

    def style_oc_table(row):
        styles = []
        is_atm = (row['STRIKE'] == atm_strike)
        base_style = 'background-color: rgba(66, 153, 225, 0.3);' if is_atm else ''

        for col in row.index:
            val = row[col]
            if col in ['Bear Activity', 'Bull Activity']:
                if val > 0:
                    styles.append('background-color: #1dc973; color: white;')
                elif val < 0:
                    styles.append('background-color: #ff4b4b; color: white;')
                else:
                    styles.append(base_style)
            else:
                styles.append(base_style)
        return styles

    def format_chg(val):
        if val > 0: return f"+{int(val)}"
        elif val < 0: return f"{int(val)}"
        else: return "0"

    format_dict = {}
    for c in final_cols:
        if 'Chg OI' in c:
            format_dict[c] = format_chg
        elif 'LTP' in c:
            format_dict[c] = '{:.2f}'
        else:
            format_dict[c] = '{:.0f}'

    styled_oc = oc_display_df.style.apply(style_oc_table, axis=1).format(format_dict)
    
    # --- NEW: Force Header Center Alignment via Pandas Styler CSS ---
    styled_oc = styled_oc.set_table_styles([
        dict(selector='th', props=[('text-align', 'center !important')])
    ], overwrite=False)

    # Streamlit Column Configuration for hard Center Alignment of data cells
    center_alignment_oc = {col: st.column_config.Column(alignment="center") for col in oc_display_df.columns}

    st.dataframe(
        styled_oc, 
        use_container_width=True, 
        hide_index=True, 
        height=430,
        column_config=center_alignment_oc
    )

    # --- SUMMARY ROW (ACTIVITY AVERAGES WITH DELTA TRACKING) ---
    bull_activity_avg = oc_display_df['Bull Activity'].sum() / 11
    bear_activity_avg = oc_display_df['Bear Activity'].sum() / 11

    # Unique session state keys to reset properly if the user changes the instrument/expiry
    state_key_bull = f"prev_bull_avg_{target_instrument_key}_{selected_expiry}"
    state_key_bear = f"prev_bear_avg_{target_instrument_key}_{selected_expiry}"

    # Initialize state if not present
    if state_key_bull not in st.session_state:
        st.session_state[state_key_bull] = bull_activity_avg
    if state_key_bear not in st.session_state:
        st.session_state[state_key_bear] = bear_activity_avg

    # Calculate difference from the last recorded state
    bull_diff = bull_activity_avg - st.session_state[state_key_bull]
    bear_diff = bear_activity_avg - st.session_state[state_key_bear]

    # Update state for the next refresh cycle
    st.session_state[state_key_bull] = bull_activity_avg
    st.session_state[state_key_bear] = bear_activity_avg

    # Helper function to render the up/down arrows
    def get_diff_html(diff):
        if diff > 0:
            return f"<span style='color:#1dc973; font-size:13px; font-weight:600;'>▲ +{int(diff):,}</span>"
        elif diff < 0:
            return f"<span style='color:#ff4b4b; font-size:13px; font-weight:600;'>▼ {int(diff):,}</span>"
        else:
            return f"<span style='color:#888888; font-size:13px; font-weight:600;'>▬ 0</span>"
    
    st.write("") # Tiny spacer
    sum_col1, sum_col2 = st.columns(2)
    
    with sum_col1:
        st.markdown(f"""
        <div style="background-color:#1e1e1e; padding:12px; border-radius:8px; text-align:center; border: 1px solid #333;">
            <p style="color:#1dc973; margin:0; font-weight:bold; font-size:12px; text-align:center;">AVG BULLS</p>
            <h4 style="margin:5px 0;">{int(bull_activity_avg):,}</h4>
            <div>{get_diff_html(bull_diff)}</div>
        </div>
        """, unsafe_allow_html=True)
        
    with sum_col2:
        st.markdown(f"""
        <div style="background-color:#1e1e1e; padding:12px; border-radius:8px; text-align:center; border: 1px solid #333;">
            <p style="color:#ff4b4b; margin:0; font-weight:bold; font-size:12px; text-align:center;">AVG BEARS</p>
            <h4 style="margin:5px 0;">{int(bear_activity_avg):,}</h4>
            <div>{get_diff_html(bear_diff)}</div>
        </div>
        """, unsafe_allow_html=True)

# -------------------------------------------------------------------
# 8. POSITION BUILDUP / POSITION SHIFT
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.markdown("---")
    color_call = 'rgba(255, 75, 75, 1)' 
    color_put = 'rgba(29, 201, 115, 1)' 

    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.markdown("<h5 style='text-align: center;'>POSITION BUILDUP</h5>", unsafe_allow_html=True)
        fig_oi = go.Figure()
        fig_oi.add_trace(go.Bar(
            x=active_strikes_df['strike_price'], 
            y=active_strikes_df.get('call_options.market_data.oi', pd.Series([0]*len(active_strikes_df))),
            name='CALL', marker_color=color_call
        ))
        fig_oi.add_trace(go.Bar(
            x=active_strikes_df['strike_price'], 
            y=active_strikes_df.get('put_options.market_data.oi', pd.Series([0]*len(active_strikes_df))),
            name='PUT', marker_color=color_put
        ))
        fig_oi.update_layout(
            barmode='group', margin=dict(l=0, r=0, t=30, b=0),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(type='category', tickangle=-45) 
        )
        st.plotly_chart(fig_oi, use_container_width=True, config={'displayModeBar': False}, key="chart_oi_buildup")

    with chart_col2:
        st.markdown("<h5 style='text-align: center;'>POSITION SHIFT (INTRADAY)</h5>", unsafe_allow_html=True)
        fig_chg = go.Figure()
        fig_chg.add_trace(go.Bar(
            x=active_strikes_df['strike_price'], 
            y=active_strikes_df['call_chg_oi'], 
            name='CALL', marker_color=color_call
        ))
        fig_chg.add_trace(go.Bar(
            x=active_strikes_df['strike_price'], 
            y=active_strikes_df['put_chg_oi'], 
            name='PUT', marker_color=color_put
        ))
        fig_chg.update_layout(
            barmode='group', margin=dict(l=0, r=0, t=30, b=0),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(type='category', tickangle=-45)
        )
        st.plotly_chart(fig_chg, use_container_width=True, config={'displayModeBar': False}, key="chart_oi_change")


# -------------------------------------------------------------------
# 9. SUPPORT / RESISTANCE / BATTLEGROUND
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.write("") 
    box_col1, box_col2, box_col3 = st.columns(3)
    
    with box_col1:
        st.markdown(f"""
        <div style="background-color:#1e1e1e; padding:15px; border-radius:10px; text-align:center;">
            <p style="color:#ff4b4b; margin:0; font-weight:bold; font-size:12px;">ACTIVE RES (CHG)</p>
            <h3 style="margin:0;">{int(resistance_strike) if resistance_strike else 0}</h3>
        </div>
        """, unsafe_allow_html=True)
        
    with box_col2:
        st.markdown(f"""
        <div style="background-color:#1e1e1e; padding:15px; border-radius:10px; text-align:center;">
            <p style="color:#1dc973; margin:0; font-weight:bold; font-size:12px;">ACTIVE SUP (CHG)</p>
            <h3 style="margin:0;">{int(support_strike) if support_strike else 0}</h3>
        </div>
        """, unsafe_allow_html=True)
        
    with box_col3:
        st.markdown(f"""
        <div style="background-color:#1e1e1e; padding:15px; border-radius:10px; text-align:center;">
            <p style="color:#faca2b; margin:0; font-weight:bold; font-size:12px;">BATTLEGROUND</p>
            <h3 style="margin:0;">{int(battleground_strike)}</h3>
        </div>
        """, unsafe_allow_html=True)


# -------------------------------------------------------------------
# 10. MARKET TREND / FEAR INDEX
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.markdown("---")
    bull_pct = min(max((live_pcr - 0.5) / 1.0, 0), 1) * 100
    row6_col1, row6_col2 = st.columns(2)

    with row6_col1:
        st.markdown("<h5 style='text-align: center;'>MARKET TREND</h5>", unsafe_allow_html=True)
        fig_pcr = go.Figure()
        fig_pcr.add_trace(go.Scatter(
            x=st.session_state.history_df['Time_IST'], y=st.session_state.history_df['PCR'],
            mode='lines+markers', line=dict(color='#a855f7', width=3) 
        ))
        fig_pcr.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=True, gridcolor='#333'), yaxis=dict(showgrid=True, gridcolor='#333')
        )
        st.plotly_chart(fig_pcr, use_container_width=True, config={'displayModeBar': False}, key="chart_pcr_trend")

    with row6_col2:
        st.markdown("<h5 style='text-align: center;'>FEAR INDEX</h5>", unsafe_allow_html=True)
        fig_vix = go.Figure()
        fig_vix.add_trace(go.Scatter(
            x=st.session_state.history_df['Time_IST'], y=st.session_state.history_df['VIX'],
            mode='lines+markers', line=dict(color='#1dc973', width=3) 
        ))
        fig_vix.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=True, gridcolor='#333'), yaxis=dict(showgrid=True, gridcolor='#333')
        )
        st.plotly_chart(fig_vix, use_container_width=True, config={'displayModeBar': False}, key="chart_vix_trend")


# -------------------------------------------------------------------
# 11. ADVANCED ALGORITHMIC TRADE SIGNAL ENGINE
# -------------------------------------------------------------------
if chain_df is not None and live_pcr is not None and live_pcr != 99.9:
    st.markdown("---")
    st.markdown("#### 🤖 Aggressive Scalp Engine")

    # --- ENHANCED STATE MANAGEMENT ---
    if 'active_trade' not in st.session_state: st.session_state.active_trade = None
    if 'trade_details' not in st.session_state: st.session_state.trade_details = {}
    
    if 'pending_signal' not in st.session_state: st.session_state.pending_signal = None
    if 'pending_ticks' not in st.session_state: st.session_state.pending_ticks = 0
    
    if 'trailing_stop' not in st.session_state: st.session_state.trailing_stop = 0
    if 'peak_spot' not in st.session_state: st.session_state.peak_spot = 0
    if 'entry_spot' not in st.session_state: st.session_state.entry_spot = 0
    if 'trail_dist' not in st.session_state: st.session_state.trail_dist = 0

    # 1. Advanced Trend Calculations (Hysteresis / 2-Step Confirmation)
    if 'prev_distinct_pcr' not in st.session_state:
        st.session_state.prev_distinct_pcr = micro_pcr
        st.session_state.pcr_step_count = 0
        st.session_state.confirmed_pcr_trend = "RISING ↗️" # Default fallback
        
    if 'prev_distinct_vix' not in st.session_state:
        st.session_state.prev_distinct_vix = current_vix
        st.session_state.vix_step_count = 0
        st.session_state.confirmed_vix_trend = "FALLING ↘️" # Default fallback

    # --- PCR Step Logic ---
    if micro_pcr > st.session_state.prev_distinct_pcr:
        if st.session_state.pcr_step_count > 0:
            st.session_state.pcr_step_count += 1
        else:
            st.session_state.pcr_step_count = 1
        st.session_state.prev_distinct_pcr = micro_pcr
        
    elif micro_pcr < st.session_state.prev_distinct_pcr:
        if st.session_state.pcr_step_count < 0:
            st.session_state.pcr_step_count -= 1
        else:
            st.session_state.pcr_step_count = -1
        st.session_state.prev_distinct_pcr = micro_pcr

    # Apply PCR Trend Change ONLY if 2 consecutive steps occur
    if st.session_state.pcr_step_count >= 2:
        st.session_state.confirmed_pcr_trend = "RISING ↗️"
    elif st.session_state.pcr_step_count <= -2:
        st.session_state.confirmed_pcr_trend = "FALLING ↘️"

    # --- VIX Step Logic ---
    if current_vix > st.session_state.prev_distinct_vix:
        if st.session_state.vix_step_count > 0:
            st.session_state.vix_step_count += 1
        else:
            st.session_state.vix_step_count = 1
        st.session_state.prev_distinct_vix = current_vix
        
    elif current_vix < st.session_state.prev_distinct_vix:
        if st.session_state.vix_step_count < 0:
            st.session_state.vix_step_count -= 1
        else:
            st.session_state.vix_step_count = -1
        st.session_state.prev_distinct_vix = current_vix

    # Apply VIX Trend Change ONLY if 2 consecutive steps occur
    if st.session_state.vix_step_count >= 2:
        st.session_state.confirmed_vix_trend = "RISING ↗️"
    elif st.session_state.vix_step_count <= -2:
        st.session_state.confirmed_vix_trend = "FALLING ↘️"

    # Lock in the trends for the engine (NO FLAT STATE)
    pcr_trend = st.session_state.confirmed_pcr_trend
    vix_trend = st.session_state.confirmed_vix_trend

    # 2. Dynamic Buffer Calculation
    try:
        atm_row = greeks_display_df[greeks_display_df['STRIKE'] == atm_strike]
        if not atm_row.empty:
            avg_iv = (atm_row['Call IV'].values[0] + atm_row['Put IV'].values[0]) / 2
        else:
            avg_iv = current_vix

        daily_move_pct = (avg_iv / 15.87) / 100
        buffer = underlying_spot * (daily_move_pct * 0.25)
    except Exception:
        buffer = underlying_spot * 0.0025

    # 3. SIGNAL GENERATION & MANAGEMENT
    signal_action = "NEUTRAL (Wait for Setup) 🟡"
    suggested_strike = st.session_state.trade_details.get('strike', 'N/A')
    target_delta = st.session_state.trade_details.get('delta', 'N/A')

    # Get live time to evaluate 3:15 logic
    ist_tz = pytz.timezone('Asia/Kolkata')
    current_time_ist_obj = datetime.now(ist_tz)
    is_closing_time = current_time_ist_obj.hour == 15 and current_time_ist_obj.minute >= 15

    if resistance_strike > 0 and support_strike > 0 and not greeks_display_df.empty:
        
        # ==========================================================
        # 🚨 3:15 PM AUTO-SQUARE OFF LOGIC
        # ==========================================================
        if is_closing_time and st.session_state.active_trade is not None:
            signal_action = f"EXIT {st.session_state.active_trade} 🛑 (3:15 PM Auto-Square-Off)"
            send_telegram_alert(f"⚠️ *AUTO SQUARE-OFF* ⚠️\n3:15 PM Liquidation triggered. Closed {st.session_state.active_trade} position.")
            st.session_state.active_trade = None
            st.session_state.pending_signal = None
            st.session_state.pending_ticks = 0

        # --- STATE A: WE ARE IN AN ACTIVE TRADE (RATCHET MODE) ---
        elif st.session_state.active_trade == 'CALL':
            if underlying_spot > st.session_state.peak_spot:
                st.session_state.peak_spot = underlying_spot
                # 🚀 SCALP RATCHET: Tighten leash if spot moves up by initial buffer
                if (st.session_state.peak_spot - st.session_state.entry_spot) > buffer:
                    st.session_state.trail_dist = buffer * 0.5
                st.session_state.trailing_stop = max(st.session_state.trailing_stop, underlying_spot - st.session_state.trail_dist)

            if underlying_spot <= st.session_state.trailing_stop:
                signal_action = "EXIT CALL 🛑 (Trailing Stop Hit)"
                st.session_state.active_trade = None 
            else:
                signal_action = f"HOLD CALL 🟢 (SL: {st.session_state.trailing_stop:.2f})"

        elif st.session_state.active_trade == 'PUT':
            if underlying_spot < st.session_state.peak_spot:
                st.session_state.peak_spot = underlying_spot
                # 🚀 SCALP RATCHET: Tighten leash if spot moves down by initial buffer
                if (st.session_state.entry_spot - st.session_state.peak_spot) > buffer:
                    st.session_state.trail_dist = buffer * 0.5 
                st.session_state.trailing_stop = min(st.session_state.trailing_stop, underlying_spot + st.session_state.trail_dist)

            if underlying_spot >= st.session_state.trailing_stop:
                signal_action = "EXIT PUT 🛑 (Trailing Stop Hit)"
                st.session_state.active_trade = None 
            else:
                signal_action = f"HOLD PUT 🔴 (SL: {st.session_state.trailing_stop:.2f})"

        # --- STATE B: WE ARE FLAT (HUNTING FOR ENTRIES) ---
        else:
            raw_signal = None
            raw_strike = None
            raw_delta = None
            
            # 1. Slice the Option Chain for Position Shift Momentum
            otm_strikes = active_strikes_df[active_strikes_df['strike_price'] > atm_strike]
            itm_atm_strikes = active_strikes_df[active_strikes_df['strike_price'] <= atm_strike]
            
            # 2. Calculate Directional Activity Sums
            otm_bull_sum = otm_strikes['put_chg_oi'].sum()
            otm_bear_sum = otm_strikes['call_chg_oi'].sum()
            
            itm_bear_sum = itm_atm_strikes['call_chg_oi'].sum()
            itm_bull_sum = itm_atm_strikes['put_chg_oi'].sum()
            
            # 3. Retrieve Averages (From Section 7)
            bull_avg = st.session_state.get(f"prev_bull_avg_{target_instrument_key}_{selected_expiry}", 0)
            bear_avg = st.session_state.get(f"prev_bear_avg_{target_instrument_key}_{selected_expiry}", 0)

            # --- AGGRESSIVE SCALPING ENTRY LOGIC ---
            
            # LONG (CE) SETUP
            if (bull_avg > bear_avg) and (pcr_trend == "RISING ↗️") and (vix_trend == "FALLING ↘️") and (otm_bull_sum > otm_bear_sum):
                raw_signal = "CALL"
                closest_idx = (greeks_display_df['Call Delta'] - 0.55).abs().idxmin()
                raw_strike = f"{int(greeks_display_df.loc[closest_idx, 'STRIKE'])} CE"
                raw_delta = f"{greeks_display_df.loc[closest_idx, 'Call Delta']:.4f}"
                
            # SHORT (PE) SETUP
            elif (bear_avg > bull_avg) and (pcr_trend == "FALLING ↘️") and (vix_trend == "RISING ↗️") and (itm_bear_sum > itm_bull_sum):
                raw_signal = "PUT"
                closest_idx = (greeks_display_df['Put Delta'] - (-0.55)).abs().idxmin()
                raw_strike = f"{int(greeks_display_df.loc[closest_idx, 'STRIKE'])} PE"
                raw_delta = f"{greeks_display_df.loc[closest_idx, 'Put Delta']:.4f}"

            # Block new entries after 3:15 PM
            if raw_signal and not is_closing_time:
                if st.session_state.pending_signal == raw_signal:
                    st.session_state.pending_ticks += 1
                else:
                    st.session_state.pending_signal = raw_signal
                    st.session_state.pending_ticks = 1
                
                # If verified across 2 consecutive ticks (30 seconds of sustained momentum)
                if st.session_state.pending_ticks >= 2:
                    st.session_state.active_trade = raw_signal
                    st.session_state.trade_details = {'strike': raw_strike, 'delta': raw_delta}
                    suggested_strike = raw_strike
                    target_delta = raw_delta
                    
                    # Initialize Scalping Trailing Stop metrics (Tighter 1.0x buffer)
                    st.session_state.trail_dist = buffer * 1.0 
                    st.session_state.entry_spot = underlying_spot
                    st.session_state.peak_spot = underlying_spot
                    
                    if raw_signal == "CALL":
                        st.session_state.trailing_stop = underlying_spot - st.session_state.trail_dist
                    else:
                        st.session_state.trailing_stop = underlying_spot + st.session_state.trail_dist

                    # TELEGRAM ALERT BLOCK 
                    try:
                        strike_num = int(raw_strike.split()[0])
                        if raw_signal == "CALL":
                            entry_ltp = active_strikes_df.loc[active_strikes_df['strike_price'] == strike_num, 'call_options.market_data.ltp'].values[0]
                        else:
                            entry_ltp = active_strikes_df.loc[active_strikes_df['strike_price'] == strike_num, 'put_options.market_data.ltp'].values[0]
                        
                        sl_price = entry_ltp * 0.90
                        target_price = entry_ltp * 1.10
                        
                        alert_msg = (
                            f"⚡ *SCALP ALERT: VERIFIED SETUP*\n\n"
                            f"🟢 *Action:* BUY {raw_strike}\n"
                            f"💰 *Entry Premium:* ₹{entry_ltp:.2f}\n\n"
                            f"🎯 *Target Premium:* ₹{target_price:.2f} (+50%)\n"
                            f"🛑 *Premium SL:* ₹{sl_price:.2f} (-25%)\n\n"
                            f"📊 *Spot Trailing SL:* {st.session_state.trailing_stop:.2f}\n"
                            f"⚙️ *Delta:* {raw_delta}"
                        )
                        send_telegram_alert(alert_msg)
                    except Exception as e:
                        pass

                    st.session_state.pending_signal = None
                    st.session_state.pending_ticks = 0
                else:
                    signal_action = f"⏳ VERIFYING SCALP {raw_signal} (Tick {st.session_state.pending_ticks}/2)"
                    suggested_strike = raw_strike
                    target_delta = raw_delta
            else:
                st.session_state.pending_signal = None
                st.session_state.pending_ticks = 0
                suggested_strike = "N/A"
                target_delta = "N/A"

    # 4. RENDER UI METRICS
    col_a, col_b, col_c, col_d = st.columns(4)
    
    with col_a:
        st.info(f"**Action Engine:**\n### {signal_action}")
    with col_b:
        st.success(f"**Target Asset:**\n### {suggested_strike} (Δ {target_delta})")
    with col_c:
        st.warning(f"**Live S&R Levels:**\nRes: {int(resistance_strike)}\nSup: {int(support_strike)}\n*Zone: ±{int(buffer)} pts*")
    with col_d:
        st.metric("PCR Trend", value=pcr_trend)
        st.metric("VIX Trend", value=vix_trend)
        
    # Manual Clear
    if st.session_state.active_trade or st.session_state.pending_signal:
        if st.button("Reset Engine / Clear Trade"):
            st.session_state.active_trade = None
            st.session_state.pending_signal = None
            st.session_state.pending_ticks = 0
            st.rerun()

# -------------------------------------------------------------------
# 12. INTERACTIVE OPTION GREEKS TABLE
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.markdown("---")
    ist_tz_greeks = pytz.timezone('Asia/Kolkata')
    current_time_ist_str = datetime.now(ist_tz_greeks).strftime('%Y-%m-%d %H:%M:%S IST')
    
    st.markdown(f"#### Option Greek | ⏱️ {current_time_ist_str}")
    
    # 1. Grab Base Greeks and Merge LTPs from active_strikes_df
    greeks_cols = ['Call Delta', 'Call Gamma', 'Call Theta', 'STRIKE', 'Put Delta', 'Put Gamma', 'Put Theta']
    base_greeks_df = greeks_display_df[greeks_cols].copy()
    
    ltp_df = active_strikes_df[['strike_price', 'call_options.market_data.ltp', 'put_options.market_data.ltp']].copy()
    ltp_df.rename(columns={
        'strike_price': 'STRIKE',
        'call_options.market_data.ltp': 'Call LTP',
        'put_options.market_data.ltp': 'Put LTP'
    }, inplace=True)
    
    # Merge and perfectly order the columns
    base_greeks_df = pd.merge(base_greeks_df, ltp_df, on='STRIKE', how='left')
    display_cols = [
        'Call Delta', 'Call Gamma', 'Call Theta', 'Call LTP', 
        'STRIKE', 
        'Put LTP', 'Put Delta', 'Put Gamma', 'Put Theta'
    ]
    base_greeks_df = base_greeks_df[display_cols]
    
    # 2. State management to track previous values
    state_key_greeks = f"prev_greeks_{target_instrument_key}_{selected_expiry}"
    if state_key_greeks not in st.session_state:
        st.session_state[state_key_greeks] = {}
        
    prev_greeks = st.session_state[state_key_greeks]
    new_greeks_state = {}
    
    # 3. Create a formatted dataframe to hold the strings with arrows
    # Convert to 'object' dtype so Pandas allows string injection
    visual_greeks_df = base_greeks_df.astype(object)
    visual_greeks_df['STRIKE'] = visual_greeks_df['STRIKE'].astype(int) 
    
    metrics = [c for c in display_cols if c != 'STRIKE']
    
    for idx, row in base_greeks_df.iterrows():
        strike = int(row['STRIKE'])
        new_greeks_state[strike] = {}
        
        for col in metrics:
            curr_val = float(row[col])
            new_greeks_state[strike][col] = curr_val
            
            # Dynamically format: 2 decimals for Price (LTP), 4 decimals for Greeks
            fmt = "{:.2f}" if "LTP" in col else "{:.4f}"
            
            # Compare with previous reading and inject arrows
            if strike in prev_greeks and col in prev_greeks[strike]:
                prev_val = prev_greeks[strike][col]
                if curr_val > prev_val:
                    visual_greeks_df.at[idx, col] = f"▲ {fmt.format(curr_val)}"
                elif curr_val < prev_val:
                    visual_greeks_df.at[idx, col] = f"▼ {fmt.format(curr_val)}"
                else:
                    visual_greeks_df.at[idx, col] = fmt.format(curr_val)
            else:
                # First run initialization (no arrows yet)
                visual_greeks_df.at[idx, col] = fmt.format(curr_val)
                
    # Update memory for the next 15-second refresh cycle
    st.session_state[state_key_greeks] = new_greeks_state
    
    # 4. Apply dynamic CSS colors based on the arrows
    def style_greeks(row):
        styles = []
        is_atm = row['STRIKE'] == int(atm_strike)
        base_style = 'background-color: rgba(255, 255, 0, 0.2); ' if is_atm else ''
        
        for col in row.index:
            if col == 'STRIKE':
                styles.append(base_style + 'font-weight: bold;')
                continue
                
            val = str(row[col])
            if val.startswith('▲'):
                styles.append(base_style + 'color: #1dc973; font-weight: 600;')
            elif val.startswith('▼'):
                styles.append(base_style + 'color: #ff4b4b; font-weight: 600;')
            else:
                styles.append(base_style)
        return styles

    styled_greeks = visual_greeks_df.style.apply(style_greeks, axis=1)
    
    # --- NEW: Streamlit Column Configuration for hard Center Alignment ---
    center_alignment = {col: st.column_config.Column(alignment="center") for col in visual_greeks_df.columns}

    st.dataframe(
        styled_greeks, 
        use_container_width=True, 
        hide_index=True, 
        height=430,
        column_config=center_alignment
    )
    
elif ACCESS_TOKEN == "YOUR_UPSTOX_ACCESS_TOKEN_HERE":
    st.warning("Please hardcode your valid Upstox Access Token at the top of the script code.")
else:
    st.info("Awaiting valid selection to populate data.")
