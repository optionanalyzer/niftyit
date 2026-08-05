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
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIzTUJDMzIiLCJqdGkiOiI2YTcyYTJkMDNiNGNkODIzM2VmMmZmMDkiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc4NTg5NzY4MCwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzg1OTY3MjAwfQ.OcizjjvQBBMhGo8Df6wWsJ7gWjLQzIU2AIAM78bkzN4" 

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
    
    # Capturing both NSE and BSE elements to include SENSEX/BANKEX
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

# Added a 5th column to make room for the new Micro-PCR metric
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
greeks_display_df = pd.DataFrame()

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
        # Micro PCR color flashes based on extreme momentum shifts
        mpcr_color = "normal" if micro_pcr >= 1 else "inverse"
        st.metric(label="MICRO PCR (±2)", value=micro_pcr, delta="Hyper-Local", delta_color=mpcr_color)
    else:
        st.metric(label="MICRO PCR (±2)", value="---", delta="No Data", delta_color="off")

with col5:
    st.metric(label="INDIA VIX", value=live_vix)


# -------------------------------------------------------------------
# 5. INTRADAY OI CHANGE TRACKER (Attached to Active Strikes)
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    if 'oi_baselines' not in st.session_state:
        st.session_state.oi_baselines = {}
        
    state_prefix = f"{target_instrument_key}_{selected_expiry}"
    call_chg_list = []
    put_chg_list = []

    for index, row in active_strikes_df.iterrows():
        strike = row['strike_price']
        current_call_oi = row.get('call_options.market_data.oi', 0)
        current_put_oi = row.get('put_options.market_data.oi', 0)
        
        dict_key = f"{state_prefix}_{strike}"
        
        if dict_key not in st.session_state.oi_baselines:
            st.session_state.oi_baselines[dict_key] = {'call_oi': current_call_oi, 'put_oi': current_put_oi}
            
        baseline = st.session_state.oi_baselines[dict_key]
        call_chg_list.append(current_call_oi - baseline['call_oi'])
        put_chg_list.append(current_put_oi - baseline['put_oi'])
        
    # Attach data globally
    active_strikes_df['call_chg_oi'] = call_chg_list
    active_strikes_df['put_chg_oi'] = put_chg_list

# -------------------------------------------------------------------
# 6. ROW 3: INTERACTIVE OPTION GREEKS TABLE
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    ist = pytz.timezone('Asia/Kolkata')
    current_time_ist = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S IST')
    
    st.markdown(f"#### Option Greek | ⏱️ {current_time_ist}")
    
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
    
    def highlight_atm(row):
        is_atm = row['STRIKE'] == atm_strike
        return ['background-color: rgba(255, 255, 0, 0.2)' if is_atm else ''] * len(row)

    styled_greeks = greeks_display_df.style.apply(highlight_atm, axis=1).format(precision=4)
    st.dataframe(styled_greeks, use_container_width=True, hide_index=True, height=430)
    
elif ACCESS_TOKEN == "YOUR_UPSTOX_ACCESS_TOKEN_HERE":
    st.warning("Please hardcode your valid Upstox Access Token at the top of the script code.")
else:
    st.info("Awaiting valid selection to populate data.")

