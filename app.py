# -*- coding: utf-8 -*-
"""
マイ資産ボード - 保有ファンドの連動指数(リアルタイム)と基準価額(日次)を表示
Streamlit Community Cloud で動作 / 完全無料構成
"""
import io
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

# ==============================================================
# 設定: 保有ファンド一覧
# --------------------------------------------------------------
# index_ticker : yfinance のティッカー(連動指数 or 代替ETF)
# isin / fund_cd : 投信協会の基準価額CSV用コード(「使い方」タブ参照)
#                  None のファンドは基準価額タブに表示されません
# ==============================================================
FUNDS = [
    # --- コア(積立中) ---
    dict(name="オルカン(全世界株式)", group="コア(積立中)",
         index_ticker="ACWI", index_label="MSCI ACWI",
         isin="JP90C000H1T1", fund_cd="0331418A"),
    dict(name="ゴールド", group="コア(積立中)",
         index_ticker="GC=F", index_label="金先物(COMEX)",
         isin=None, fund_cd=None),
    # --- サテライト ---
    dict(name="ニッセイSOX指数", group="サテライト",
         index_ticker="^SOX", index_label="SOX指数",
         isin=None, fund_cd=None),
    # --- iDeCo ---
    dict(name="iDeCo 先進国株式(除く日本)", group="iDeCo",
         index_ticker="TOK", index_label="MSCIコクサイ(ETF)",
         isin=None, fund_cd=None),
    # --- レガシー(NISA) ---
    dict(name="eMAXIS Slim S&P500", group="レガシー",
         index_ticker="^GSPC", index_label="S&P500",
         isin="JP90C000GKC6", fund_cd="03311187"),
    dict(name="楽天・全米株式", group="レガシー",
         index_ticker="VTI", index_label="米国株全体(VTI)",
         isin=None, fund_cd=None),
    dict(name="SBI・V・全米株式", group="レガシー",
         index_ticker="VTI", index_label="米国株全体(VTI)",
         isin=None, fund_cd=None),
    dict(name="iFreeNEXT NASDAQ100", group="レガシー",
         index_ticker="^NDX", index_label="NASDAQ100",
         isin=None, fund_cd=None),
    dict(name="iFreeNEXT FANG+", group="レガシー",
         index_ticker="^NYFANG", index_label="NYSE FANG+",
         isin=None, fund_cd=None),
    dict(name="Mega10(米国大型株)", group="レガシー",
         index_ticker="^NDX", index_label="NASDAQ100(代替)",
         isin=None, fund_cd=None),
    dict(name="TOPIX", group="レガシー",
         index_ticker="1306.T", index_label="TOPIX連動ETF",
         isin=None, fund_cd=None),
]

GROUP_ORDER = ["コア(積立中)", "サテライト", "iDeCo", "レガシー"]
GROUP_COLOR = {
    "コア(積立中)": "#1a7f5a",
    "サテライト": "#b8860b",
    "iDeCo": "#4169aa",
    "レガシー": "#8a8a8a",
}
PERIODS = {"1日": ("1d", "5m"), "5日": ("5d", "30m"),
           "1ヶ月": ("1mo", "1d"), "6ヶ月": ("6mo", "1d"),
           "1年": ("1y", "1d"), "3年": ("3y", "1wk")}

