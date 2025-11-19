import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 页面配置 ---
st.set_page_config(page_title="AI 股票全能分析 (Pro+)", layout="wide")
st.title("📈 股票全能分析：趋势 + 智能估值区间 + 强弱支撑")

# --- 侧边栏 ---
with st.sidebar:
    st.header("1. 股票设置")
    ticker = st.text_input("股票代码", value="NVDA", help="美股: AAPL | A股: 600519.SS | 港股: 0700.HK")
    
    st.header("2. 核心假设")
    # 这里的增长率将直接决定 PE 的取值
    growth_rate_input = st.slider("预计未来3-5年复合增长率 (%)", 0, 80, 15, help="这是决定估值最重要的参数")
    
    st.divider()
    st.caption("数据来源：Yahoo Finance")

# --- 核心函数 ---
@st.cache_data(ttl=3600)
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="2y") 
        try:
            info = stock.info
        except:
            info = {}
        return hist, info
    except:
        return None, None

# --- 支撑/压力位算法 (保持原样) ---
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
    merged_levels = []
    if not levels: return []
    current_group = [levels[0]]
    for i in range(1, len(levels)):
        price, type_ = levels[i]
        last_avg_price = sum([x[0] for x in current_group]) / len(current_group)
        if abs(price - last_avg_price) / last_avg_price <= sensitivity:
            current_group.append(levels[i])
        else:
            avg_price = sum([x[0] for x in current_group]) / len(current_group)
            merged_levels.append({'price': avg_price, 'strength': len(current_group)})
            current_group = [levels[i]]
    avg_price = sum([x[0] for x in current_group]) / len(current_group)
    merged_levels.append({'price': avg_price, 'strength': len(current_group)})
    return merged_levels

# --- 新增：智能 PE 区间生成器 ---
def calculate_fair_value_range(eps, growth_rate, current_pe):
    """
    根据本杰明·格雷厄姆公式和 PEG 理论计算合理 PE 区间
    格雷厄姆公式: V = EPS * (8.5 + 2g)
    """
    # 1. 基础：无增长公司的 PE 基准 (通常 8.5 或者 10)
    base_pe = 8.5 
    
    # 2. 计算三种情景的合理 PE
    
    # 保守 (Bear): 假设增长不及预期，PEG 给 1.0 或 格雷厄姆系数打折
    # 逻辑：PE = 8.5 + 1 * growth (给予增长较少的溢价)
    bear_pe = base_pe + (1.0 * growth_rate)
    # 封顶：防止低速增长股 PE 过低 (至少给 10 倍)
    bear_pe = max(10.0, bear_pe) 
    
    # 中性 (Base): 标准格雷厄姆公式
    # 逻辑：PE = 8.5 + 2 * growth
    base_target_pe = base_pe + (2.0 * growth_rate)
    
    # 乐观 (Bull): 市场情绪高涨，或者 PEG 给到 2.0+
    # 逻辑：在格雷厄姆基础上再溢价 20%，或者参考当前高 PE
    bull_pe = base_target_pe * 1.2
    
    # 修正：如果计算出的 PE 极其夸张 (比如增长率 50% -> PE 108)，进行平滑处理
    # 对于超高增长股，PEG 方法更适用 (PEG=1.5 ~ 2.0)
    if growth_rate > 20:
        bear_pe = growth_rate * 1.0  # PEG = 1
        base_target_pe = growth_rate * 1.5 # PEG = 1.5
        bull_pe = growth_rate * 2.0  # PEG = 2.0
        
    return {
        "bear": {"pe": bear_pe, "price": eps * bear_pe},
        "base": {"pe": base_target_pe, "price": eps * base_target_pe},
        "bull": {"pe": bull_pe, "price": eps * bull_pe}
    }

