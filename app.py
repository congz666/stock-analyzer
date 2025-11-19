import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 1. 页面配置 ---
st.set_page_config(page_title="AI 智能投研 (Auto-WACC版)", layout="wide", page_icon="📊")

# --- 2. CSS 样式 (自适应清爽版) ---
st.markdown("""
    <style>
    /* 顶部指标卡片 */
    .metric-container {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.1);
        border-radius: 8px;
        padding: 15px 20px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    .metric-label { font-size: 0.9rem; color: gray; margin-bottom: 4px; }
    .metric-value { font-size: 1.8rem; font-weight: 700; color: var(--text-color); }
    
    /* 涨跌幅 */
    .delta-pos { color: #00C805; font-weight: 600; }
    .delta-neg { color: #FF3B30; font-weight: 600; }
    
    /* 估值卡片 */
    .valuation-card {
        background-color: var(--secondary-background-color);
        border-left: 5px solid #888;
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心逻辑函数 ---

@st.cache_data(ttl=3600)
def get_market_data():
    """获取无风险利率 (10年美债)"""
    try:
        # 获取 ^TNX (CBOE Interest Rate 10 Year T No)
        tnx = yf.Ticker("^TNX")
        # Yahoo返回的是点数，比如 4.50 代表 4.5%
        rf_rate = tnx.history(period="5d")['Close'].iloc[-1]
        return rf_rate
    except:
        return 4.0 # 默认兜底值

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
    """计算 EPS 和 Revenue 的历史复合增长率"""
    metrics = {"eps_cagr": 0.0, "years": 0}
    if financials is None or financials.empty: return metrics
    try:
        financials = financials.sort_index(axis=1, ascending=False)
        cols = financials.columns
        if len(cols) >= 3:
            latest, oldest = cols[0], cols[-1]
            num_years = len(cols) - 1
            metrics['years'] = num_years
            try:
                eps_row = financials.loc['Diluted EPS']
                s, e = eps_row[oldest], eps_row[latest]
                if s > 0 and e > 0: metrics['eps_cagr'] = ((e/s)**(1/num_years) - 1) * 100
            except: pass
    except: pass
    return metrics

def calculate_sr_levels(df, sensitivity=0.02):
    """支撑压力算法"""
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

# --- 4. 页面逻辑 ---

# 侧边栏输入
with st.sidebar:
    st.subheader("🔎 股票检索")
    ticker = st.text_input("代码", value="NVDA", help="美股直接输代码，A股加后缀 (600519.SS)")
    
    st.markdown("---")
    st.subheader("⚙️ 自动计算参数")
    
    # --- 核心修改：获取无风险利率 & Beta ---
    rf_rate_data = get_market_data() # 获取 10年美债
    
    # 占位符，等获取到 Stock Info 后再更新
    beta_placeholder = st.empty()
    
    # 默认风险溢价 (Equity Risk Premium)
    erp_input = st.slider("市场风险溢价 ERP (%)", 4.0, 7.0, 5.5, 0.1, help="通常取 5.0% - 6.0%")
    
    st.markdown("---")
    st.caption(f"当前 10年美债收益率: {rf_rate_data:.2f}%")

if ticker:
    with st.spinner('正在抓取美债收益率、Beta系数及财报...'):
        hist, info, financials = get_stock_data(ticker)
        
    if hist is not None and not hist.empty:
        # --- 1. 自动计算 WACC (CAPM模型) ---
        stock_beta = info.get('beta', 1.0)
        if stock_beta is None: stock_beta = 1.0 # 容错
        
        # CAPM 公式: Rf + Beta * (Rm - Rf)
        # 我们用 CAPM 计算出的股权成本作为 WACC 的替代（适用于大多数分析）
        calculated_wacc = rf_rate_data + stock_beta * erp_input
        
        # 更新侧边栏 Beta 显示
        beta_placeholder.metric("当前 Beta", f"{stock_beta:.2f}")
        
        # --- 2. 侧边栏 WACC 确认 ---
        with st.sidebar:
            st.success(f"🤖 AI 建议折现率: {calculated_wacc:.2f}%")
            st.caption(f"算法: {rf_rate_data:.2f}% (无风险) + {stock_beta:.2f} (Beta) × {erp_input:.1f}% (溢价)")
            
            # 允许用户微调，但默认值设为计算值
            user_discount_rate = st.slider("折现率 WACC (%)", 3.0, 20.0, float(round(calculated_wacc, 1)), 0.1)
            user_terminal_growth = st.slider("永续增长率 (%)", 1.0, 5.0, 3.0, 0.5)

        # --- 3. 基础数据准备 ---
        curr_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        price_change = (curr_price - prev_close) / prev_close * 100
        cagr_data = calculate_historical_cagr(financials)
        hist_eps_cagr = cagr_data.get('eps_cagr', 0)
        
        # 默认增长率逻辑
        analyst_growth = info.get('earningsGrowth', 0) * 100 if info.get('earningsGrowth') else 0
        default_growth = analyst_growth if analyst_growth > 0 else (hist_eps_cagr if hist_eps_cagr > 0 else 10.0)

        # ==========================================
        # UI Part: 顶部仪表盘
        # ==========================================
        st.title(f"{info.get('shortName', ticker)}")
        st.caption(f"Sector: {info.get('sector', 'N/A')} | Beta: {stock_beta:.2f} | WACC(Calc): {calculated_wacc:.2f}%")
        
        m1, m2, m3, m4 = st.columns(4)
        def kpi_card(col, label, value, delta=None):
            delta_html = ""
            if delta is not None:
                cls = "delta-pos" if delta > 0 else "delta-neg"
                sign = "+" if delta > 0 else ""
                delta_html = f'<span class="{cls}">{sign}{delta:.2f}%</span>'
            col.markdown(f"""<div class="metric-container"><div class="metric-label">{label}</div><div class="metric-value">{value}</div>{delta_html}</div>""", unsafe_allow_html=True)

        kpi_card(m1, "当前价格", f"{curr_price:.2f}", price_change)
        kpi_card(m2, "折现率 (WACC)", f"{user_discount_rate:.1f}%")
        kpi_card(m3, "EPS (TTM)", f"{info.get('trailingEps', 0):.2f}")
        kpi_card(m4, "分析师预期增长", f"{analyst_growth:.1f}%")

        st.markdown("---")

        # ==========================================
        # UI Part: 估值模型
        # ==========================================
        st.subheader("📊 估值建模 (Auto-WACC)")
        
        with st.container():
            c1, c2, c3 = st.columns([1,1,2])
            user_growth = c1.number_input("预期增长率 (%)", value=float(default_growth), step=0.5)
            user_eps = c2.number_input("基准 EPS", value=float(info.get('trailingEps', 1.0)), step=0.05)
            c3.info(f"ℹ️ 折现率已自动锚定为 **{user_discount_rate:.1f}%** (基于 Beta {stock_beta:.2f})")

        # --- 1. PE 模型 ---
        base_pe = 8.5 + 2 * user_growth
        if user_growth > 25: base_pe = user_growth * 1.5 
        
        pe_scenarios = {
            '保守': {'pe': max(10, base_pe*0.8)},
            '中性': {'pe': base_pe},
            '乐观': {'pe': base_pe*1.2}
        }
        
        # --- 2. DCF 模型 (使用自动 WACC) ---
        dcf_flows = []
        temp_eps = user_eps
        for i in range(1, 6):
            temp_eps *= (1 + user_growth/100)
            dcf_flows.append(temp_eps / ((1 + user_discount_rate/100)**i))
        term_val = (temp_eps * (1 + user_terminal_growth/100)) / ((user_discount_rate - user_terminal_growth)/100)
        dcf_value = sum(dcf_flows) + term_val / ((1 + user_discount_rate/100)**5)

        # 结果展示
        col_v1, col_v2 = st.columns(2)
        def get_color(target, curr):
            diff = (target - curr) / curr
            if diff >= 0.15: return "#00C805"
            if diff <= -0.15: return "#FF3B30"
            return "#FF9500"

        with col_v1:
            st.markdown("#### 🅰️ 相对估值 (PE法)")
            for label, data in pe_scenarios.items():
                target = user_eps * data['pe']
                upside = (target - curr_price)/curr_price*100
                color = get_color(target, curr_price)
                st.markdown(f"""
                <div class="valuation-card" style="border-left-color: {color};">
                    <div style="display:flex; justify-content:space-between;">
                        <div><b>{label}</b> <small>(PE {data['pe']:.1f}x)</small></div>
                        <div style="text-align:right;"><b>${target:.2f}</b> <br><span style="color:{color};font-size:0.8rem">{upside:+.1f}%</span></div>
                    </div>
                </div>""", unsafe_allow_html=True)

        with col_v2:
            st.markdown("#### 🅱️ 绝对估值 (DCF法)")
            dcf_upside = (dcf_value - curr_price)/curr_price*100
            dcf_color = get_color(dcf_value, curr_price)
            st.markdown(f"""
            <div style="background:var(--secondary-background-color); border:2px solid {dcf_color}; border-radius:10px; padding:20px; text-align:center;">
                <div style="color:gray; font-size:0.9rem">DCF 内在价值 (WACC {user_discount_rate}%)</div>
                <div style="font-size:2.5rem; font-weight:bold; color:{dcf_color};">${dcf_value:.2f}</div>
                <div style="color:{dcf_color}; font-weight:600">{dcf_upside:+.2f}% 空间</div>
            </div>""", unsafe_allow_html=True)
            
            avg_val = (pe_scenarios['中性']['pe']*user_eps + dcf_value)/2
            st.success(f"⚖️ 综合参考: ${avg_val:.2f}")

        st.divider()

        # ==========================================
        # UI Part: 技术面
        # ==========================================
        st.subheader("📉 关键点位")
        sr = calculate_sr_levels(hist)
        supports = sorted([x for x in sr if x['price'] < curr_price], key=lambda x: x['price'], reverse=True)
        resistances = sorted([x for x in sr if x['price'] > curr_price], key=lambda x: x['price'])
        
        c_chart, c_list = st.columns([3, 1])
        with c_chart:
            plot_df = hist.iloc[-252:]
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], increasing_line_color='#00C805', decreasing_line_color='#FF3B30', name='K线'))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), line=dict(color='#007AFF', width=1.5), name='MA20'))
            for s in supports[:3]: fig.add_hline(y=s['price'], line_dash="dot", line_color="green", line_width=1)
            for r in resistances[:3]: fig.add_hline(y=r['price'], line_dash="dot", line_color="red", line_width=1)
            fig.update_layout(template="plotly_white", height=400, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
            
        with c_list:
            st.markdown("###### 🔴 压力位")
            for r in resistances[:3]: st.markdown(f"<div style='border-bottom:1px solid #eee; display:flex; justify-content:space-between;'><span>${r['price']:.1f}</span><span style='color:#FF3B30'>{'★'*min(r['strength'],3)}</span></div>", unsafe_allow_html=True)
            st.markdown("###### 🟢 支撑位")
            for s in supports[:3]: st.markdown(f"<div style='border-bottom:1px solid #eee; display:flex; justify-content:space-between;'><span>${s['price']:.1f}</span><span style='color:#00C805'>{'★'*min(s['strength'],3)}</span></div>", unsafe_allow_html=True)

    else:
        st.error("数据加载失败")
