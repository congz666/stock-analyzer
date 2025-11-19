import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 1. 页面配置 ---
st.set_page_config(page_title="AI 智能投研 (Pro Max)", layout="wide", page_icon="📈")

# --- 2. CSS 样式 (保持自适应清爽风) ---
st.markdown("""
    <style>
    /* 指标容器 */
    .metric-container {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.1);
        border-radius: 8px;
        padding: 15px 20px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .metric-label { font-size: 0.9rem; color: gray; margin-bottom: 4px; }
    .metric-value { font-size: 1.8rem; font-weight: 700; color: var(--text-color); }
    
    /* 颜色定义 */
    .delta-pos { color: #00C805; font-weight: 600; }
    .delta-neg { color: #FF3B30; font-weight: 600; }
    
    /* 估值结果卡片 */
    .valuation-card {
        background-color: var(--secondary-background-color);
        border-left: 5px solid #888;
        border-radius: 6px;
        padding: 12px 15px;
        margin-bottom: 8px;
    }
    
    /* 当前 PE 状态条 */
    .pe-status-bar {
        background-color: rgba(0, 122, 255, 0.1);
        border: 1px solid rgba(0, 122, 255, 0.3);
        color: #007AFF;
        padding: 10px;
        border-radius: 6px;
        margin-bottom: 15px;
        font-weight: 600;
        text-align: center;
        display: flex;
        justify-content: space-around;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 数据与算法函数 ---

@st.cache_data(ttl=3600)
def get_market_data():
    """获取无风险利率 (^TNX)"""
    try:
        tnx = yf.Ticker("^TNX")
        return tnx.history(period="5d")['Close'].iloc[-1]
    except:
        return 4.0

@st.cache_data(ttl=3600)
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="2y")
        try:
            info = stock.info
            financials = stock.income_stmt
        except:
            info = {}
            financials = pd.DataFrame()
        return hist, info, financials
    except:
        return None, None, None

def calculate_historical_cagr(financials):
    metrics = {"eps_cagr": 0.0, "years": 0}
    if financials is None or financials.empty: return metrics
    try:
        financials = financials.sort_index(axis=1, ascending=False)
        cols = financials.columns
        if len(cols) >= 3:
            metrics['years'] = len(cols) - 1
            try:
                eps_row = financials.loc['Diluted EPS']
                s, e = eps_row[cols[-1]], eps_row[cols[0]]
                if s > 0 and e > 0: metrics['eps_cagr'] = ((e/s)**(1/metrics['years']) - 1) * 100
            except: pass
    except: pass
    return metrics

def calculate_sr_levels(df, sensitivity=0.02):
    levels = []
    for i in range(2, len(df) - 2):
        if df['Low'][i] < df['Low'][i-1] and df['Low'][i] < df['Low'][i+1] and \
           df['Low'][i] < df['Low'][i-2] and df['Low'][i] < df['Low'][i+2]:
            levels.append((df['Low'][i], 1)) 
        if df['High'][i] > df['High'][i-1] and df['High'][i] > df['High'][i+1] and \
           df['High'][i] > df['High'][i-2] and df['High'][i] > df['High'][i+2]:
            levels.append((df['High'][i], 2)) 
    levels.sort(key=lambda x: x[0])
    merged = []
    if not levels: return []
    curr = [levels[0]]
    for i in range(1, len(levels)):
        avg = sum(x[0] for x in curr)/len(curr)
        if abs(levels[i][0] - avg)/avg <= sensitivity:
            curr.append(levels[i])
        else:
            merged.append({'price': avg, 'strength': len(curr)})
            curr = [levels[i]]
    merged.append({'price': sum(x[0] for x in curr)/len(curr), 'strength': len(curr)})
    return merged

# --- 4. 主界面逻辑 ---

with st.sidebar:
    st.subheader("🔎 股票检索")
    ticker = st.text_input("代码", value="NVDA")
    st.markdown("---")
    st.subheader("⚙️ 宏观参数 (Auto)")
    rf_rate = get_market_data()
    beta_ph = st.empty()
    erp = st.slider("市场风险溢价 ERP (%)", 4.0, 7.0, 5.5, 0.1)
    st.caption(f"10年美债: {rf_rate:.2f}%")

if ticker:
    with st.spinner('正在计算 WACC 与 PE 估值矩阵...'):
        hist, info, financials = get_stock_data(ticker)

    if hist is not None and not hist.empty:
        # 基础数据
        curr_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        price_change = (curr_price - prev_close) / prev_close * 100
        
        # WACC 计算
        beta = info.get('beta', 1.0) if info.get('beta') else 1.0
        beta_ph.metric("Beta", f"{beta:.2f}")
        calc_wacc = rf_rate + beta * erp
        
        with st.sidebar:
            st.success(f"AI WACC: {calc_wacc:.2f}%")
            user_wacc = st.slider("折现率 (%)", 3.0, 20.0, float(round(calc_wacc, 1)), 0.1)
            user_tg = st.slider("永续增长 (%)", 1.0, 5.0, 3.0, 0.5)
            
        # 增长率逻辑
        cagr = calculate_historical_cagr(financials)
        hist_growth = cagr.get('eps_cagr', 0)
        analyst_growth = info.get('earningsGrowth', 0) * 100 if info.get('earningsGrowth') else 0
        default_growth = analyst_growth if analyst_growth > 0 else (hist_growth if hist_growth > 0 else 10.0)
        
        # 获取当前 PE 数据 (核心新增)
        ttm_pe = info.get('trailingPE', 0)
        fwd_pe = info.get('forwardPE', 0)
        eps_ttm = info.get('trailingEps', 0)

        # ==========================================
        # 1. 顶部仪表盘
        # ==========================================
        st.title(f"{info.get('shortName', ticker)} ({ticker})")
        m1, m2, m3, m4 = st.columns(4)
        def card(col, label, val, delta=None):
            d_html = ""
            if delta: d_html = f"<span class='{'delta-pos' if delta>0 else 'delta-neg'}'>{'+' if delta>0 else ''}{delta:.2f}%</span>"
            col.markdown(f"<div class='metric-container'><div class='metric-label'>{label}</div><div class='metric-value'>{val}</div>{d_html}</div>", unsafe_allow_html=True)
        
        card(m1, "当前价格", f"{curr_price:.2f}", price_change)
        card(m2, "静态 PE (TTM)", f"{ttm_pe:.1f}" if ttm_pe else "N/A")
        card(m3, "EPS (TTM)", f"{eps_ttm:.2f}")
        card(m4, "历史复合增长", f"{hist_growth:.1f}%")
        
        st.markdown("---")

        # ==========================================
        # 2. 估值建模 (含当前 PE 对比)
        # ==========================================
        st.subheader("📊 估值建模")
        
        with st.container():
            c1, c2 = st.columns([1, 2])
            user_growth = c1.number_input("预期未来增长率 (%)", value=float(default_growth), step=0.5)
            user_eps = c2.number_input("基准 EPS", value=float(eps_ttm if eps_ttm else 1.0), step=0.01)
            c2.info(f"市场参考: 分析师预期 {analyst_growth:.1f}% | 历史增速 {hist_growth:.1f}%")

        # --- 计算逻辑 ---
        # PE 逻辑
        base_pe = 8.5 + 2 * user_growth
        if user_growth > 25: base_pe = user_growth * 1.5 
        pe_scenarios = {
            '保守': max(10, base_pe*0.8),
            '合理': base_pe,
            '乐观': base_pe*1.2
        }
        
        # DCF 逻辑
        dcf_sum = 0
        temp_eps = user_eps
        for i in range(1, 6):
            temp_eps *= (1 + user_growth/100)
            dcf_sum += temp_eps / ((1 + user_wacc/100)**i)
        term = (temp_eps * (1 + user_tg/100)) / ((user_wacc - user_tg)/100)
        dcf_val = dcf_sum + term / ((1 + user_wacc/100)**5)
        
        # --- 展示逻辑 ---
        col_v1, col_v2 = st.columns(2)
        
        # 辅助颜色函数
        def get_color(target):
            diff = (target - curr_price)/curr_price
            if diff >= 0.15: return "#00C805"
            if diff <= -0.15: return "#FF3B30"
            return "#FF9500"

        with col_v1:
            st.markdown("#### 🅰️ 相对估值法 (PE对比)")
            
            # --- 核心新增：当前市场定价状态栏 ---
            fwd_pe_str = f"{fwd_pe:.1f}x" if fwd_pe else "N/A"
            ttm_pe_str = f"{ttm_pe:.1f}x" if ttm_pe else "N/A"
            
            st.markdown(f"""
            <div class="pe-status-bar">
                <div>🏦 当前静态 PE: {ttm_pe_str}</div>
                <div style="border-left:1px solid rgba(0,122,255,0.3); padding-left:20px;">🔭 远期 Fwd PE: {fwd_pe_str}</div>
            </div>
            """, unsafe_allow_html=True)
            # -----------------------------------
            
            for label, pe_mult in pe_scenarios.items():
                target = user_eps * pe_mult
                color = get_color(target)
                upside = (target - curr_price)/curr_price*100
                
                # 逻辑判断：当前PE是否高于理论PE
                premium = ""
                if ttm_pe and ttm_pe > pe_mult:
                    premium = f"<span style='color:#FF3B30; font-size:0.8rem'>(市场溢价 {(ttm_pe/pe_mult - 1)*100:.0f}%)</span>"
                
                st.markdown(f"""
                <div class="valuation-card" style="border-left-color: {color};">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-weight:bold; color:var(--text-color)">{label} <span style="color:gray; font-weight:normal">| 给定 {pe_mult:.1f}x</span></div>
                            <div style="font-size:0.8rem; color:gray">目标价: <b>${target:.2f}</b> {premium}</div>
                        </div>
                        <div style="text-align:right; color:{color}; font-weight:bold;">{upside:+.1f}%</div>
                    </div>
                </div>""", unsafe_allow_html=True)

        with col_v2:
            st.markdown("#### 🅱️ 绝对估值法 (DCF)")
            dcf_upside = (dcf_val - curr_price)/curr_price*100
            dcf_color = get_color(dcf_val)
            st.markdown(f"""
            <div style="background:var(--secondary-background-color); border:2px solid {dcf_color}; border-radius:10px; padding:25px; text-align:center; margin-top:10px;">
                <div style="color:gray; font-size:0.9rem">WACC {user_wacc}% | Growth {user_growth}%</div>
                <div style="font-size:2.5rem; font-weight:800; color:{dcf_color};">${dcf_val:.2f}</div>
                <div style="color:{dcf_color}; font-weight:600">潜在回报: {dcf_upside:+.2f}%</div>
            </div>""", unsafe_allow_html=True)
            
            avg_val = (pe_scenarios['合理']*user_eps + dcf_val)/2
            st.success(f"⚖️ 综合参考价: ${avg_val:.2f}")

        st.divider()
        
        # ==========================================
        # 3. 技术分析 (保持清爽版)
        # ==========================================
        st.subheader("📉 关键点位")
        sr = calculate_sr_levels(hist)
        supports = sorted([x for x in sr if x['price'] < curr_price], key=lambda x: x['price'], reverse=True)
        resistances = sorted([x for x in sr if x['price'] > curr_price], key=lambda x: x['price'])
        
        col_chart, col_list = st.columns([3, 1])
        with col_chart:
            plot_df = hist.iloc[-252:]
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], increasing_line_color='#00C805', decreasing_line_color='#FF3B30', name='K线'))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), line=dict(color='#007AFF', width=1.5), name='MA20'))
            for s in supports[:3]: fig.add_hline(y=s['price'], line_dash="dot", line_color="green", line_width=1)
            for r in resistances[:3]: fig.add_hline(y=r['price'], line_dash="dot", line_color="red", line_width=1)
            fig.update_layout(template="plotly_white", height=400, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        
        with col_list:
            st.markdown("###### 🔴 阻力区")
            for r in resistances[:3]: st.markdown(f"<div style='border-bottom:1px solid #eee; display:flex; justify-content:space-between;'><span>${r['price']:.1f}</span><span style='color:#FF3B30'>{'★'*min(r['strength'],3)}</span></div>", unsafe_allow_html=True)
            st.markdown("###### 🟢 支撑区")
            for s in supports[:3]: st.markdown(f"<div style='border-bottom:1px solid #eee; display:flex; justify-content:space-between;'><span>${s['price']:.1f}</span><span style='color:#00C805'>{'★'*min(s['strength'],3)}</span></div>", unsafe_allow_html=True)

    else:
        st.error("数据获取失败")
