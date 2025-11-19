import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 页面配置 ---
st.set_page_config(page_title="AI 股票全能分析 (Pro版)", layout="wide")
st.title("📈 股票全能分析：趋势 + 估值 + 强弱支撑")

# --- 侧边栏控制 ---
with st.sidebar:
    st.header("1. 股票设置")
    ticker = st.text_input("股票代码", value="AAPL", help="美股: NVDA | A股: 600519.SS | 港股: 0700.HK")
    
    st.header("2. DCF 模型假设")
    growth_rate_input = st.slider("预计未来5年增长率 (%)", 0, 50, 10)
    discount_rate_input = st.slider("折现率 (WACC) (%)", 5, 15, 9)
    terminal_growth_input = st.slider("永续增长率 (%)", 1, 5, 3)
    
    st.header("3. 技术分析设置")
    sr_sensitivity = st.slider("支撑/压力合并阈值 (%)", 1.0, 5.0, 2.0, help="数值越大，合并的范围越广，显示的线条越少但越重要")

# --- 核心函数 ---
@st.cache_data(ttl=3600)
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        # 获取更长一点的历史数据以识别长期支撑压力
        hist = stock.history(period="2y") 
        try:
            info = stock.info
        except:
            info = {}
        return hist, info
    except:
        return None, None

# --- 支撑/压力位计算算法 (核心新增) ---
def calculate_sr_levels(df, sensitivity=0.02):
    """
    算法逻辑：
    1. 寻找局部高点和低点 (Fractals)。
    2. 将价格相近的点聚合在一起 (Cluster)。
    3. 出现次数越多，强度(Strength)越高。
    """
    levels = []
    # 1. 简单的局部极值查找
    for i in range(2, len(df) - 2):
        # 局部低点 (支撑)
        if df['Low'][i] < df['Low'][i-1] and df['Low'][i] < df['Low'][i+1] and \
           df['Low'][i] < df['Low'][i-2] and df['Low'][i] < df['Low'][i+2]:
            levels.append((df['Low'][i], 1)) # 1 代表支撑
            
        # 局部高点 (压力)
        if df['High'][i] > df['High'][i-1] and df['High'][i] > df['High'][i+1] and \
           df['High'][i] > df['High'][i-2] and df['High'][i] > df['High'][i+2]:
            levels.append((df['High'][i], 2)) # 2 代表压力

    levels.sort(key=lambda x: x[0])

    # 2. 聚合相近的层级
    merged_levels = []
    if not levels:
        return []

    current_group = [levels[0]]
    
    for i in range(1, len(levels)):
        price, type_ = levels[i]
        last_avg_price = sum([x[0] for x in current_group]) / len(current_group)
        
        # 如果当前价格在平均价格的阈值范围内 (例如 2%)
        if abs(price - last_avg_price) / last_avg_price <= sensitivity:
            current_group.append(levels[i])
        else:
            # 保存上一组
            avg_price = sum([x[0] for x in current_group]) / len(current_group)
            count = len(current_group)
            merged_levels.append({'price': avg_price, 'strength': count})
            current_group = [levels[i]]
    
    # 保存最后一组
    avg_price = sum([x[0] for x in current_group]) / len(current_group)
    count = len(current_group)
    merged_levels.append({'price': avg_price, 'strength': count})

    return merged_levels

# --- 估值计算逻辑 (保持不变) ---
def calculate_dcf(eps, growth_rate, discount_rate, terminal_growth, years=5):
    flows = []
    future_eps = eps
    for i in range(1, years + 1):
        future_eps = future_eps * (1 + growth_rate / 100)
        discounted_flow = future_eps / ((1 + discount_rate / 100) ** i)
        flows.append(discounted_flow)
    terminal_value = (future_eps * (1 + terminal_growth / 100)) / ((discount_rate - terminal_growth) / 100)
    discounted_terminal_value = terminal_value / ((1 + discount_rate / 100) ** years)
    return sum(flows) + discounted_terminal_value

