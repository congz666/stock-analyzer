import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 页面配置 ---
st.set_page_config(page_title="AI 股票全能分析 (估值版)", layout="wide")
st.title("📈 股票全能分析：趋势 + 双重估值 (PE & DCF)")

# --- 侧边栏控制 ---
with st.sidebar:
    st.header("1. 股票设置")
    ticker = st.text_input("股票代码", value="AAPL", help="美股: NVDA | A股: 600519.SS | 港股: 0700.HK")
    
    st.header("2. DCF 模型假设")
    growth_rate_input = st.slider("预计未来5年增长率 (%)", 0, 50, 10, help="假设公司每年的盈利增长速度")
    discount_rate_input = st.slider("折现率 (WACC) (%)", 5, 15, 9, help="也就是你的预期回报率，通常为 8%-10%")
    terminal_growth_input = st.slider("永续增长率 (%)", 1, 5, 3, help="5年后公司保持的长期低速增长，通常不超过 GDP (2-3%)")
    
    st.markdown("---")
    st.caption("数据来源：Yahoo Finance (若云端限流，请手动填入右侧参数)")

# --- 核心函数 ---
@st.cache_data(ttl=3600)
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        # 尝试获取历史价格 (相对稳定)
        hist = stock.history(period="1y")
        
        # 尝试获取基本面 (极易被封，做强容错处理)
        try:
            info = stock.info
        except:
            info = {}
            
        return hist, info
    except:
        return None, None

# --- 估值计算逻辑 ---
def calculate_pe_valuation(eps, current_pe, industry_pe=20):
    # 简单逻辑：如果当前PE过高，给一个折扣；如果过低，可能低估
    # 这里我们用 "合理PE" 假设为 20-25 (科技股) 或 10-15 (传统股)
    # 为了通用，我们设定一个 conservative_pe
    
    fair_pe = 20 # 默认给个中位数
    if current_pe > 0:
        fair_pe = min(current_pe, 30) # 封顶不给太高
        
    fair_value = eps * fair_pe
    return fair_value, fair_pe

def calculate_dcf(eps, growth_rate, discount_rate, terminal_growth, years=5):
    # 使用 EPS 近似替代 自由现金流 (FCF)，简化模型以便通用
    # 这是一个两阶段模型
    
    flows = []
    future_eps = eps
    
    # 第一阶段：高速增长期
    for i in range(1, years + 1):
        future_eps = future_eps * (1 + growth_rate / 100)
        discounted_flow = future_eps / ((1 + discount_rate / 100) ** i)
        flows.append(discounted_flow)
    
    # 第二阶段：终值 (Terminal Value)
    terminal_value = (future_eps * (1 + terminal_growth / 100)) / ((discount_rate - terminal_growth) / 100)
    discounted_terminal_value = terminal_value / ((1 + discount_rate / 100) ** years)
    
    total_value = sum(flows) + discounted_terminal_value
    return total_value

# --- 主逻辑 ---
if ticker:
    with st.spinner('正在分析数据...'):
        df, info = get_stock_data(ticker)

    if df is not None and not df.empty:
        current_price = df['Close'].iloc[-1]
        
        # ==========================================
        # 第一部分：走势概览
        # ==========================================
        st.subheader(f"📊 {ticker} 走势概览")
        col1, col2, col3 = st.columns(3)
        
        # 提取自动获取的数据，若无则 None
        auto_eps = info.get('trailingEps', None)
        auto_pe = info.get('trailingPE', None)
        
        with col1:
            st.metric("当前价格", f"{current_price:.2f}")
        with col2:
            if auto_pe:
                st.metric("当前市盈率 (PE)", f"{auto_pe:.2f}")
            else:
                st.warning("暂无 PE 数据")
        with col3:
             # 简单的均线趋势
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            trend = "🟢 上升" if current_price > ma20 else "🔴 下跌"
            st.metric("短期趋势 (20日线)", trend)

        st.divider()

        # ==========================================
        # 第二部分：双重估值模型 (核心功能)
        # ==========================================
        st.subheader("💰 合理估值计算器")
        
        # --- 关键：数据输入区 (自动填充 or 手动修改) ---
        st.info("👇 请确认以下基础参数（如果 API 被限流，请手动填入正确数值）：")
        
        input_cols = st.columns(3)
        
        # 1. EPS 输入 (核心参数)
        default_eps = auto_eps if auto_eps else 1.0
        user_eps = input_cols[0].number_input("每股收益 (EPS TTM)", value=float(default_eps), step=0.1, format="%.2f")
        
        # 2. 增长率输入 (DCF用)
        # 如果 info 里有分析师增长预期则使用，否则用侧边栏默认值
        default_growth = info.get('earningsGrowth', 0.10) * 100 if info.get('earningsGrowth') else growth_rate_input
        user_growth = input_cols[1].number_input("预期年增长率 (%)", value=float(default_growth), step=0.5)
        
        # 3. 合理 PE倍数 (PE估值用)
        default_fair_pe = auto_pe if (auto_pe and 0 < auto_pe < 60) else 20.0
        user_target_pe = input_cols[2].number_input("给予合理 PE 倍数", value=float(default_fair_pe), step=0.5, help="你想给这家公司多少倍估值？")

        # --- 开始计算 ---
        
        # 1. PE 估值法
        pe_fair_value = user_eps * user_target_pe
        pe_upside = ((pe_fair_value - current_price) / current_price) * 100
        
        # 2. DCF 估值法
        dcf_fair_value = calculate_dcf(
            eps=user_eps, 
            growth_rate=user_growth, 
            discount_rate=discount_rate_input, 
            terminal_growth=terminal_growth_input
        )
        dcf_upside = ((dcf_fair_value - current_price) / current_price) * 100

        # --- 展示结果 ---
        val_col1, val_col2 = st.columns(2)
        
        with val_col1:
            st.markdown("### 1️⃣ PE 相对估值法")
            st.markdown(f"逻辑：EPS ({user_eps}) × 合理PE ({user_target_pe})")
            if pe_upside > 0:
                st.success(f"估值: **{pe_fair_value:.2f}** (空间: +{pe_upside:.2f}%)")
            else:
                st.error(f"估值: **{pe_fair_value:.2f}** (高估: {pe_upside:.2f}%)")

        with val_col2:
            st.markdown("### 2️⃣ DCF 现金流折现法")
            st.markdown(f"逻辑：未来现金流折现 (WACC: {discount_rate_input}%)")
            if dcf_upside > 0:
                st.success(f"估值: **{dcf_fair_value:.2f}** (空间: +{dcf_upside:.2f}%)")
            else:
                st.error(f"估值: **{dcf_fair_value:.2f}** (高估: {dcf_upside:.2f}%)")
        
        # 综合结论
        avg_val = (pe_fair_value + dcf_fair_value) / 2
        st.caption(f"💡 综合参考价：{avg_val:.2f}")

        st.divider()

        # ==========================================
        # 第三部分：技术走势图
        # ==========================================
        st.subheader("📈 技术走势图")
        
        # 计算布林带
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['Std'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['SMA_20'] + (2 * df['Std'])
        df['Lower'] = df['SMA_20'] - (2 * df['Std'])
        
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper'], line=dict(color='red', width=1, dash='dot'), name='压力位'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower'], line=dict(color='green', width=1, dash='dot'), name='支撑位'))
        
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.error("无法获取数据，请稍后再试。")
