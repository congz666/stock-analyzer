import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 1. 页面配置 ---
st.set_page_config(page_title="AI 智能投研 (专业版)", layout="wide", page_icon="📊")

# --- 2. CSS 样式优化 (自适应浅色/深色模式) ---
st.markdown("""
    <style>
    /* 使用 Streamlit 原生变量，自动适配浅色/深色模式 */
    
    /* 顶部指标卡片容器 */
    .metric-container {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(49, 51, 63, 0.1);
        border-radius: 8px;
        padding: 15px 20px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        margin-bottom: 10px;
    }
    
    /* 指标文字 */
    .metric-label {
        font-size: 0.9rem;
        color: var(--text-color);
        opacity: 0.7;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: var(--text-color);
    }
    
    /* 涨跌幅颜色 */
    .delta-pos { color: #00C805; font-weight: 600; font-size: 0.9rem; }
    .delta-neg { color: #FF3B30; font-weight: 600; font-size: 0.9rem; }
    
    /* 估值结果卡片 */
    .valuation-card {
        background-color: var(--secondary-background-color);
        border-left: 5px solid #888; /* 默认灰色，脚本里会修改颜色 */
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 10px;
    }
    
    /* 调整侧边栏 */
    [data-testid="stSidebar"] {
        background-color: var(--secondary-background-color);
        border-right: 1px solid rgba(49, 51, 63, 0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 核心逻辑函数 (保持功能最强) ---

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
    metrics = {"eps_cagr": 0.0, "rev_cagr": 0.0, "years": 0}
    if financials is None or financials.empty: return metrics
    
    try:
        financials = financials.sort_index(axis=1, ascending=False)
        cols = financials.columns
        if len(cols) >= 3:
            latest, oldest = cols[0], cols[-1]
            num_years = len(cols) - 1
            metrics['years'] = num_years
            
            # EPS CAGR
            try:
                eps_row = financials.loc['Diluted EPS']
                s, e = eps_row[oldest], eps_row[latest]
                if s > 0 and e > 0: metrics['eps_cagr'] = ((e/s)**(1/num_years) - 1) * 100
            except: pass
            
            # Revenue CAGR
            try:
                rev_key = 'Total Revenue' if 'Total Revenue' in financials.index else 'Total Income'
                if rev_key in financials.index:
                    rev_row = financials.loc[rev_key]
                    s, e = rev_row[oldest], rev_row[latest]
                    if s > 0 and e > 0: metrics['rev_cagr'] = ((e/s)**(1/num_years) - 1) * 100
            except: pass
    except: pass
    return metrics

def calculate_sr_levels(df, sensitivity=0.02):
    """支撑压力算法"""
    levels = []
    for i in range(2, len(df) - 2):
        if df['Low'][i] < df['Low'][i-1] and df['Low'][i] < df['Low'][i+1] and \
           df['Low'][i] < df['Low'][i-2] and df['Low'][i] < df['Low'][i+2]:
            levels.append((df['Low'][i], 1)) # Support
        if df['High'][i] > df['High'][i-1] and df['High'][i] > df['High'][i+1] and \
           df['High'][i] > df['High'][i-2] and df['High'][i] > df['High'][i+2]:
            levels.append((df['High'][i], 2)) # Resistance
            
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

# --- 4. 页面主结构 ---

# 侧边栏
with st.sidebar:
    st.subheader("🔎 股票检索")
    ticker = st.text_input("代码", value="AAPL", help="例: NVDA, 600519.SS, 0700.HK")
    
    st.markdown("---")
    st.subheader("⚙️ 估值参数微调")
    user_discount_rate = st.slider("折现率 WACC (%)", 5.0, 15.0, 9.0, 0.5)
    user_terminal_growth = st.slider("永续增长率 (%)", 1.0, 5.0, 3.0, 0.5)
    st.info("左侧参数仅影响 DCF 模型")

if ticker:
    with st.spinner('正在进行数据清洗与模型计算...'):
        hist, info, financials = get_stock_data(ticker)
        
    if hist is not None and not hist.empty:
        # --- 基础数据准备 ---
        curr_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        price_change = (curr_price - prev_close) / prev_close * 100
        
        cagr_data = calculate_historical_cagr(financials)
        hist_eps_cagr = cagr_data.get('eps_cagr', 0)
        
        # 智能确定默认增长率
        analyst_growth = info.get('earningsGrowth', 0) * 100 if info.get('earningsGrowth') else 0
        default_growth = analyst_growth if analyst_growth > 0 else (hist_eps_cagr if hist_eps_cagr > 0 else 10.0)

        # ==========================================
        # 顶部仪表盘 (清爽卡片风)
        # ==========================================
        st.title(f"{info.get('shortName', ticker)}")
        st.caption(f"代码: {ticker} | 行业: {info.get('industry', 'N/A')} | 货币: {info.get('currency', 'USD')}")
        
        m1, m2, m3, m4 = st.columns(4)
        
        def kpi_card(col, label, value, delta=None, suffix=""):
            delta_html = ""
            if delta is not None:
                color_class = "delta-pos" if delta > 0 else "delta-neg"
                sign = "+" if delta > 0 else ""
                delta_html = f'<span class="{color_class}">{sign}{delta:.2f}%</span>'
            
            col.markdown(f"""
            <div class="metric-container">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}{suffix}</div>
                {delta_html}
            </div>
            """, unsafe_allow_html=True)

        kpi_card(m1, "当前价格", f"{curr_price:.2f}", price_change)
        kpi_card(m2, "静态市盈率 (PE)", f"{info.get('trailingPE', 0):.2f}")
        kpi_card(m3, "每股收益 (EPS)", f"{info.get('trailingEps', 0):.2f}")
        kpi_card(m4, f"历史 {cagr_data['years']} 年利润复合增长", f"{hist_eps_cagr:.1f}", suffix="%")

        st.markdown("---")

        # ==========================================
        # 中部：双重估值模型 (逻辑 + 展示)
        # ==========================================
        st.subheader("📊 估值建模分析")
        
        # 1. 交互输入区 (放在一行，节省空间)
        with st.container():
            col_input1, col_input2, col_input3 = st.columns([1, 1, 2])
            user_growth = col_input1.number_input("预期未来年增长率 (%)", value=float(default_growth), step=0.5)
            user_eps = col_input2.number_input("基准 EPS (TTM)", value=float(info.get('trailingEps', 1.0)), step=0.05)
            col_input3.warning(f"💡 建议参考：分析师预测增速为 **{analyst_growth:.1f}%**，历史真实增速为 **{hist_eps_cagr:.1f}%**")

        # 2. 计算逻辑
        # --- PE 模型 ---
        # 逻辑：基础PE 8.5，每增加1%增长率，PE增加2 (格雷厄姆经典公式)
        # 修正：如果增长率>20%，格雷厄姆公式会失效，改用PEG=1.5修正
        base_pe_multiplier = 8.5 + 2 * user_growth
        if user_growth > 25: base_pe_multiplier = user_growth * 1.5 
        
        pe_scenarios = {
            '保守 (Bear)': {'pe': max(10, base_pe_multiplier*0.8), 'factor': 0.8},
            '中性 (Base)': {'pe': base_pe_multiplier, 'factor': 1.0},
            '乐观 (Bull)': {'pe': base_pe_multiplier*1.2, 'factor': 1.2}
        }
        
        # --- DCF 模型 ---
        dcf_flows = []
        temp_eps = user_eps
        for i in range(1, 6):
            temp_eps *= (1 + user_growth/100)
            dcf_flows.append(temp_eps / ((1 + user_discount_rate/100)**i))
        term_val = (temp_eps * (1 + user_terminal_growth/100)) / ((user_discount_rate - user_terminal_growth)/100)
        dcf_value = sum(dcf_flows) + term_val / ((1 + user_discount_rate/100)**5)

        # 3. 结果展示区
        c_val1, c_val2 = st.columns(2)
        
        # 辅助函数：根据空间决定颜色
        def get_status_color(target, current):
            diff = (target - current) / current
            if diff >= 0.15: return "#00C805" # 绿 (大空间)
            if diff <= -0.15: return "#FF3B30" # 红 (高估)
            return "#FF9500" # 橙 (合理)

        with c_val1:
            st.markdown("#### 🅰️ 相对估值法 (PE Multiplier)")
            st.markdown(f"<div style='font-size:0.8rem; color:gray'>基于输入增长率 {user_growth}% 动态推导合理 PE 倍数</div>", unsafe_allow_html=True)
            
            for label, data in pe_scenarios.items():
                target_price = user_eps * data['pe']
                upside = (target_price - curr_price) / curr_price * 100
                color = get_status_color(target_price, curr_price)
                
                st.markdown(f"""
                <div class="valuation-card" style="border-left-color: {color};">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-weight:bold; font-size:1rem; color:var(--text-color)">{label}</div>
                            <div style="font-size:0.8rem; color:gray">给予 {data['pe']:.1f}x PE</div>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-weight:bold; font-size:1.2rem; color:var(--text-color)">${target_price:.2f}</div>
                            <div style="font-size:0.8rem; color:{color}">空间 {upside:+.2f}%</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with c_val2:
            st.markdown("#### 🅱️ 绝对估值法 (DCF Model)")
            st.markdown(f"<div style='font-size:0.8rem; color:gray'>基于未来现金流折现 (WACC: {user_discount_rate}%)</div>", unsafe_allow_html=True)
            
            dcf_upside = (dcf_value - curr_price) / curr_price * 100
            dcf_color = get_status_color(dcf_value, curr_price)
            
            # DCF 大卡片
            st.markdown(f"""
            <div style="background-color:var(--secondary-background-color); border: 2px solid {dcf_color}; border-radius:10px; padding:25px; text-align:center; margin-top:15px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
                <div style="color:gray; font-size:0.9rem; margin-bottom:5px;">DCF 内在价值</div>
                <div style="font-size:2.8rem; font-weight:800; color:{dcf_color}; line-height:1.2;">${dcf_value:.2f}</div>
                <div style="font-size:1.1rem; font-weight:600; color:{dcf_color}; margin-top:5px;">预期回报: {dcf_upside:+.2f}%</div>
            </div>
            """, unsafe_allow_html=True)
            
            # 综合结论
            avg_fair = (pe_scenarios['中性 (Base)']['pe'] * user_eps + dcf_value) / 2
            st.success(f"⚖️ **综合参考价 (Base PE + DCF)**: ${avg_fair:.2f}")

        st.divider()

        # ==========================================
        # 底部：技术分析 (清爽图表)
        # ==========================================
        st.subheader("📉 关键价格行为 (Price Action)")
        
        sr_data = calculate_sr_levels(hist, sensitivity=0.02)
        supports = sorted([x for x in sr_data if x['price'] < curr_price], key=lambda x: x['price'], reverse=True)
        resistances = sorted([x for x in sr_data if x['price'] > curr_price], key=lambda x: x['price'])
        
        col_chart, col_list = st.columns([3, 1])
        
        with col_chart:
            # Plotly 图表配置 - 使用更清爽的配色
            plot_df = hist.iloc[-252:]
            
            fig = go.Figure()
            
            # K线 (经典红绿)
            fig.add_trace(go.Candlestick(
                x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'],
                name='K线', increasing_line_color='#00C805', decreasing_line_color='#FF3B30'
            ))
            
            # 均线 (蓝色)
            fig.add_trace(go.Scatter(
                x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), 
                line=dict(color='#007AFF', width=2), name='MA20'
            ))
            
            # 绘制 SR 线
            for s in supports[:3]:
                fig.add_hline(y=s['price'], line_dash="dot", line_color="green", line_width=1, opacity=0.7)
            for r in resistances[:3]:
                fig.add_hline(y=r['price'], line_dash="dot", line_color="red", line_width=1, opacity=0.7)
            
            # 布局优化：使用 plotly_white 模板，背景更干净
            fig.update_layout(
                template="plotly_white", 
                height=450,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis_rangeslider_visible=False,
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.1)')
            )
            st.plotly_chart(fig, use_container_width=True)
            
        with col_list:
            st.markdown("##### 🛡️ 关键点位")
            
            # 封装显示函数
            def show_level(title, items, color_hex):
                st.markdown(f"<div style='color:{color_hex}; font-weight:bold; margin-top:10px; font-size:0.9rem'>{title}</div>", unsafe_allow_html=True)
                if not items:
                    st.caption("无近期数据")
                else:
                    for item in items[:3]:
                        stars = "★" * min(item['strength'], 4)
                        st.markdown(f"""
                        <div style="display:flex; justify-content:space-between; font-size:0.9rem; border-bottom:1px solid rgba(128,128,128,0.1); padding:4px 0;">
                            <span>${item['price']:.2f}</span>
                            <span style="color:#aaa; font-size:0.7rem">{stars}</span>
                        </div>
                        """, unsafe_allow_html=True)

            show_level("🔴 上方阻力 (卖压)", resistances, "#FF3B30")
            show_level("🟢 下方支撑 (买盘)", supports, "#00C805")

    else:
        st.error("无法获取数据，请检查股票代码是否正确 (如 A股需加后缀 .SS/.SZ)")
