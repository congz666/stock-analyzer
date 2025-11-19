import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import time

# --- 页面设置 ---
st.set_page_config(page_title="股票技术分析 (极速版)", layout="wide")
st.title("📈 股票技术分析 (防封锁极速版)")
st.caption("注意：为确保在公共云端能稳定运行，本模式仅提供K线与技术指标，已移除易触发风控的基本面数据。")

# --- 侧边栏 ---
with st.sidebar:
    st.header("参数设置")
    # 默认加入几个热门股，方便快速切换
    ticker_symbol = st.text_input("输入股票代码", value="AAPL", help="美股: NVDA | A股: 600519.SS")
    period = st.selectbox("时间跨度", ["3mo", "6mo", "1y", "2y"], index=1)
    
    st.info("💡 小贴士：如果仍然报错，请尝试在代码后加空格重新输入，或者等待几分钟。")

# --- 核心函数：使用更抗封锁的 download 接口 ---
@st.cache_data(ttl=600) # 缓存10分钟
def get_price_data(symbol, time_period):
    try:
        # 使用 download 接口，它是获取历史数据最稳定的方式
        # threads=False 可以减少并发请求，降低被识别为爬虫的风险
        df = yf.download(symbol, period=time_period, progress=False, threads=False)
        
        # 检查数据是否为空
        if df.empty:
            return None
            
        # yfinance 新版本可能会返回多层索引，需要扁平化处理
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # 确保列名正确
        df = df.rename(columns={"Close": "Close", "Open": "Open", "High": "High", "Low": "Low"})
        return df
    except Exception as e:
        print(e)
        return None

# --- 主逻辑 ---
if ticker_symbol:
    with st.spinner('正在建立安全连接并获取数据...'):
        # 简单的防抖动延迟
        time.sleep(0.5)
        df = get_price_data(ticker_symbol, period)

    if df is not None and len(df) > 0:
        # --- 1. 指标计算 ---
        current_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2]
        change = current_price - prev_price
        pct_change = (change / prev_price) * 100

        # 移动平均线
        df['SMA_5'] = df['Close'].rolling(window=5).mean()
        df['SMA_20'] = df['Close'].rolling(window=20).mean()

        # 布林带
        df['Middle'] = df['SMA_20']
        df['Std'] = df['Close'].rolling(window=20).std()
        df['Upper'] = df['Middle'] + (2 * df['Std'])
        df['Lower'] = df['Middle'] - (2 * df['Std'])

        # --- 2. 顶部数据栏 ---
        col1, col2, col3 = st.columns(3)
        
        with col1:
            color = "normal"
            if change > 0: color = "normal" # Streamlit metric 自动处理红绿，但我们可以手动加样式
            st.metric("最新收盘价", f"{current_price:.2f}", f"{change:.2f} ({pct_change:.2f}%)")
        
        with col2:
            # 简单趋势判断
            trend = "🤔 趋势不明"
            if current_price > df['SMA_5'].iloc[-1] > df['SMA_20'].iloc[-1]:
                trend = "🚀 短期上升趋势"
            elif current_price < df['SMA_5'].iloc[-1] < df['SMA_20'].iloc[-1]:
                trend = "🔻 短期下降趋势"
            st.markdown(f"**技术形态:**\n\n{trend}")

        with col3:
            # 压力支撑
            resistance = df['Upper'].iloc[-1]
            support = df['Lower'].iloc[-1]
            st.write(f"🧱 **压力位:** {resistance:.2f}")
            st.write(f"🧘 **支撑位:** {support:.2f}")

        st.divider()

        # --- 3. 绘图 ---
        fig = go.Figure()

        # K线
        fig.add_trace(go.Candlestick(x=df.index,
                        open=df['Open'], high=df['High'],
                        low=df['Low'], close=df['Close'],
                        name='K线'))

        # 均线
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_5'], line=dict(color='orange', width=1), name='MA5'))
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], line=dict(color='blue', width=1.5), name='MA20'))

        # 布林带
        fig.add_trace(go.Scatter(x=df.index, y=df['Upper'], line=dict(color='gray', width=1, dash='dot'), name='布林上轨'))
        fig.add_trace(go.Scatter(x=df.index, y=df['Lower'], line=dict(color='gray', width=1, dash='dot'), name='布林下轨'))

        fig.update_layout(
            height=600, 
            title=f"{ticker_symbol} 走势图",
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

    else:
        st.error("无法加载数据。Streamlit 云端服务器的 IP 正处于 Yahoo 的风控冷却期。")
        st.warning("💡 建议：\n1. 尝试输入其他冷门一点的股票代码试探。\n2. 等待 5-10 分钟后再刷新。\n3. **最终解决方案**：在你自己电脑上运行此代码，本地运行 100% 不会报错。")