# --- 主逻辑 ---
if ticker:
    with st.spinner('正在下载数据并进行AI计算...'):
        df, info = get_stock_data(ticker)

    if df is not None and not df.empty:
        current_price = df['Close'].iloc[-1]
        
        # ==========================================
        # 第一部分：基础概览
        # ==========================================
        st.subheader(f"📊 {ticker} 行情仪表盘")
        col1, col2, col3, col4 = st.columns(4)
        
        auto_eps = info.get('trailingEps', 1.0)
        auto_pe = info.get('trailingPE', None)
        
        with col1: st.metric("当前价格", f"{current_price:.2f}")
        with col2: st.metric("EPS (TTM)", f"{auto_eps:.2f}")
        with col3: st.metric("PE (静)", f"{auto_pe:.2f}" if auto_pe else "N/A")
        with col4: 
            change = (current_price - df['Close'].iloc[-2]) / df['Close'].iloc[-2] * 100
            st.metric("日涨跌幅", f"{change:.2f}%", delta=f"{change:.2f}%")

        st.divider()

        # ==========================================
        # 第二部分：智能支撑与压力分析 (新增核心)
        # ==========================================
        st.subheader("🛡️ 智能支撑 & 压力位分析")
        
        # 计算所有层级
        sr_data = calculate_sr_levels(df, sensitivity=sr_sensitivity/100)
        
        # 区分支撑和压力
        supports = sorted([x for x in sr_data if x['price'] < current_price], key=lambda x: x['price'], reverse=True) # 离当前价格最近的支撑在前面
        resistances = sorted([x for x in sr_data if x['price'] > current_price], key=lambda x: x['price']) # 离当前价格最近的压力在前面
        
        sr_col1, sr_col2 = st.columns(2)
        
        with sr_col1:
            st.markdown("#### 🟢 下方支撑 (买入/止损参考)")
            if supports:
                top_supports = supports[:5]
                for i, s in enumerate(top_supports):
                    dist = (s['price'] - current_price) / current_price * 100
                    # 强度可视化：最大5星
                    stars = "⭐" * min(s['strength'], 5) 
                    st.info(f"**支撑 {i+1}**: {s['price']:.2f} (距离 {dist:.1f}%) | 强度: {stars}")
            else:
                st.write("当前价格下方暂无明显支撑数据 (可能处于历史新低)")

        with sr_col2:
            st.markdown("#### 🔴 上方压力 (止盈/抛压参考)")
            if resistances:
                top_resistances = resistances[:5]
                for i, r in enumerate(top_resistances):
                    dist = (r['price'] - current_price) / current_price * 100
                    stars = "⭐" * min(r['strength'], 5)
                    st.warning(f"**压力 {i+1}**: {r['price']:.2f} (距离 +{dist:.1f}%) | 强度: {stars}")
            else:
                st.write("当前价格上方暂无明显压力数据 (可能处于历史新高)")

        # ==========================================
        # 第三部分：K线图 + SR线
        # ==========================================
        st.subheader("📈 交互式 K 线图")
        
        # 只展示最近一年的图表，避免太乱，但SR是基于2年计算的
        plot_df = df.iloc[-252:] 
        
        fig = go.Figure()
        
        # K线
        fig.add_trace(go.Candlestick(x=plot_df.index, 
                                     open=plot_df['Open'], high=plot_df['High'], 
                                     low=plot_df['Low'], close=plot_df['Close'], 
                                     name='K线'))
        
        # 均线
        fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), 
                                 line=dict(color='orange', width=1), name='MA20'))
        
        # 画出最近的3个支撑和3个压力线
        lines_to_plot = supports[:3] + resistances[:3]
        
        for level in lines_to_plot:
            color = 'green' if level['price'] < current_price else 'red'
            line_dash = 'dash' if level['strength'] < 3 else 'solid' # 强度高的用实线
            width = 1 + (min(level['strength'], 5) * 0.5) # 强度越高线越粗
            
            fig.add_hline(y=level['price'], 
                          line_dash=line_dash, 
                          line_color=color, 
                          line_width=width,
                          annotation_text=f"{level['price']:.1f}",
                          annotation_position="bottom right")

        fig.update_layout(
            height=600, 
            xaxis_rangeslider_visible=False, 
            template="plotly_dark",
            title=f"{ticker} 技术走势与关键位"
        )
        st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # ==========================================
        # 第四部分：估值计算 (保留功能)
        # ==========================================
        st.subheader("💰 双重估值计算器")
        
        with st.expander("点击展开估值参数设置", expanded=True):
            input_cols = st.columns(3)
            user_eps = input_cols[0].number_input("EPS (TTM)", value=float(auto_eps), step=0.1)
            
            default_growth = info.get('earningsGrowth', 0.10) * 100 if info.get('earningsGrowth') else growth_rate_input
            user_growth = input_cols[1].number_input("预期增长率 (%)", value=float(default_growth), step=0.5)
            
            default_pe = auto_pe if (auto_pe and 0 < auto_pe < 60) else 20.0
            user_target_pe = input_cols[2].number_input("合理 PE 倍数", value=float(default_pe), step=0.5)

        # 计算
        pe_val = user_eps * user_target_pe
        dcf_val = calculate_dcf(user_eps, user_growth, discount_rate_input, terminal_growth_input)
        
        col_val1, col_val2 = st.columns(2)
        with col_val1:
            upside = (pe_val - current_price)/current_price*100
            st.metric("PE 估值法", f"{pe_val:.2f}", f"{upside:.2f}%")
        with col_val2:
            upside = (dcf_val - current_price)/current_price*100
            st.metric("DCF 现金流法", f"{dcf_val:.2f}", f"{upside:.2f}%")

    else:
        st.error(f"无法获取 {ticker} 数据，请检查代码或网络连接。")
