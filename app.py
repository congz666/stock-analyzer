import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import requests

# 设置页面配置
st.set_page_config(page_title="AI 股票智能分析助手", layout="wide")

# --- 核心修复：配置请求头，伪装成浏览器 ---
def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    return session

# --- 核心修复：添加缓存装饰器 (TTL=3600秒，即1小时内查同一个票不重复请求) ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_data(ticker_input, period_input):
    try:
        # 使用自定义 session 绕过简单的反爬
        session = get_session()
        stock = yf.Ticker(ticker_input, session=session)
        
        # 获取历史数据
        hist = stock.history(period=period_input)
        
        # 获取基本信息 (容易触发限流，加异常处理)
        try:
            info = stock.info
        except:
            info = {} # 如果获取信息失败，返回空字典，不影响K线图显示
            
        return hist, info
    except Exception as e:
        return None, None

# 标题
st.title("📈 股票趋势与估值分析工具 (防限流版)")
st.markdown("输入股票代码，获取基于技术指标的短期预测、压力位及估值参考。")

# 侧边栏
st.sidebar.header("参数设置")
ticker_symbol = st.sidebar.text_input("输入股票代码", value="AAPL", help="美股: AAPL, NVDA | A股: 600519.SS")
period = st.sidebar.selectbox("分析周期", ["3mo", "6mo", "1y"], index=1)
force_refresh = st.sidebar.button("强制刷新数据")

if force_refresh:
    st.cache_data.clear() # 清除缓存

# 主逻辑
if ticker_symbol:
    with st.spinner('正在拉取数据 (首次加载可能稍慢)...'):
        df, stock_info = get_stock_data(ticker_symbol, period)

    if df is not None and not df.empty:
        # --- 1. 数据预处理 ---
        current_price = df['Close'].iloc[-1]
        
        # 计算指标
        df['SMA_5'] = df['Close'].rolling(window=5).mean()
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        df['Middle_Band'] = df['Close'].rolling(window=20).mean()
        df['Std_Dev'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['Middle_Band'] + (2 * df['Std_Dev'])
        df['Lower_Band'] = df['Middle_Band'] - (2 * df['Std_Dev'])

        # --- 2. 页面布局 ---
        col1, col2, col3 = st.columns(3)
        
        # 计算涨跌
        prev_close = df['Close'].iloc[-2]
        change_val = current_price - prev_close
        change_pct = (change_val / prev_close) * 100
        
        with col1:
            st.metric("当前价格", f"{current_price:.2f}", f"{change_val:.2f} ({change_pct:.2f}%)")
        
        with col2:
            # 趋势判断
            trend_txt = "震荡"
            color = "orange"
            if df['SMA_5'].iloc[-1] > df['SMA_20'].iloc[-1]:
                trend_txt = "🚀 短期偏多"
                color = "green"
            elif df['SMA_5'].iloc[-1] < df['SMA_20'].iloc[-1]:
                trend_txt = "🔻 短期偏空"
                color = "red"
            st.markdown(f"**趋势信号:** :{color}[{trend_txt}]")

        with col3:
            # 估值 (容错处理，因为 Info 可能获取失败)
            if stock_info and 'targetMeanPrice' in stock_info:
                target = stock_info['targetMeanPrice']
                if target:
                    upside = ((target - current_price) / current_price) * 100
                    st.metric("分析师目标价", f"{target}", f"{upside:.2f}%")
                else:
                    st.write("暂无分析师目标价")
            else:
                st.write("估值数据暂时不可用")

        st.divider()

        # --- 3. 压力与支撑 ---
        c1, c2 = st.columns(2)
        resistance = df['Upper_Band'].iloc[-1]
        support = df['Lower_Band'].iloc[-1]
        
        with c1:
            st.info(f"🛡️ **支撑位: {support:.2f}**")
        with c2:
            st.warning(f"🧗 **压力位: {resistance:.2f}**")

        # --- 4. 绘图 ---
        st.subheader("技术走势图")
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name='K线'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='red', width=1, dash='dot'), name='压力位'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='green', width=1, dash='dot'), name='支撑位'))
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1), name='20日线'))
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.error("无法获取数据。原因可能是：\n1. 股票代码错误。\n2. 访问过于频繁，请等待 1 分钟后再试。\n3. 刚刚部署，服务器IP需要“冷却”一下。")

st.caption("数据来源: Yahoo Finance | 提示: 如果遇到 Rate Limited，请稍等片刻或刷新页面。")
