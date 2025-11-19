import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 1. 页面配置 & CSS 美化 ---
st.set_page_config(page_title="AI 深度投研终端", layout="wide", page_icon="📈")

# 注入自定义 CSS 以美化 UI
st.markdown("""
    <style>
    /* 全局背景微调 */
    .stApp {
        background-color: #0E1117;
    }
    
    /* 卡片样式 */
    .metric-card {
        background-color: #1E1E25;
        border: 1px solid #2E2E38;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .metric-label {
        font-size: 0.9rem;
        color: #A0A0A0;
        margin-bottom: 5px;
    }
    .metric-value {
        font-size: 1.6rem;
        font-weight: bold;
        color: #FFFFFF;
    }
    .metric-delta-up { color: #00E676; font-size: 0.9rem; }
    .metric-delta-down { color: #FF1744; font-size: 0.9rem; }

    /* 估值结果卡片 */
    .val-card {
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 10px;
        border-left: 4px solid #555;
        background-color: #262730;
    }
    
    /* 调整 Sidebar */
    [data-testid="stSidebar"] {
        background-color: #16161D;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心数据获取与计算 ---

@st.cache_data(ttl=3600)
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="2y")
        try:
            info = stock.info
            # 获取财务报表用于计算 CAGR
            financials = stock.income_stmt
        except:
            info = {}
            financials = pd.DataFrame()
        return hist, info, financials
    except:
        return None, None, None

def calculate_historical_cagr(financials):
    """
    计算历史 EPS 和 Revenue 的 CAGR (3-4年)
    """
    metrics = {"eps_cagr": 0.0, "rev_cagr": 0.0, "years": 0}
    
    if financials is None or financials.empty:
        return metrics
    
    try:
        # 获取 Diluted EPS (部分财报 key 可能不同，做容错)
        # 按照列名（日期）排序，新的在左，旧的在右
        financials = financials.sort_index(axis=1, ascending=False)
        
        # 尝试获取最近一年和最远一年（通常yfinance给4年）
        cols = financials.columns
        if len(cols) >= 3:
            latest_year = cols[0]
            oldest_year = cols[-1]
            num_years = len(cols) - 1
            metrics['years'] = num_years
            
            # --- 计算 EPS CAGR ---
            try:
                eps_row = financials.loc['Diluted EPS']
                end_val = eps_row[latest_year]
                start_val = eps_row[oldest_year]
                
                # 只有当起始和结束都是正数时，CAGR才有意义
                if start_val > 0 and end_val > 0:
                    cagr = (end_val / start_val) ** (1 / num_years) - 1
                    metrics['eps_cagr'] = cagr * 100
            except:
                pass

            # --- 计算 Revenue CAGR ---
            try:
                # 尝试不同的 Total Revenue 标签
                rev_key = 'Total Revenue' if 'Total Revenue' in financials.index else 'Total Income'
                if rev_key in financials.index:
                    rev_row = financials.loc[rev_key]
                    end_val = rev_row[latest_year]
                    start_val = rev_row[oldest_year]
                    if start_val > 0 and end_val > 0:
                        cagr = (end_val / start_val) ** (1 / num_years) - 1
                        metrics['rev_cagr'] = cagr * 100
            except:
                pass
                
    except Exception as e:
        print(f"CAGR Calculation Error: {e}")
        
    return metrics

def calculate_sr_levels(df, sensitivity=0.02):
    """技术分析：计算支撑压力位"""
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
        if abs(levels[i][0] - sum(x[0] for x in curr)/len(curr))/(sum(x[0] for x in curr)/len(curr)) <= sensitivity:
            curr.append(levels[i])
        else:
            merged.append({'price': sum(x[0] for x in curr)/len(curr), 'strength': len(curr)})
            curr = [levels[i]]
    merged.append({'price': sum(x[0] for x in curr)/len(curr), 'strength': len(curr)})
    return merged

# --- 3. 主逻辑 ---

with st.sidebar:
    st.markdown("## ⚙️ 参数设置")
    ticker = st.text_input("股票代码", value="NVDA")
    st.caption("支持美股/港股/A股 (如 600519.SS)")
    
    st.markdown("---")
    st.markdown("### 🛠️ 估值模型假设")
    # 初始化占位，后面获取数据后会更新 key
    user_discount_rate = st.slider("折现率 WACC (%)", 5.0, 15.0, 9.0, 0.5)
    user_terminal_growth = st.slider("永续增长率 (%)", 1.0, 5.0, 3.0, 0.5)

if ticker:
    with st.spinner('正在挖掘历史财报与行情数据...'):
        hist, info, financials = get_stock_data(ticker)
        
    if hist is not None:
        # --- 数据预处理 ---
        curr_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        price_change = (curr_price - prev_close) / prev_close * 100
        
        # 获取历史 CAGR
        cagr_data = calculate_historical_cagr(financials)
        hist_eps_cagr = cagr_data.get('eps_cagr', 0)
        hist_rev_cagr = cagr_data.get('rev_cagr', 0)
        
        # 确定默认增长率：优先用分析师预期，其次用历史EPS CAGR，最后兜底10%
        analyst_growth = info.get('earningsGrowth', 0) * 100 if info.get('earningsGrowth') else 0
        default_growth = analyst_growth if analyst_growth > 0 else (hist_eps_cagr if hist_eps_cagr > 0 else 10.0)
        
        # ==========================================
        # Header: 关键指标卡片
        # ==========================================
        st.title(f"{info.get('shortName', ticker)} ({ticker})")
        
        m1, m2, m3, m4 = st.columns(4)
        
        def metric_html(label, value, delta=None, suffix=""):
            delta_html = ""
            if delta is not None:
                color = "metric-delta-up" if delta > 0 else "metric-delta-down"
                sign = "+" if delta > 0 else ""
                delta_html = f'<span class="{color}">{sign}{delta:.2f}%</span>'
            
            return f"""
            <div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}{suffix}</div>
                {delta_html}
            </div>
            """

        with m1: st.markdown(metric_html("当前价格", f"{curr_price:.2f}", price_change), unsafe_allow_html=True)
        with m2: st.markdown(metric_html("PE (TTM)", f"{info.get('trailingPE', 0):.2f}"), unsafe_allow_html=True)
        with m3: st.markdown(metric_html("EPS (TTM)", f"{info.get('trailingEps', 0):.2f}"), unsafe_allow_html=True)
        with m4: st.markdown(metric_html(f"历史{cagr_data['years']}年 EPS复合增长", f"{hist_eps_cagr:.1f}", suffix="%"), unsafe_allow_html=True)

        st.markdown("---")

        # ==========================================
        # Section 1: 双重估值模型 (更紧凑的布局)
        # ==========================================
        st.subheader("💰 智能估值中心")
        
        # 估值控制栏 (放在一行)
        with st.container():
            st.markdown("#### 1. 确认核心假设")
            c_in1, c_in2, c_in3 = st.columns([1, 1, 2])
            
            # 智能推荐增长率
            growth_help = f"历史CAGR: {hist_eps_cagr:.1f}% | 分析师预期: {analyst_growth:.1f}%"
            user_growth = c_in1.number_input("预期未来增长率 (%)", value=float(default_growth), step=0.5, help=growth_help)
            user_eps = c_in2.number_input("基准 EPS", value=float(info.get('trailingEps', 1.0)), step=0.1)
            c_in3.info(f"💡 **智能提示**：根据财报数据，该公司过去 {cagr_data['years']} 年营收增长 **{hist_rev_cagr:.1f}%**，利润增长 **{hist_eps_cagr:.1f}%**。建议保守取值。")

        # --- 计算逻辑 ---
        # PE 逻辑
        base_pe = 8.5 + 2 * user_growth
        if user_growth > 20: base_pe = user_growth * 1.5 # PEG修正
        pe_targets = {'Bear': base_pe*0.8, 'Base': base_pe, 'Bull': base_pe*1.2}
        pe_vals = {k: v * user_eps for k,v in pe_targets.items()}
        
        # DCF 逻辑
        future_eps = user_eps
        dcf_sum = 0
        for i in range(1, 6):
            future_eps *= (1 + user_growth/100)
            dcf_sum += future_eps / ((1 + user_discount_rate/100)**i)
        term_val = (future_eps * (1+user_terminal_growth/100)) / ((user_discount_rate - user_terminal_growth)/100)
        dcf_val = dcf_sum + term_val / ((1 + user_discount_rate/100)**5)
        
        # --- 估值展示 ---
        v_col1, v_col2 = st.columns(2)
        
        with v_col1:
            st.markdown("#### 🅰️ 相对估值 (PE法)")
            st.caption(f"基于增长率 {user_growth}% 推导合理 PE")
            
            # 动态颜色函数
            def get_color(target_price, current):
                diff = (target_price - current) / current
                if diff > 0.15: return "#00E676" # Green
                if diff < -0.15: return "#FF1744" # Red
                return "#FF9100" # Orange
            
            for scenario, val in pe_vals.items():
                color = get_color(val, curr_price)
                upside = (val - curr_price) / curr_price * 100
                st.markdown(f"""
                <div class="val-card" style="border-left-color: {color};">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:1rem; font-weight:bold;">{scenario} (PE {pe_targets[scenario]:.1f}x)</span>
                        <span style="font-size:1.2rem; color:#FFF;">${val:.2f}</span>
                    </div>
                    <div style="text-align:right; font-size:0.9rem; color:{color};">
                        {'🚀' if upside>0 else '⚠️'} 空间: {upside:+.2f}%
                    </div>
                </div>
                """, unsafe_allow_html=True)

        with v_col2:
            st.markdown("#### 🅱️ 绝对估值 (DCF法)")
            st.caption(f"基于 WACC {user_discount_rate}% 现金流折现")
            
            dcf_upside = (dcf_val - curr_price) / curr_price * 100
            dcf_color = get_color(dcf_val, curr_price)
            
            st.markdown(f"""
            <div style="background:#1E1E25; border:2px solid {dcf_color}; border-radius:10px; padding:20px; text-align:center; margin-top:10px;">
                <div style="color:#888; margin-bottom:5px;">DCF 内在价值</div>
                <div style="font-size:2.5rem; font-weight:bold; color:{dcf_color};">${dcf_val:.2f}</div>
                <div style="font-size:1.1rem; color:{dcf_color}; margin-top:5px;">
                    {dcf_upside:+.2f}% 潜在空间
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # 综合建议
            avg_price = (pe_vals['Base'] + dcf_val) / 2
            st.info(f"⚖️ **综合参考价**: ${avg_price:.2f}")

        st.markdown("---")

        # ==========================================
        # Section 2: 技术分析 (Pro Chart)
        # ==========================================
        st.subheader("📉 关键点位透视")
        
        sr_data = calculate_sr_levels(hist, sensitivity=0.02)
        supports = sorted([x for x in sr_data if x['price'] < curr_price], key=lambda x: x['price'], reverse=True)
        resistances = sorted([x for x in sr_data if x['price'] > curr_price], key=lambda x: x['price'])
        
        c_tech1, c_tech2 = st.columns([3, 1])
        
        with c_tech1:
            # Plotly 图表美化
            plot_df = hist.iloc[-252:]
            fig = go.Figure()
            
            # K线
            fig.add_trace(go.Candlestick(
                x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'],
                name='Price', increasing_line_color='#00E676', decreasing_line_color='#FF1744'
            ))
            
            # 均线
            fig.add_trace(go.Scatter(
                x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), 
                line=dict(color='#2979FF', width=1.5), name='MA20'
            ))
            
            # SR 线
            for s in supports[:3]:
                fig.add_hline(y=s['price'], line_dash="dot", line_color="#00E676", opacity=0.6, annotation_text="Sup", annotation_position="top left")
            for r in resistances[:3]:
                fig.add_hline(y=r['price'], line_dash="dot", line_color="#FF1744", opacity=0.6, annotation_text="Res", annotation_position="bottom left")
                
            fig.update_layout(
                height=500, 
                margin=dict(l=10, r=10, t=30, b=10),
                paper_bgcolor='rgba(0,0,0,0)', # 透明背景
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis_rangeslider_visible=False,
                font=dict(color="#A0A0A0"),
                xaxis=dict(showgrid=False), # 去除网格
                yaxis=dict(showgrid=True, gridcolor="#333")
            )
            st.plotly_chart(fig, use_container_width=True)
            
        with c_tech2:
            st.markdown("##### 🎯 关键位置")
            
            st.markdown("<div style='font-size:0.8rem; color:#FF1744; margin-top:10px;'>🔴 上方抛压</div>", unsafe_allow_html=True)
            if resistances:
                for r in resistances[:3]:
                    st.markdown(f"<div style='border-bottom:1px solid #333; padding:5px; display:flex; justify-content:space-between;'><span>${r['price']:.1f}</span> <span>{'⭐'*min(r['strength'],3)}</span></div>", unsafe_allow_html=True)
            else:
                st.caption("上方无阻力")

            st.markdown("<div style='font-size:0.8rem; color:#00E676; margin-top:20px;'>🟢 下方接盘</div>", unsafe_allow_html=True)
            if supports:
                for s in supports[:3]:
                    st.markdown(f"<div style='border-bottom:1px solid #333; padding:5px; display:flex; justify-content:space-between;'><span>${s['price']:.1f}</span> <span>{'⭐'*min(s['strength'],3)}</span></div>", unsafe_allow_html=True)
            else:
                st.caption("深不见底")