# --- 主程序 ---
if ticker:
    with st.spinner('正在深入分析基本面与技术面...'):
        df, info = get_stock_data(ticker)

    if df is not None and not df.empty:
        current_price = df['Close'].iloc[-1]
        
        # 获取自动数据
        auto_eps = info.get('trailingEps', 0)
        # 获取市场当前的 PE 水平
        market_ttm_pe = info.get('trailingPE', 0)
        market_fwd_pe = info.get('forwardPE', 0)
        
        # 如果获取不到 EPS，设为 1 防止报错，但在 UI 提示
        if not auto_eps: auto_eps = 1.0

        # ==========================================
        # 1. 估值核心逻辑 (重构部分)
        # ==========================================
        st.subheader("💰 AI 智能估值区间 (基于增长率 & 历史模型)")
        
        # 输入区
        with st.expander("📊 调整估值参数 (EPS & 增长率)", expanded=True):
            c1, c2, c3 = st.columns(3)
            user_eps = c1.number_input("每股收益 (EPS TTM)", value=float(auto_eps), step=0.01, format="%.2f")
            user_growth = c2.number_input("预期年增长率 (%)", value=float(growth_rate_input), step=0.5)
            
            # 展示市场当前的看法
            c3.markdown("##### 市场当前定价:")
            if market_ttm_pe:
                c3.markdown(f"- **当前 PE (TTM)**: `{market_ttm_pe:.2f}`")
            if market_fwd_pe:
                diff = ((market_fwd_pe - market_ttm_pe) / market_ttm_pe) * 100 if market_ttm_pe else 0
                trend = "升" if diff > 0 else "降"
                c3.markdown(f"- **远期 PE (Fwd)**: `{market_fwd_pe:.2f}` (预期估值{trend})")
            else:
                c3.warning("无法获取市场 PE 数据")

        # --- 计算结果 ---
        valuation = calculate_fair_value_range(user_eps, user_growth, market_ttm_pe)
        
        # 制作结果表格
        val_data = {
            "情景": ["🐻 保守 (Bear)", "⚖️ 合理 (Base)", "🐂 乐观 (Bull)"],
            "给予 PE 倍数": [f"{valuation['bear']['pe']:.1f}x", f"{valuation['base']['pe']:.1f}x", f"{valuation['bull']['pe']:.1f}x"],
            "估值价格": [valuation['bear']['price'], valuation['base']['price'], valuation['bull']['price']],
            "安全边际/空间": [
                (valuation['bear']['price'] - current_price) / current_price,
                (valuation['base']['price'] - current_price) / current_price,
                (valuation['bull']['price'] - current_price) / current_price
            ]
        }
        
        # 布局展示
        res_col1, res_col2 = st.columns([2, 1])
        
        with res_col1:
            # 使用 Dataframe 展示，并根据当前价格高亮
            st.markdown("#### 🎯 估值矩阵")
            for i in range(3):
                scen = val_data["情景"][i]
                pe = val_data["给予 PE 倍数"][i]
                price = val_data["估值价格"][i]
                margin = val_data["安全边际/空间"][i] * 100
                
                # 颜色逻辑
                color = "red" if margin < -10 else ("green" if margin > 10 else "orange")
                emoji = "✅" if margin > 0 else "⚠️"
                
                # 卡片式展示
                with st.container():
                    st.markdown(f"""
                    <div style="border:1px solid #333; padding: 10px; border-radius: 5px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
                        <div style="width: 30%;"><b>{scen}</b><br><span style="font-size:0.8em; color:gray;">逻辑: EPS × {pe}</span></div>
                        <div style="font-size: 1.2em; font-weight: bold;">${price:.2f}</div>
                        <div style="color: {color}; text-align: right;">{emoji} {margin:+.2f}%</div>
                    </div>
                    """, unsafe_allow_html=True)

        with res_col2:
            # 仪表盘图示：当前价格在什么位置
            st.markdown("#### 📍 当前价格定位")
            low = valuation['bear']['price'] * 0.8
            high = valuation['bull']['price'] * 1.2
            
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = current_price,
                domain = {'x': [0, 1], 'y': [0, 1]},
                title = {'text': "当前市价", 'font': {'size': 18}},
                delta = {'reference': valuation['base']['price'], 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
                gauge = {
                    'axis': {'range': [low, high], 'tickwidth': 1, 'tickcolor': "white"},
                    'bar': {'color': "white", 'thickness': 0.1}, # 细针
                    'steps': [
                        {'range': [low, valuation['bear']['price']], 'color': "lightgreen"},
                        {'range': [valuation['bear']['price'], valuation['bull']['price']], 'color': "gray"},
                        {'range': [valuation['bull']['price'], high], 'color': "salmon"}],
                    'threshold': {
                        'line': {'color': "cyan", 'width': 4},
                        'thickness': 0.75,
                        'value': valuation['base']['price']}
                }
            ))
            fig_gauge.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20))
            st.plotly_chart(fig_gauge, use_container_width=True)
            st.caption("💡 绿色区: 低估 (买入) | 灰色区: 合理 | 红色区: 高估 (卖出)")
            st.caption(f"蓝线: 理论合理价 {valuation['base']['price']:.2f}")

        st.divider()

        # ==========================================
        # 2. 技术分析 (保留压力支撑功能)
        # ==========================================
        st.subheader(f"📉 {ticker} 技术走势与关键位")
        
        sr_data = calculate_sr_levels(df, sensitivity=0.02)
        supports = sorted([x for x in sr_data if x['price'] < current_price], key=lambda x: x['price'], reverse=True)
        resistances = sorted([x for x in sr_data if x['price'] > current_price], key=lambda x: x['price'])
        
        # 画图
        plot_df = df.iloc[-252:] # 最近一年
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], name='K线'))
        fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), line=dict(color='orange', width=1), name='MA20'))
        
        # 绘制支撑压力线
        for level in supports[:3] + resistances[:3]:
            color = 'green' if level['price'] < current_price else 'red'
            width = 1 + (min(level['strength'], 5) * 0.5)
            fig.add_hline(y=level['price'], line_dash='dash', line_color=color, line_width=width,
                          annotation_text=f"{level['price']:.1f}", annotation_position="bottom right")

        fig.update_layout(height=500, xaxis_rangeslider_visible=False, template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
        
        # 列出具体点位
        c_sr1, c_sr2 = st.columns(2)
        with c_sr1:
            if supports:
                 st.success(f"最近强支撑: **{supports[0]['price']:.2f}** (强度: {'⭐'*min(supports[0]['strength'],5)})")
        with c_sr2:
             if resistances:
                 st.error(f"最近强压力: **{resistances[0]['price']:.2f}** (强度: {'⭐'*min(resistances[0]['strength'],5)})")

    else:
        st.error("无法获取数据，请检查股票代码。")
