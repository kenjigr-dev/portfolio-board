# -*- coding: utf-8 -*-
"""
マイ資産ボード - 保有ファンドごとに「連動指数」と「基準価額」をまとめて表示
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
# isin / fund_cd : 投信協会の基準価額CSV用コード(未設定は None)
# ==============================================================
FUNDS = [
    dict(name="オルカン(全世界株式)", group="コア(積立中)",
         index_ticker="ACWI", index_label="MSCI ACWI",
         isin="JP90C000H1T1", fund_cd="0331418A"),
    dict(name="ゴールド", group="コア(積立中)",
         index_ticker="GC=F", index_label="金先物(COMEX)",
         isin=None, fund_cd=None),
    dict(name="ニッセイSOX指数", group="サテライト",
         index_ticker="^SOX", index_label="SOX指数",
         isin=None, fund_cd=None),
    dict(name="iDeCo 先進国株式(除く日本)", group="iDeCo",
         index_ticker="TOK", index_label="MSCIコクサイ(ETF)",
         isin=None, fund_cd=None),
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
      display: inline-block; color: #fff; font-size: 0.72rem;
      font-weight: 600; padding: 2px 10px; border-radius: 999px;
  }
  .fund-head {display:flex; align-items:center; gap:8px; margin-bottom:2px;}
</style>
""", unsafe_allow_html=True)


# ==============================================================
# データ取得
# ==============================================================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_index_history(ticker: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    return df if df is not None else pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_daily_change(ticker: str):
    df = yf.Ticker(ticker).history(period="5d", interval="1d")
    if df is None or len(df) < 2:
        return None, None
    last, prev = df["Close"].iloc[-1], df["Close"].iloc[-2]
    return float(last), (last / prev - 1) * 100


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_nav(isin: str, fund_cd: str) -> pd.DataFrame:
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


def area_chart(x, y, color: str, height: int = 240,
               ysuffix: str = "", yfmt: str = ",.0f"):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines",
                             line=dict(width=2.2, color=color),
                             fill="tozeroy"))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=8, b=10),
                      showlegend=False, hovermode="x unified",
                      yaxis=dict(tickformat=yfmt, ticksuffix=ysuffix))
    return fig


# ==============================================================
# ヘッダー
# ==============================================================
st.title("📊 マイ資産ボード")
st.caption(f"最終更新: {dt.datetime.now():%Y-%m-%d %H:%M} / "
           "指数は5分・基準価額は6時間キャッシュ")

fx_last, fx_chg = fetch_daily_change("JPY=X")
if fx_last:
    c1, c2 = st.columns(2)
    c1.metric("💱 ドル円", f"{fx_last:,.2f} 円", f"{fx_chg:+.2f} %")
    c2.metric("円の動き",
              "円安(外貨資産に追い風)" if fx_chg and fx_chg > 0
              else "円高(外貨資産に向かい風)")

period_label = st.radio("指数チャートの期間", list(PERIODS.keys()),
                        horizontal=True, index=2)
period, interval = PERIODS[period_label]

st.divider()

# ==============================================================
# ファンドごとに「指数」と「基準価額」をまとめて表示
# ==============================================================
for group in GROUP_ORDER:
    funds = [f for f in FUNDS if f["group"] == group]
    if not funds:
        continue
    st.markdown(
        f'<span class="group-badge" style="background:{GROUP_COLOR[group]}">'
        f'{group}</span>', unsafe_allow_html=True)
    st.write("")

    for f in funds:
        color = GROUP_COLOR.get(group, "#1a7f5a")
        with st.expander(f["name"], expanded=(group == "コア(積立中)")):

            # --- 指数(リアルタイム) ---
            st.markdown(f"**連動指数: {f['index_label']}**")
            last, chg = fetch_daily_change(f["index_ticker"])
            if last is None:
                st.warning("指数データの取得に失敗しました")
            else:
                st.metric("直近値(前営業日比)", f"{last:,.2f}", f"{chg:+.2f} %")
                hist = fetch_index_history(f["index_ticker"], period, interval)
                if not hist.empty:
                    st.plotly_chart(
                        area_chart(hist.index, hist["Close"], color),
                        use_container_width=True,
                        key=f"idx_{f['name']}_{period}")
                else:
                    st.caption("チャート用データを取得できませんでした")

            # --- 基準価額(日次) ---
            if f["isin"] and f["fund_cd"]:
                st.markdown("**基準価額(日次・投信協会公表)**")
                try:
                    nav_df = fetch_nav(f["isin"], f["fund_cd"])
                    span = st.select_slider(
                        "表示期間", options=["3ヶ月", "1年", "3年", "全期間"],
                        value="1年", key=f"span_{f['name']}")
                    days = {"3ヶ月": 90, "1年": 365, "3年": 1095}.get(span)
                    plot_df = nav_df if days is None else nav_df[
                        nav_df["date"] >= nav_df["date"].max()
                        - pd.Timedelta(days=days)]
                    latest, prev = nav_df["nav"].iloc[-1], nav_df["nav"].iloc[-2]
                    st.metric("基準価額(前日比)", f"{latest:,.0f} 円",
                              f"{(latest / prev - 1) * 100:+.2f} %")
                    st.plotly_chart(
                        area_chart(plot_df["date"], plot_df["nav"], color),
                        use_container_width=True,
                        key=f"nav_{f['name']}_{span}")
                except Exception as e:
                    st.warning(f"基準価額の取得に失敗しました({e})")
            else:
                st.caption("基準価額コード未設定 — 下の「使い方」を参照してください")

# ==============================================================
# 使い方(末尾)
# ==============================================================
with st.expander("📖 使い方 / 基準価額コードの追加方法"):
    st.markdown("""
- **連動指数**: yfinanceで取得。日中の値動きが反映されます(現地通貨ベース)。
- **基準価額**: 投信協会の公開CSVから取得。更新は通常、営業日の夜1回のみです。

**基準価額コードの追加手順**
1. [投信総合検索ライブラリー](https://toushin-lib.fwg.ne.jp/FdsWeb/) でファンド名を検索
2. ファンド詳細ページのURLから `isinCd`(JP90C…)と `associFundCd`(8桁)を確認
3. GitHub上で `app.py` の該当ファンドに `isin` と `fund_cd` を記入してコミット

※ Mega10 は連動指数が無料で取得できないため NASDAQ100 を代替表示しています。
""")