st.set_page_config(page_title="マイ資産ボード", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
  div[data-testid="stMetric"] {
      background: #ffffff; border: 1px solid #e6e6e6;
      border-radius: 12px; padding: 10px 14px;
      box-shadow: 0 1px 3px rgba(0,0,0,.06);
  }
  div[data-testid="stMetricLabel"] {font-size: 0.78rem;}
  .group-badge {
      display: inline-block; color: #fff; font-size: 0.75rem;
      font-weight: 600; padding: 2px 10px; border-radius: 999px;
      margin: 6px 0 2px 0;
  }
</style>
""", unsafe_allow_html=True)


# ==============================================================
# データ取得
# ==============================================================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_index_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """yfinance から指数の履歴を取得(5分キャッシュ)"""
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    return df if df is not None else pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_daily_change(ticker: str):
    """直近終値と前営業日終値から騰落率を計算"""
    df = yf.Ticker(ticker).history(period="5d", interval="1d")
    if df is None or len(df) < 2:
        return None, None
    last, prev = df["Close"].iloc[-1], df["Close"].iloc[-2]
    return float(last), (last / prev - 1) * 100


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_nav(isin: str, fund_cd: str) -> pd.DataFrame:
    """投信協会サイトから基準価額CSVを取得(6時間キャッシュ)"""
    url = ("https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download"
           f"?isinCd={isin}&associFundCd={fund_cd}")
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), encoding="shift_jis")
    df.columns = [c.strip() for c in df.columns]
    date_col = df.columns[0]
    nav_col = next(c for c in df.columns if "基準価額" in c)
    df[date_col] = pd.to_datetime(df[date_col], format="%Y年%m月%d日",
                                  errors="coerce")
    df = df.dropna(subset=[date_col]).rename(
        columns={date_col: "date", nav_col: "nav"})
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    return df[["date", "nav"]].dropna()


def line_chart(df: pd.DataFrame, x, y, name: str, color: str = "#1a7f5a"):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df[x], y=df[y], mode="lines", name=name,
                             line=dict(width=2.2, color=color),
                             fill="tozeroy",
                             fillcolor=color.replace(")", ",0.08)")
                             if color.startswith("rgba") else None))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                      showlegend=False, hovermode="x unified",
                      yaxis=dict(tickformat=",.0f"),
                      title=dict(text=name, font=dict(size=14)))
    return fig


# ==============================================================
# 画面
# ==============================================================
st.title("📊 マイ資産ボード")
st.caption(f"最終更新: {dt.datetime.now():%Y-%m-%d %H:%M} / "
           "指数は5分・基準価額は6時間キャッシュ")

tab_sum, tab_idx, tab_nav, tab_help = st.tabs(
    ["🏠 サマリー", "📈 指数チャート", "💹 基準価額", "📖 使い方"])

# --------------------------------------------------------------
# タブ1: サマリー
# --------------------------------------------------------------
with tab_sum:
    # 為替
    fx_last, fx_chg = fetch_daily_change("JPY=X")
    if fx_last:
        c1, c2 = st.columns(2)
        c1.metric("💱 ドル円", f"{fx_last:,.2f} 円",
                  f"{fx_chg:+.2f} %")
        c2.metric("為替の影響",
                  "円安 → 外貨資産に追い風" if fx_chg and fx_chg > 0
                  else "円高 → 外貨資産に向かい風",
                  delta=None)
    st.divider()

    # 重複ティッカーは1回だけ取得
    seen = {}
    for g in GROUP_ORDER:
        funds = [f for f in FUNDS if f["group"] == g]
        if not funds:
            continue
        st.markdown(
            f'<span class="group-badge" '
            f'style="background:{GROUP_COLOR[g]}">{g}</span>',
            unsafe_allow_html=True)
        cols = st.columns(2)
        for i, f in enumerate(funds):
            t = f["index_ticker"]
            if t not in seen:
                seen[t] = fetch_daily_change(t)
            last, chg = seen[t]
            with cols[i % 2]:
                if last is None:
                    st.metric(f["name"], "取得失敗", "—")
                else:
                    st.metric(f["name"],
                              f"{last:,.2f}",
                              f"{chg:+.2f} % ({f['index_label']})")

    st.info("騰落率は連動指数(現地通貨ベース)の前営業日比です。"
            "円建ての実感値は「指数騰落率 + ドル円騰落率」が目安になります。")

# --------------------------------------------------------------
# タブ2: 指数チャート(比較)
# --------------------------------------------------------------
with tab_idx:
    period_label = st.radio("期間", list(PERIODS.keys()),
                            horizontal=True, index=2)
    period, interval = PERIODS[period_label]

    options = sorted({(f["index_label"], f["index_ticker"]) for f in FUNDS})
    default_sel = ["MSCI ACWI", "金先物(COMEX)", "S&P500", "SOX指数"]
    sel = st.multiselect("表示する指数(複数選択で比較)",
                         [o[0] for o in options],
                         default=[d for d in default_sel
                                  if d in [o[0] for o in options]])

    if sel:
        fig = go.Figure()
        palette = ["#1a7f5a", "#b8860b", "#4169aa", "#c0392b",
                   "#7d3c98", "#16a085", "#d35400", "#2c3e50"]
        for i, label in enumerate(sel):
            ticker = dict(options)[label]
            df = fetch_index_history(ticker, period, interval)
            if df.empty:
                st.warning(f"{label}: データ取得に失敗しました")
                continue
            base = df["Close"].iloc[0]
            fig.add_trace(go.Scatter(
                x=df.index, y=(df["Close"] / base - 1) * 100,
                mode="lines", name=label,
                line=dict(width=2.2, color=palette[i % len(palette)])))
        fig.update_layout(
            height=420, margin=dict(l=10, r=10, t=40, b=10),
            hovermode="x unified",
            yaxis=dict(title="騰落率 (%)", ticksuffix="%"),
            legend=dict(orientation="h", y=-0.2),
            title=dict(text=f"指数比較({period_label}・期初=0%)",
                       font=dict(size=15)))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("表示する指数を選択してください")

# --------------------------------------------------------------
# タブ3: 基準価額
# --------------------------------------------------------------
with tab_nav:
    nav_funds = [f for f in FUNDS if f["isin"] and f["fund_cd"]]
    if not nav_funds:
        st.info("基準価額コードが未設定です。「使い方」タブをご覧ください。")
    for f in nav_funds:
        try:
            df = fetch_nav(f["isin"], f["fund_cd"])
            span = st.select_slider(
                f"{f['name']} の表示期間",
                options=["3ヶ月", "1年", "3年", "全期間"],
                value="1年", key=f"span_{f['name']}")
            days = {"3ヶ月": 90, "1年": 365, "3年": 1095}.get(span)
            plot_df = df if days is None else df[
                df["date"] >= df["date"].max() - pd.Timedelta(days=days)]

            latest, prev = df["nav"].iloc[-1], df["nav"].iloc[-2]
            c1, c2 = st.columns([1, 2])
            c1.metric(f["name"], f"{latest:,.0f} 円",
                      f"{(latest / prev - 1) * 100:+.2f} % (前日比)")
            with c2:
                st.plotly_chart(
                    line_chart(plot_df, "date", "nav", f["name"],
                               GROUP_COLOR.get(f["group"], "#1a7f5a")),
                    use_container_width=True)
            st.divider()
        except Exception as e:
            st.warning(f"{f['name']}: 基準価額の取得に失敗しました。"
                       f"コード設定を確認してください({e})")

    remaining = [f["name"] for f in FUNDS if not (f["isin"] and f["fund_cd"])]
    if remaining:
        st.caption("コード未設定(基準価額 非表示): " + " / ".join(remaining))

# --------------------------------------------------------------
# タブ4: 使い方
# --------------------------------------------------------------
with tab_help:
    st.markdown("""
### このアプリについて
- **サマリー**: 各保有ファンドの連動指数の前営業日比を一覧表示します(現地通貨ベース)。
- **指数チャート**: 複数指数を期初=0%に揃えて比較できます。
- **基準価額**: 投信協会の公開データから日次の基準価額を表示します(1日1回更新)。

### 基準価額コードの追加方法
1. [投信総合検索ライブラリー](https://toushin-lib.fwg.ne.jp/FdsWeb/) でファンド名を検索
2. ファンド詳細ページのURLに含まれる `isinCd`(JP90C…)と `associFundCd`(8桁)をメモ
3. GitHub上で `app.py` の `FUNDS` に `isin` と `fund_cd` を記入してコミット

※ プリセット済みのコード(オルカン・S&P500)も念のため上記手順で一度ご確認ください。

### 更新頻度と注意
- 指数: 5分キャッシュ(米国指数は日本時間の夜〜早朝に動きます)
- 基準価額: 6時間キャッシュ(投信協会の更新は通常 営業日の夜)
- Mega10 は無料で取れる連動指数がないため NASDAQ100 を代替表示しています
""")
