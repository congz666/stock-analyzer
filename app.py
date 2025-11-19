import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import numpy as np

# --- 页面配置 ---
st.set_page_config(page_title="AI 股票终极分析", layout="wide")
st.title("📈 股票终极分析：技术趋势 + 双重估值模型")

# --- 侧边栏：全局设置 ---
with st.sidebar:
    st.header("1. 股票设置")
    ticker = st.text_input("股票代码", value="NVDA", help="美股: TSLA | A股: 600519.SS | 港股: 0700.HK")
    
    st.header("2. 估值核心假设")
    # 这个增长率将同时影响 PE推导 和 DCF计算
    global_growth_rate = st.slider("预期未来3-5年增长率 (%)", 0, 80, 15, help="这是决定估值最重要的参数")
    discount_rate = st.slider("折现率 (WACC) (%)", 5, 15, 9, help="DCF模型使用的预期回报率")
    terminal_growth = st.slider("永续增长率 (%)", 1, 5, 3, help="DCF模型终值阶段的增长率")
    
    st.divider()
    st.caption("数据来源：Yahoo Finance")

# --- 核心算法函数 ---

@st.cache_data(ttl=3600)
def get_stock_data(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="2y") # 获取2年数据以计算支撑压力
        try:
            info = stock.info
        except:
            info = {}
        return hist, info
    except:
        return None, None

def calculate_sr_levels(df, sensitivity=0.02):
    """识别支撑和压力位并计算强度"""
    levels = []
    # 寻找局部极值
    for i in range(2, len(df) - 2):
        # 支撑 (Low point)
        if df['Low'][i] < df['Low'][i-1] and df['Low'][i] < df['Low'][i+1] and \
           df['Low'][i] < df['Low'][i-2] and df['Low'][i] < df['Low'][i+2]:
            levels.append((df['Low'][i], 1))
        # 压力 (High point)
        if df['High'][i] > df['High'][i-1] and df['High'][i] > df['High'][i+1] and \
           df['High'][i] > df['High'][i-2] and df['High'][i] > df['High'][i+2]:
            levels.append((df['High'][i], 2))

    levels.sort(key=lambda x: x[0])
    
    # 聚类合并
    merged_levels = []
    if not levels: return []
    
    current_group = [levels[0]]
    for i in range(1, len(levels)):
        price, type_ = levels[i]
        last_avg = sum([x[0] for x in current_group]) / len(current_group)
        
        if abs(price - last_avg) / last_avg <= sensitivity:
            current_group.append(levels[i])
        else:
            avg_price = sum([x[0] for x in current_group]) / len(current_group)
            merged_levels.append({'price': avg_price, 'strength': len(current_group)})
            current_group = [levels[i]]
            
    avg_price = sum([x[0] for x in current_group]) / len(current_group)
    merged_levels.append({'price': avg_price, 'strength': len(current_group)})
    
    return merged_levels

def calculate_pe_range(eps, growth_rate):
    """基于格雷厄姆公式和PEG推导合理PE区间"""
    base_pe_const = 8.5
    
    # 1. 保守 (Bear)
    bear_pe = max(10.0, base_pe_const + (1.0 * growth_rate))
    
    # 2. 中性 (Base) - 格雷厄姆公式
    base_target_pe = base_pe_const + (2.0 * growth_rate)
    
    # 3. 乐观 (Bull)
    bull_pe = base_target_pe * 1.25
    
    # 修正高增长情况 (当增长率>20%时，格雷厄姆公式会给过高PE，转用PEG修正)
    if growth_rate > 20:
        bear_pe = growth_rate * 1.0  # PEG=1
        base_target_pe = growth_rate * 1.5 # PEG=1.5
        bull_pe = growth_rate * 2.0  # PEG=2.0
        
    return {
        "bear": eps * bear_pe,
        "base": eps * base_target_pe,
        "bull": eps * bull_pe,
        "pe_multipliers": (bear_pe, base_target_pe, bull_pe)
    }

