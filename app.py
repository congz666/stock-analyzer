import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# 设置页面配置
st.set_page_config(page_title="AI 股票智能分析助手", layout="wide")

# 标题
st.title("📈 股票趋势与估值分析工具")
st.markdown("输入股票代码，获取基于技术指标的短期预测、压力位及估值参考。")

# 侧边栏输入
st.sidebar.header("参数设置")
ticker_symbol = st.sidebar.text_input("输入股票代码", value="AAPL", help="美股直接输代码(如NVDA)，A股加后缀(如600519.SS)")
period = st.sidebar.selectbox("分析周期", ["3mo", "6mo", "1y"], index=1)

# 核心分析函数
def analyze_stock(ticker_input):
    try:
        stock = yf.Ticker(ticker_input)
        hist = stock.history(period=period)
        
        if hist.empty:
            st.error("未找到数据，请检查股票代码是否正确（A股请加 .SS 或 .SZ 后缀）。")
            return None, None
            
        info = stock.info
        return hist, info
    except Exception as e:
        st.error(f"发生错误: {e}")
        return None, None

# 主逻辑
if st.button("开始分析") or ticker_symbol:
    with st.spinner('正在拉取数据并计算模型...'):
        df, stock_info = analyze_stock(ticker_symbol)

    if df is not None:
        # --- 1. 数据预处理与计算 ---
        current_price = df['Close'].iloc[-1]
        
        # 计算移动平均线
        df['SMA_5'] = df['Close'].rolling(window=5).mean()
        df['SMA_20'] = df['Close'].rolling(window=20).mean()
        
        # 计算布林带 (用于压力/支撑)
        df['Middle_Band'] = df['Close'].rolling(window=20).mean()
        df['Std_Dev'] = df['Close'].rolling(window=20).std()
        df['Upper_Band'] = df['Middle_Band'] + (2 * df['Std_Dev']) # 压力位
        df['Lower_Band'] = df['Middle_Band'] - (2 * df['Std_Dev']) # 支撑位

        # --- 2. 页面布局展示 ---
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("当前价格", f"{current_price:.2f}", f"{current_price - df['Close'].iloc[-2]:.2f}")
        with col2:
            # 短期趋势判断逻辑
            trend = "震荡/不确定"
            if df['SMA_5'].iloc[-1] > df['SMA_20'].iloc[-1] and current_price > df['SMA_5'].iloc[-1]:
                trend = "🚀 短期看涨 (多头排列)"
                color = "green"
            elif df['SMA_5'].iloc[-1] < df['SMA_20'].iloc[-1] and current_price < df['SMA_5'].iloc[-1]:
                trend = "🔻 短期看跌 (空头排列)"
                color = "red"
            else:
                trend = "⚖️ 震荡整理"
                color = "orange"
            st.markdown(f"**短期走势预测:**")
            st.markdown(f":{color}[{trend}]")

        with col3:
            # 估值逻辑 (使用分析师目标价)
            target_mean = stock_info.get('targetMeanPrice', None)
            if target_mean:
                upside = ((target_mean - current_price) / current_price) * 100
                val_status = "低估" if upside > 0 else "高估"
                st.metric("华尔街目标均价 (合理估值)", f"{target_mean}", f"{upside:.2f}% 空间")
            else:
                pe_ratio = stock_info.get('trailingPE', 'N/A')
                st.metric("市盈率 (PE)", f"{pe_ratio}", "无目标价数据")

        st.divider()

        # --- 3. 压力位与支撑位 ---
        c1, c2 = st.columns(2)
        
        resistance = df['Upper_Band'].iloc[-1]
        support = df['Lower_Band'].iloc[-1]
        
        with c1:
            st.info(f"🛡️ **下方支撑位 (Support): {support:.2f}**\n\n若跌破此价格，可能会开启下跌通道。")
        with c2:
            st.warning(f"🧗 **上方压力位 (Resistance): {resistance:.2f}**\n\n若突破此价格，上涨空间可能打开。")

        # --- 4. 交互式K线图 ---
        st.subheader("技术走势图 (含布林带)")
        
        fig = go.Figure()
        
        # K线
        fig.add_trace(go.Candlestick(x=df.index,
                        open=df['Open'], high=df['High'],
                        low=df['Low'], close=df['Close'],
                        name='K线'))
        
        # 均线和布林带
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper_Band'], line=dict(color='red', width=1, dash='dot'), name='压力位 (布林上轨)'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower_Band'], line=dict(color='green', width=1, dash='dot'), name='支撑位 (布林下轨)'))
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1), name='20日均线'))

        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # --- 5. 详细基本面数据 ---
        with st.expander("查看更多基本面数据"):
            info_cols = st.columns(4)
            info_cols[0].write(f"**市值:** {stock_info.get('marketCap', 'N/A')}")
            info_cols[1].write(f"**52周最高:** {stock_info.get('fiftyTwoWeekHigh', 'N/A')}")
            info_cols[2].write(f"**52周最低:** {stock_info.get('fiftyTwoWeekLow', 'N/A')}")
            info_cols[3].write(f"**贝塔值 (波动率):** {stock_info.get('beta', 'N/A')}")

    else:
        st.info("请输入股票代码并点击分析。例如：AAPL, MSFT, 600519.SS")

# 免责声明
st.caption("⚠️ 免责声明：本工具仅基于历史数据进行技术指标计算，不构成任何投资建议。市场有风险，投资需谨慎。")