# -------------------------------------------------------------------
# 7. ROW 4: ADVANCED ALGORITHMIC TRADE SIGNAL ENGINE (DEBOUNCED & TRAILING)
# -------------------------------------------------------------------
if chain_df is not None and live_pcr is not None and live_pcr != 99.9:
    st.markdown("---")
    st.markdown("#### 🤖 Smart Trade Engine")
    
    try:
        current_vix = float(live_vix)
    except Exception:
        current_vix = 15.0

    # --- ENHANCED STATE MANAGEMENT ---
    if 'prev_pcr' not in st.session_state: st.session_state.prev_pcr = micro_pcr
    if 'prev_vix' not in st.session_state: st.session_state.prev_vix = current_vix
    
    if 'active_trade' not in st.session_state: st.session_state.active_trade = None
    if 'trade_details' not in st.session_state: st.session_state.trade_details = {}
    
    # NEW: Signal Verification (Debouncing)
    if 'pending_signal' not in st.session_state: st.session_state.pending_signal = None
    if 'pending_ticks' not in st.session_state: st.session_state.pending_ticks = 0
    
    # NEW: Trailing Stop Logic
    if 'trailing_stop' not in st.session_state: st.session_state.trailing_stop = 0
    if 'peak_spot' not in st.session_state: st.session_state.peak_spot = 0
    if 'trail_dist' not in st.session_state: st.session_state.trail_dist = 0

    # 1. Trend Calculations
    pcr_diff = micro_pcr - st.session_state.prev_pcr
    if pcr_diff > 0.02: pcr_trend = "RISING ↗️"
    elif pcr_diff < -0.02: pcr_trend = "FALLING ↘️"
    else: pcr_trend = "FLAT ➖"

    vix_diff = current_vix - st.session_state.prev_vix
    if vix_diff > 0.1: vix_trend = "RISING ↗️"
    elif vix_diff < -0.1: vix_trend = "FALLING ↘️"
    else: vix_trend = "FLAT ➖"

    st.session_state.prev_pcr = micro_pcr
    st.session_state.prev_vix = current_vix

    # 2. Support & Resistance & Dynamic Buffer Calculation
    try:
        res_idx = active_strikes_df['call_options.market_data.oi'].idxmax()
        resistance_strike = active_strikes_df.loc[res_idx, 'strike_price']
        sup_idx = active_strikes_df['put_options.market_data.oi'].idxmax()
        support_strike = active_strikes_df.loc[sup_idx, 'strike_price']
    except Exception:
        resistance_strike, support_strike = 0, 0

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

    if resistance_strike > 0 and support_strike > 0 and not greeks_display_df.empty:
        
        # --- STATE A: WE ARE IN AN ACTIVE TRADE (TRAILING STOP MODE) ---
        if st.session_state.active_trade == 'CALL':
            # Update peak price for trailing stop
            if underlying_spot > st.session_state.peak_spot:
                st.session_state.peak_spot = underlying_spot
                st.session_state.trailing_stop = max(st.session_state.trailing_stop, underlying_spot - st.session_state.trail_dist)

            # Exit purely on Price Action breaking the trailing stop
            if underlying_spot <= st.session_state.trailing_stop:
                signal_action = "EXIT CALL 🛑 (Trailing Stop Hit)"
                st.session_state.active_trade = None 
            else:
                signal_action = f"HOLD CALL 🟢 (SL: {st.session_state.trailing_stop:.2f})"

        elif st.session_state.active_trade == 'PUT':
            # Update lowest price for trailing stop
            if underlying_spot < st.session_state.peak_spot:
                st.session_state.peak_spot = underlying_spot
                st.session_state.trailing_stop = min(st.session_state.trailing_stop, underlying_spot + st.session_state.trail_dist)

            # Exit purely on Price Action breaking the trailing stop
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
            
            # Determine theoretical entry
            if (underlying_spot >= resistance_strike - buffer and pcr_trend == "FALLING ↘️") or (live_pcr <= 0.85 and pcr_trend == "FALLING ↘️"):
                raw_signal = "PUT"
                closest_idx = (greeks_display_df['Put Delta'] - (-0.55)).abs().idxmin()
                raw_strike = f"{int(greeks_display_df.loc[closest_idx, 'STRIKE'])} PE"
                raw_delta = f"{greeks_display_df.loc[closest_idx, 'Put Delta']:.4f}"
                
            elif (underlying_spot <= support_strike + buffer and pcr_trend == "RISING ↗️") or (live_pcr >= 1.15 and pcr_trend == "RISING ↗️"):
                raw_signal = "CALL"
                closest_idx = (greeks_display_df['Call Delta'] - 0.55).abs().idxmin()
                raw_strike = f"{int(greeks_display_df.loc[closest_idx, 'STRIKE'])} CE"
                raw_delta = f"{greeks_display_df.loc[closest_idx, 'Call Delta']:.4f}"

            # SIGNAL VERIFICATION LOGIC (Tick Debouncing)
            if raw_signal:
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
                    
                    # Initialize Trailing Stop metrics (1.5x the dynamic buffer distance)
                    st.session_state.trail_dist = buffer * 1.5 
                    st.session_state.peak_spot = underlying_spot
                    if raw_signal == "CALL":
                        st.session_state.trailing_stop = underlying_spot - st.session_state.trail_dist
                    else:
                        st.session_state.trailing_stop = underlying_spot + st.session_state.trail_dist

                    st.session_state.pending_signal = None
                    st.session_state.pending_ticks = 0
                else:
                    # Show user that a signal is being validated
                    signal_action = f"⏳ VERIFYING {raw_signal} (Tick {st.session_state.pending_ticks}/2)"
                    suggested_strike = raw_strike
                    target_delta = raw_delta
            else:
                # No setup found, reset pending buffers
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
# 8. ROW 5 & 6: VISUAL OI BUILDUP & TREND GAUGES
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.markdown("---")
    
    color_call = 'rgba(255, 75, 75, 1)' 
    color_put = 'rgba(29, 201, 115, 1)' 

    # 1. NEW LAYOUT: Give charts the full width by splitting into 2 columns
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
            # Force exact strike labels on the X-axis
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
            # Force exact strike labels on the X-axis
            xaxis=dict(type='category', tickangle=-45)
        )
        st.plotly_chart(fig_chg, use_container_width=True, config={'displayModeBar': False}, key="chart_oi_change")

    # 2. NEW LAYOUT: Place the 3 S&R metric boxes horizontally below the charts
    st.write("") # Add a tiny bit of vertical spacing
    box_col1, box_col2, box_col3 = st.columns(3)
    
    active_strikes_df['Total_Activity'] = active_strikes_df.get('call_options.market_data.oi', 0) + active_strikes_df.get('put_options.market_data.oi', 0)
    bg_idx = active_strikes_df['Total_Activity'].idxmax()
    battleground_strike = active_strikes_df.loc[bg_idx, 'strike_price'] if pd.notna(bg_idx) else 0

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

    # ... KEEP YOUR EXISTING TIME-SERIES LOGGING CODE BELOW THIS ...

    # Time-Series Logging for Trends
    if 'history_df' not in st.session_state:
        st.session_state.history_df = pd.DataFrame(columns=['Time_IST', 'PCR', 'VIX'])
    
    ist = pytz.timezone('Asia/Kolkata')
    current_time_str = datetime.now(ist).strftime('%H:%M:%S')
    
    new_data = pd.DataFrame([{'Time_IST': current_time_str, 'PCR': live_pcr, 'VIX': current_vix}])
    st.session_state.history_df = pd.concat([st.session_state.history_df, new_data], ignore_index=True)
    st.session_state.history_df = st.session_state.history_df.tail(20)

    st.markdown("---")
    bull_pct = min(max((live_pcr - 0.5) / 1.0, 0), 1) * 100
    
    st.markdown(f"""
    <div style="background-color:#1e1e1e; padding:15px; border-radius:10px; margin-bottom:20px;">
        <h4 style="margin-top:0; margin-bottom:10px; color:white; font-weight:600;">MARKET SENTIMENT: {int(bull_pct)}% BULLISH</h4>
        <div style="width:100%; background-color:#333; border-radius:8px; height:18px; overflow:hidden;">
            <div style="width:{bull_pct}%; background-color:#3182ce; height:100%; transition: width 0.5s ease-in-out;"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

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
# 9. ROW 7: LIVE OPTION CHAIN DYNAMIC TABLE (ATM ± 5 Strikes)
# -------------------------------------------------------------------
if not active_strikes_df.empty:
    st.markdown("---")
    st.markdown("#### 🔗 Live Position Tracker (ATM ± 5 Strikes)")

    oc_required_cols = {
        'call_options.market_data.oi': 'Bear Positions',
        'call_chg_oi': 'Bear Activity',
#        'call_options.market_data.ltp': 'Call LTP',
        'strike_price': 'STRIKE',
#        'put_options.market_data.ltp': 'Put LTP',
        'put_chg_oi': 'Bull Activity',
        'put_options.market_data.oi': 'Bull Positions'
    }

    oc_available = [c for c in oc_required_cols.keys() if c in active_strikes_df.columns]
    oc_display_df = active_strikes_df[oc_available].rename(columns=oc_required_cols)

    ordered_cols = ['Bear Positions', 'Bear Activity', 'Call LTP', 'STRIKE', 'Put LTP', 'Bull Activity', 'Bull Positions']
    final_cols = [c for c in ordered_cols if c in oc_display_df.columns]
    oc_display_df = oc_display_df[final_cols]

    # 1. STRICTLY NUMERIC DATA
    # Keep the raw dataframe as pure numbers so Streamlit's PyArrow backend never crashes.
    for c in final_cols:
        oc_display_df[c] = pd.to_numeric(oc_display_df[c], errors='coerce').fillna(0)

    # 2. SAFE CSS LOGIC
    # Removed aggressive tags to allow Streamlit's internal renderer to parse the colors.
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

    # 3. VISUAL LAYER FORMATTING
    # We inject the "+" or "-" visually without altering the underlying raw data.
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

    # 4. RENDER
    # Apply the CSS and the Visual Formatters simultaneously
    styled_oc = oc_display_df.style.apply(style_oc_table, axis=1).format(format_dict)
    
    st.dataframe(styled_oc, use_container_width=True, hide_index=True, height=430)