def calculate_dcf(eps, growth_rate, discount_rate, terminal_growth, years=5):
    """DCF 现金流折现模型"""
    flows = []
    future_eps = eps
    # 1. 增长期
    for i in range(1, years + 1):
        future_eps = future_eps * (1 + growth_rate / 100)
        discounted_flow = future_eps / ((1 + discount_rate / 100) ** i)
        flows.append(discounted_flow)
    
    # 2. 永续期 (Terminal Value)
    # 公式: [Final EPS * (1+g)] / (r - g)
    terminal_value = (future_eps * (1 + terminal_growth / 100)) / ((discount_rate - terminal_growth) / 100)
    discounted_terminal_value = terminal_value / ((1 + discount_rate / 100) ** years)
    
    return sum(flows) + discounted_terminal_value

# --- 主逻辑 ---
if ticker:
    with st.spinner('正在整合技术面与基本面数据...'):
        df, info = get_stock_data(ticker)

    if df is not None and not df.empty:
        current_price = df['Close'].iloc[-1]
        auto_eps = info.get('trailingEps', 1.0)
        if not auto_eps: auto_eps = 1.0 # 容错

        # ==========================================
        # 1. 技术分析板块 (K线 + 5档压力支撑)
        # ==========================================
        st.subheader(f"📉 {ticker} 技术分析：关键点位")
        
        # 计算点位
        sr_data = calculate_sr_levels(df, sensitivity=0.02)
        # 支撑：价格 < 现价，按价格从高到低排 (离现价最近的在前)
        supports = sorted([x for x in sr_data if x['price'] < current_price], key=lambda x: x['price'], reverse=True)
        # 压力：价格 > 现价，按价格从低到高排 (离现价最近的在前)
        resistances = sorted([x for x in sr_data if x['price'] > current_price], key=lambda x: x['price'])
        
        # 1.1 展示 5 个压力/支撑区间
        col_tech1, col_tech2 = st.columns(2)
        
        with col_tech1:
            st.markdown("#### 🟢 下方强支撑 (Top 5)")
            if supports:
                for i, s in enumerate(supports[:5]): # 只取前5
                    dist = (s['price'] - current_price) / current_price * 100
                    stars = "⭐" * min(s['strength'], 5)
                    st.info(f"Support {i+1}: **{s['price']:.2f}** (距离 {dist:.1f}%) | 强度: {stars}")
            else:
                st.write("下方暂无明显历史支撑")
                
        with col_tech2:
            st.markdown("#### 🔴 上方强压力 (Top 5)")
            if resistances:
                for i, r in enumerate(resistances[:5]): # 只取前5
                    dist = (r['price'] - current_price) / current_price * 100
                    stars = "⭐" * min(r['strength'], 5)
                    st.warning(f"Resistance {i+1}: **{r['price']:.2f}** (距离 +{dist:.1f}%) | 强度: {stars}")
            else:
                st.write("上方暂无明显历史压力 (可能创新高)")

        # 1.2 绘制 K 线图
        with st.expander("查看交互式 K 线图 (含关键位)", expanded=True):
            plot_df = df.iloc[-252:] # 最近一年
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=plot_df.index, open=plot_df['Open'], high=plot_df['High'], low=plot_df['Low'], close=plot_df['Close'], name='K线'))
            fig.add_trace(go.Scatter(x=plot_df.index, y=plot_df['Close'].rolling(20).mean(), line=dict(color='orange', width=1), name='MA20'))
            
            # 画出最近的 3 个支撑和 3 个压力 (避免图表太乱)
            lines_to_plot = supports[:3] + resistances[:3]
            for level in lines_to_plot:
                color = 'green' if level['price'] < current_price else 'red'
                width = 1 + (min(level['strength'], 5) * 0.5)
                fig.add_hline(y=level['price'], line_dash='dash', line_color=color, line_width=width, opacity=0.7)
                
            fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(t=30,b=20,l=20,r=20))
            st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # ==========================================
        # 2. 双重估值板块 (PE区间 + DCF模型)
        # ==========================================
        st.subheader("💰 双重估值模型")
        st.caption("结合市场情绪 (PE) 与 现金流折现 (DCF) 进行交叉验证")

        # 输入参数微调区
        with st.container():
            cols = st.columns(4)
            user_eps = cols[0].number_input("EPS (TTM)", value=float(auto_eps), step=0.1)
            user_growth = cols[1].number_input("增长率 (%)", value=float(global_growth_rate), step=0.5)
            user_wacc = cols[2].number_input("折现率 WACC (%)", value=float(discount_rate), step=0.5)
            user_tg = cols[3].number_input("永续增长 (%)", value=float(terminal_growth), step=0.1)

        # --- 模型计算 ---
        # A. PE 模型结果
        pe_res = calculate_pe_range(user_eps, user_growth)
        
        # B. DCF 模型结果
        dcf_val = calculate_dcf(user_eps, user_growth, user_wacc, user_tg)
        dcf_upside = (dcf_val - current_price) / current_price * 100

        # --- 结果展示 ---
        val_c1, val_c2 = st.columns([1, 1])
        
        # 左侧：PE 估值矩阵
        with val_c1:
            st.markdown("### 1️⃣ 智能 PE 估值 (相对估值)")
            st.markdown(f"基于增长率 **{user_growth}%** 推导合理 PE 区间")
            
            # 构建 PE 结果数据
            df_pe = pd.DataFrame({
                "情景": ["🐻 保守 (Bear)", "⚖️ 合理 (Base)", "🐂 乐观 (Bull)"],
                "隐含 PE": [f"{x:.1f}x" for x in pe_res['pe_multipliers']],
                "估值价格": [pe_res['bear'], pe_res['base'], pe_res['bull']],
            })
            
            # 自定义展示
            for i, row in df_pe.iterrows():
                p = row['估值价格']
                diff = (p - current_price) / current_price * 100
                color = "red" if diff < -5 else ("green" if diff > 5 else "orange")
                emoji = "📉" if diff < 0 else "📈"
                
                st.markdown(f"""
                <div style="background-color: #262730; padding: 10px; border-radius: 5px; margin-bottom: 8px; border-left: 5px solid {color}">
                    <div style="display:flex; justify-content:space-between;">
                        <span>{row['情景']} <small style="color:gray">({row['隐含 PE']})</small></span>
                        <span style="font-weight:bold; font-size:1.1em">${p:.2f}</span>
                    </div>
                    <div style="text-align:right; font-size:0.9em; color:{color}">{emoji} 空间: {diff:+.2f}%</div>
                </div>
                """, unsafe_allow_html=True)

        # 右侧：DCF 估值 + 仪表盘
        with val_c2:
            st.markdown("### 2️⃣ DCF 现金流估值 (绝对估值)")
            st.markdown(f"基于 WACC **{user_wacc}%** 的内在价值计算")
            
            # DCF 大数字展示
            dcf_color = "green" if dcf_upside > 0 else "red"
            st.metric("DCF 内在价值", f"${dcf_val:.2f}", f"{dcf_upside:.2f}%")
            
            # 仪表盘：当前价格 vs PE合理价 vs DCF合理价
            avg_target = (pe_res['base'] + dcf_val) / 2
            
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = current_price,
                title = {'text': "当前价格 vs 综合目标", 'font': {'size': 15}},
                delta = {'reference': avg_target, 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
                gauge = {
                    'axis': {'range': [min(pe_res['bear'], dcf_val)*0.7, max(pe_res['bull'], dcf_val)*1.2]},
                    'bar': {'color': "white", 'thickness': 0.2},
                    'steps': [
                        {'range': [0, pe_res['bear']], 'color': "#555555"}, # 极低区
                        {'range': [pe_res['bear'], pe_res['bull']], 'color': "#222222"}  # 合理区间背景
                    ],
                    'threshold': {
                        'line': {'color': "cyan", 'width': 4},
                        'thickness': 0.8,
                        'value': avg_target # 综合目标价
                    }
                }
            ))
            fig_gauge.update_layout(height=250, margin=dict(t=30, b=10, l=30, r=30))
            st.plotly_chart(fig_gauge, use_container_width=True)
            
            st.info(f"💡 综合目标价 (PE中值 + DCF): **${avg_target:.2f}**")

    else:
        st.error("无法获取数据，请检查股票代码或网络连接。")
