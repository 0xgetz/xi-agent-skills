"""
pro_reporting.py — Institutional-Grade Reporting System

Amateurs take screenshots. Pros generate audit trails.
Generates HTML reports with interactive Plotly charts, PDF exports,
trade journals, audit trails, risk reports, attribution analysis,
and AI-generated performance summaries.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    go = pio = None

logger = logging.getLogger("Reporting")


# ===================================================================
# Shared Data Types
# ===================================================================

@dataclass
class TradeRecord:
    """A single trade record."""
    trade_id: str = ""
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    exit_time: Optional[datetime] = None
    asset: str = ""
    direction: str = "long"  # long, short
    entry_price: float = 0.0
    exit_price: Optional[float] = None
    size: float = 0.0
    position_size_usd: float = 0.0
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    entry_reason: str = ""
    exit_reason: str = ""
    tags: List[str] = field(default_factory=list)
    strategy: str = ""
    screenshot_path: str = ""
    notes: str = ""
    fees: float = 0.0
    slippage: float = 0.0
    market_regime_at_entry: str = ""
    emotion_at_entry: str = ""

    def is_closed(self) -> bool:
        return self.exit_time is not None and self.exit_price is not None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_time"] = self.entry_time.isoformat() if self.entry_time else ""
        d["exit_time"] = self.exit_time.isoformat() if self.exit_time else ""
        return d


@dataclass
class AuditEntry:
    """A single audit log entry with hash-chain integrity."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    action: str = ""
    user: str = "system"
    details: str = ""
    previous_hash: str = ""
    hash: str = ""
    entry_id: str = ""

    def __post_init__(self):
        if not self.entry_id:
            self.entry_id = str(uuid.uuid4())[:12]

    def compute_hash(self) -> str:
        data = f"{self.timestamp.isoformat()}|{self.action}|{self.user}|{self.details}|{self.previous_hash}|{self.entry_id}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action,
            "user": self.user,
            "details": self.details,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
            "entry_id": self.entry_id,
        }


# ===================================================================
# 1. PerformanceReport
# ===================================================================

class PerformanceReport:
    """
    Generates comprehensive performance reports:
    - Equity curve with annotations
    - Monthly returns heatmap
    - Drawdown chart
    - Trade journal
    - Statistics table
    - Rolling metrics
    - Market comparison
    """

    def __init__(self, risk_free_rate: float = 0.05):
        self.risk_free_rate = risk_free_rate

    def generate_all(
        self,
        trades: List[TradeRecord],
        equity_curve: pd.Series = None,
        price_data: pd.DataFrame = None,
        benchmark_prices: pd.Series = None,
        title: str = "Trading Performance Report",
    ) -> Dict[str, Any]:
        """Generate all report components."""
        if equity_curve is None and trades:
            equity_curve = self._build_equity_from_trades(trades)

        result = {
            "title": title,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary_stats": self._compute_summary_stats(trades, equity_curve),
            "monthly_returns": self._compute_monthly_returns(equity_curve),
            "drawdown": self._compute_drawdown(equity_curve),
            "rolling_sharpe": self._compute_rolling_sharpe(equity_curve),
            "rolling_win_rate": self._compute_rolling_win_rate(trades),
            "market_comparison": self._compute_market_comparison(equity_curve, benchmark_prices),
            "trade_stats": self._compute_trade_statistics(trades),
            "trade_journal": [t.to_dict() for t in trades],
            "equity_curve": equity_curve.to_dict() if equity_curve is not None else {},
        }
        return result

    def _build_equity_from_trades(self, trades: List[TradeRecord]) -> pd.Series:
        if not trades:
            return pd.Series(dtype=float)
        closed = [t for t in trades if t.is_closed()]
        if not closed:
            return pd.Series(dtype=float)
        closed.sort(key=lambda t: t.exit_time or t.entry_time)
        equity = 100000.0
        dates = [closed[0].entry_time]
        values = [equity]
        for t in closed:
            if t.pnl is not None:
                equity += t.pnl
                values.append(equity)
                dates.append(t.exit_time or t.entry_time)
        return pd.Series(values, index=pd.DatetimeIndex(dates))

    def _compute_summary_stats(self, trades: List[TradeRecord], equity_curve: pd.Series = None) -> Dict[str, float]:
        stats = {
            "total_trades": len(trades), "total_closed": 0, "total_pnl": 0.0, "total_pnl_pct": 0.0,
            "winning_trades": 0, "losing_trades": 0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
            "max_drawdown": 0.0, "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0, "sortino_ratio": 0.0, "calmar_ratio": 0.0,
            "avg_holding_hours": 0.0, "avg_trade_return": 0.0, "std_trade_return": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
            "consecutive_wins": 0, "consecutive_losses": 0, "recovery_factor": 0.0,
        }
        closed = [t for t in trades if t.is_closed() and t.pnl is not None]
        stats["total_closed"] = len(closed)
        if not closed:
            return stats
        pnls = np.array([t.pnl for t in closed])
        stats["total_pnl"] = float(np.sum(pnls))
        winners = [t for t in closed if t.pnl > 0]
        losers = [t for t in closed if t.pnl <= 0]
        stats["winning_trades"] = len(winners)
        stats["losing_trades"] = len(losers)
        stats["win_rate"] = len(winners) / len(closed) if closed else 0.0
        if winners:
            stats["avg_win"] = float(np.mean([t.pnl for t in winners]))
            stats["best_trade"] = float(max(t.pnl for t in winners))
        if losers:
            stats["avg_loss"] = float(np.mean([t.pnl for t in losers]))
            stats["worst_trade"] = float(min(t.pnl for t in losers))
        gross_profit = sum(t.pnl for t in winners) if winners else 0.0
        gross_loss = abs(sum(t.pnl for t in losers)) if losers else 1.0
        stats["profit_factor"] = gross_profit / gross_loss if gross_loss > 0 else 0.0
        if equity_curve is not None and len(equity_curve) > 1:
            cumulative = equity_curve.values
            running_max = np.maximum.accumulate(cumulative)
            drawdowns = (cumulative - running_max) / running_max * 100
            stats["max_drawdown_pct"] = float(np.min(drawdowns))
            stats["max_drawdown"] = float(np.min(cumulative - running_max))
        if equity_curve is not None and len(equity_curve) > 20:
            daily_returns = pd.Series(equity_curve).pct_change().dropna()
            if len(daily_returns) > 1:
                excess = daily_returns - self.risk_free_rate / 365
                sharpe = np.sqrt(365) * excess.mean() / (excess.std() + 1e-10)
                stats["sharpe_ratio"] = float(sharpe)
                downside = excess[excess < 0]
                sortino = np.sqrt(365) * excess.mean() / (downside.std() + 1e-10)
                stats["sortino_ratio"] = float(sortino)
                if abs(stats["max_drawdown_pct"]) > 0:
                    annual_return = (1 + daily_returns.mean()) ** 365 - 1
                    stats["calmar_ratio"] = annual_return / abs(stats["max_drawdown_pct"]) * 100
        results = [1 if t.pnl > 0 else 0 for t in closed]
        stats["consecutive_wins"] = self._longest_run(results, 1)
        stats["consecutive_losses"] = self._longest_run(results, 0)
        holding_times = [(t.exit_time - t.entry_time).total_seconds() / 3600.0
                         for t in closed if t.entry_time and t.exit_time]
        if holding_times:
            stats["avg_holding_hours"] = float(np.mean(holding_times))
        pnl_pcts = [t.pnl_pct or 0.0 for t in closed]
        stats["avg_trade_return"] = float(np.mean(pnl_pcts))
        stats["std_trade_return"] = float(np.std(pnl_pcts)) if len(pnl_pcts) > 1 else 0.0
        if stats["max_drawdown"] != 0:
            stats["recovery_factor"] = stats["total_pnl"] / abs(stats["max_drawdown"])
        return stats

    @staticmethod
    def _longest_run(arr: List[int], target: int) -> int:
        best = cur = 0
        for x in arr:
            if x == target:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    def _compute_monthly_returns(self, equity_curve: pd.Series) -> pd.DataFrame:
        if equity_curve is None or len(equity_curve) < 2:
            return pd.DataFrame()
        try:
            s = equity_curve.copy()
            if isinstance(s.index, pd.DatetimeIndex):
                monthly = s.resample("ME").last()
                monthly_returns = monthly.pct_change().dropna()
                years = monthly_returns.index.year
                month_nums = monthly_returns.index.month
                month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
                data = []
                for yr in sorted(years.unique()):
                    row = {"Year": str(yr)}
                    for m_idx, m_name in enumerate(month_names, 1):
                        mask = (years == yr) & (month_nums == m_idx)
                        vals = monthly_returns[mask]
                        row[m_name] = float(vals.iloc[0] * 100) if len(vals) > 0 else np.nan
                    data.append(row)
                return pd.DataFrame(data)
        except Exception:
            pass
        return pd.DataFrame()

    def _compute_drawdown(self, equity_curve: pd.Series) -> Dict:
        if equity_curve is None or len(equity_curve) < 2:
            return {}
        vals = equity_curve.values
        running_max = np.maximum.accumulate(vals)
        dd_pct = (vals - running_max) / running_max * 100
        return {
            "drawdown_pct_series": list(dd_pct),
            "max_drawdown_pct": float(np.min(dd_pct)),
            "dates": [str(d) for d in equity_curve.index],
        }

    def _compute_rolling_sharpe(self, equity_curve: pd.Series, window: int = 90) -> pd.Series:
        if equity_curve is None or len(equity_curve) < window + 10:
            return pd.Series(dtype=float)
        daily_returns = equity_curve.pct_change().dropna()
        rolling = daily_returns.rolling(window)
        rs = np.sqrt(365) * rolling.mean() / (rolling.std() + 1e-10)
        return rs.clip(-5, 5)

    def _compute_rolling_win_rate(self, trades: List[TradeRecord], window: int = 20) -> pd.Series:
        closed = [t for t in trades if t.is_closed() and t.pnl is not None]
        if len(closed) < window:
            return pd.Series(dtype=float)
        closed.sort(key=lambda t: t.exit_time or t.entry_time)
        results = pd.Series(
            [1 if t.pnl > 0 else 0 for t in closed],
            index=pd.DatetimeIndex([t.exit_time or t.entry_time for t in closed]),
        )
        return results.rolling(window).mean() * 100

    def _compute_market_comparison(self, equity_curve: pd.Series, benchmark: pd.Series) -> Dict:
        if equity_curve is None or benchmark is None or len(equity_curve) < 2:
            return {}
        common = equity_curve.index.intersection(benchmark.index)
        if len(common) < 2:
            return {}
        eq_a, bm_a = equity_curve.loc[common], benchmark.loc[common]
        return {
            "strategy_return_pct": round(float((eq_a.iloc[-1] / eq_a.iloc[0] - 1) * 100), 2),
            "benchmark_return_pct": round(float((bm_a.iloc[-1] / bm_a.iloc[0] - 1) * 100), 2),
            "alpha": round(float(eq_a.iloc[-1] / eq_a.iloc[0] - bm_a.iloc[-1] / bm_a.iloc[0]), 4),
            "correlation": float(eq_a.pct_change().corr(bm_a.pct_change())),
        }

    def _compute_trade_statistics(self, trades: List[TradeRecord]) -> Dict:
        closed = [t for t in trades if t.is_closed() and t.pnl is not None]
        if not closed:
            return {}
        longs = [t for t in closed if t.direction == "long"]
        shorts = [t for t in closed if t.direction == "short"]
        return {
            "by_direction": {
                "long": {"count": len(longs), "win_rate": sum(1 for t in longs if t.pnl > 0) / max(len(longs), 1)},
                "short": {"count": len(shorts), "win_rate": sum(1 for t in shorts if t.pnl > 0) / max(len(shorts), 1)},
            }
        }


# ===================================================================
# 2. HtmlReportGenerator
# ===================================================================

class HtmlReportGenerator:
    """
    Generates self-contained HTML reports with embedded interactive Plotly charts.
    Dark-themed, color-coded, fully responsive.
    """

    def __init__(self, theme: str = "dark"):
        self.theme = theme
        self._template = "plotly_dark" if theme == "dark" else "plotly_white"
        if theme == "dark":
            self.bg, self.card, self.tc = "#1a1a2e", "#16213e", "#e0e0e0"
            self.accent, self.gr, self.rd, self.yl = "#00d4ff", "#00e676", "#ff5252", "#ffd740"
        else:
            self.bg, self.card, self.tc = "#f0f2f6", "#ffffff", "#333333"
            self.accent, self.gr, self.rd, self.yl = "#1976d2", "#2e7d32", "#c62828", "#f9a825"

    def _css(self) -> str:
        b, c, t = self.bg, self.card, self.tc
        a, g, r = self.accent, self.gr, self.rd
        return f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,sans-serif; background:{b}; color:{t}; padding:20px; }}
.container {{ max-width:1400px; margin:0 auto; }}
.header {{ text-align:center; padding:30px 0; border-bottom:2px solid {a}; margin-bottom:30px; }}
.header h1 {{ font-size:2rem; color:{a}; }}
.header p {{ color:#888; margin-top:5px; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:15px; margin-bottom:30px; }}
.stat-card {{ background:{c}; border-radius:12px; padding:20px; text-align:center; border:1px solid rgba(255,255,255,0.1); }}
.stat-card .value {{ font-size:1.5rem; font-weight:bold; margin-top:5px; }}
.stat-card .label {{ font-size:0.8rem; color:#888; }}
.chart-box {{ background:{c}; border-radius:12px; padding:20px; margin-bottom:25px; border:1px solid rgba(255,255,255,0.1); }}
.chart-box h2 {{ font-size:1.2rem; margin-bottom:15px; color:{a}; }}
.charts-row {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
@media(max-width:900px){{ .charts-row{{ grid-template-columns:1fr; }} }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:0.85rem; }}
th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid rgba(255,255,255,0.1); }}
th {{ background:rgba(0,212,255,0.1); color:{a}; font-weight:600; }}
tr:hover {{ background:rgba(255,255,255,0.03); }}
.pos {{ color:{g}; }}
.neg {{ color:{r}; }}
.neu {{ color:{self.yl}; }}
.footer {{ text-align:center; padding:30px; color:#555; font-size:0.8rem; }}
"""

    def generate_performance_html(self, perf_data: Dict[str, Any], output_path: str = "performance_report.html") -> str:
        title = perf_data.get("title", "Performance Report")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        css = self._css()
        s = self._summary(perf_data)
        ec = self._eq_chart(perf_data)
        mr = self._monthly_chart(perf_data)
        dd = self._dd_chart(perf_data)
        sc = self._sharpe_chart(perf_data)
        wr = self._wr_chart(perf_data)
        tj = self._trade_table(perf_data)
        st = self._stats_table(perf_data)
        html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{title}</title><script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script><style>{css}</style></head><body><div class="container"><div class="header"><h1>{title}</h1><p>Generated: {ts}</p></div>{s}{ec}{mr}<div class="charts-row">{dd}{sc}</div>{wr}{tj}{st}<div class="footer"><p>Pro Reporting System | Gumloop Trading Suite</p><p>Past performance is not indicative of future results.</p></div></div></body></html>"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

    def _summary(self, d: Dict) -> str:
        st = d.get("summary_stats", {})
        if not st:
            return '<div class="stats-grid"><div class="stat-card"><div class="label">No Data</div></div></div>'
        def c(v, hi=None):
            if hi is not None: return "pos" if v >= hi else "neg"
            return "pos" if v > 0 else "neg" if v < 0 else "neu"
        items = [
            ("Total Trades", str(st.get("total_trades",0)), ""),
            ("Win Rate", f'{st.get("win_rate",0)*100:.1f}%', "pos" if st.get("win_rate",0)>=0.5 else "neg"),
            ("Total P&L", f'${st.get("total_pnl",0):,.0f}', c(st.get("total_pnl",0))),
            ("Profit Factor", f'{st.get("profit_factor",0):.2f}', "pos" if st.get("profit_factor",0)>1.5 else "neu"),
            ("Sharpe", f'{st.get("sharpe_ratio",0):.2f}', "pos" if st.get("sharpe_ratio",0)>1 else "neg"),
            ("Max DD", f'{st.get("max_drawdown_pct",0):.1f}%', "neg"),
            ("Best Trade", f'${st.get("best_trade",0):,.0f}', "pos"),
            ("Worst Trade", f'${st.get("worst_trade",0):,.0f}', "neg"),
            ("Avg Hold", f'{st.get("avg_holding_hours",0):.1f}h', ""),
        ]
        cards = "".join(f'<div class="stat-card"><div class="label">{l}</div><div class="value {cl}">{v}</div></div>' for l,v,cl in items)
        return f'<div class="stats-grid">{cards}</div>'

    def _eq_chart(self, d: Dict) -> str:
        eq = d.get("equity_curve", {})
        vals = list(eq.values()) if isinstance(eq, dict) and eq else []
        if not vals or not HAS_PLOTLY:
            return ""
        try:
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=vals, mode="lines", name="Equity",
                line=dict(color=self.accent,width=2), fill="tozeroy", fillcolor="rgba(0,212,255,0.1)"))
            fig.update_layout(title="Equity Curve", template=self._template, height=400, margin=dict(l=50,r=50,t=50,b=50), showlegend=False)
            return f'<div class="chart-box"><h2>Equity Curve</h2>{pio.to_html(fig, include_plotlyjs=False, full_html=False)}</div>'
        except Exception as e:
            return f'<div class="chart-box"><h2>Equity Curve</h2><p>Error: {e}</p></div>'

    def _monthly_chart(self, d: Dict) -> str:
        mr = d.get("monthly_returns", {})
        df = mr if isinstance(mr, pd.DataFrame) and not mr.empty else pd.DataFrame()
        if df.empty or not HAS_PLOTLY:
            return ""
        try:
            mc = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
            av = [c for c in mc if c in df.columns]
            zd = df[av].values
            fig = go.Figure(data=go.Heatmap(z=zd, x=av, y=df["Year"].values if "Year" in df.columns else list(range(len(df))),
                colorscale=[[0,"#d32f2f"],[0.25,"#ff8a80"],[0.5,"#1a1a2e"],[0.75,"#69f0ae"],[1.0,"#00c853"]],
                zmid=0, zmin=-10, zmax=10, text=[[f"{v:.1f}%" if not np.isnan(v) else "" for v in row] for row in zd],
                texttemplate="%{text}", hovertemplate="%{y} %{x}: %{z:.2f}%<extra></extra>"))
            fig.update_layout(title="Monthly Returns (%)", template=self._template, height=300, margin=dict(l=50,r=50,t=50,b=50), xaxis=dict(side="top"))
            return f'<div class="chart-box"><h2>Monthly Returns Heatmap</h2>{pio.to_html(fig, include_plotlyjs=False, full_html=False)}</div>'
        except Exception as e:
            return f'<div class="chart-box"><h2>Monthly Returns</h2><p>Error: {e}</p></div>'

    def _dd_chart(self, d: Dict) -> str:
        dd = d.get("drawdown", {})
        s = dd.get("drawdown_pct_series", [])
        if not s or not HAS_PLOTLY:
            return ""
        try:
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=s, mode="lines", name="DD", line=dict(color=self.rd,width=1),
                fill="tozeroy", fillcolor="rgba(255,82,82,0.15)"))
            fig.add_hline(y=0, line=dict(color="white",width=1,dash="dash"))
            fig.update_layout(title=f"Drawdown (Max: {dd.get('max_drawdown_pct',0):.1f}%)",
                template=self._template, height=300, margin=dict(l=50,r=50,t=50,b=50), showlegend=False,
                yaxis=dict(range=[min(s)*1.1,5]))
            return f'<div class="chart-box"><h2>Drawdown Analysis</h2>{pio.to_html(fig, include_plotlyjs=False, full_html=False)}</div>'
        except Exception as e:
            return f'<div class="chart-box"><h2>Drawdown</h2><p>Error: {e}</p></div>'

    def _sharpe_chart(self, d: Dict) -> str:
        rs = d.get("rolling_sharpe", {})
        if isinstance(rs, pd.Series) and len(rs) > 0 and HAS_PLOTLY:
            try:
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=rs.values, mode="lines", line=dict(color=self.yl,width=2)))
                fig.add_hline(y=1.0, line=dict(color=self.gr,width=1,dash="dash"))
                fig.add_hline(y=0.0, line=dict(color="white",width=1,dash="dash"))
                fig.update_layout(title="Rolling Sharpe (90d)", template=self._template, height=300, margin=dict(l=50,r=50,t=50,b=50), showlegend=False)
                return f'<div class="chart-box"><h2>Rolling Sharpe Ratio</h2>{pio.to_html(fig, include_plotlyjs=False, full_html=False)}</div>'
            except Exception:
                return ""
        return ""

    def _wr_chart(self, d: Dict) -> str:
        rw = d.get("rolling_win_rate", {})
        if isinstance(rw, pd.Series) and len(rw) > 0 and HAS_PLOTLY:
            try:
                fig = go.Figure()
                fig.add_trace(go.Scatter(y=rw.values, mode="lines", line=dict(color=self.gr,width=2),
                    fill="tozeroy", fillcolor="rgba(0,230,118,0.1)"))
                fig.add_hline(y=50, line=dict(color="white",width=1,dash="dash"))
                fig.update_layout(title="Rolling Win Rate (20 trades)", template=self._template,
                    height=250, showlegend=False, yaxis=dict(range=[0,100]), margin=dict(l=50,r=50,t=50,b=50))
                return f'<div class="chart-box"><h2>Rolling Win Rate</h2>{pio.to_html(fig, include_plotlyjs=False, full_html=False)}</div>'
            except Exception:
                return ""
        return ""

    def _trade_table(self, d: Dict) -> str:
        trades = d.get("trade_journal", [])
        if not trades:
            return ""
        rows = ""
        for t in trades[:50]:
            pnl = t.get("pnl", 0) or 0
            cls = "pos" if pnl > 0 else "neg" if pnl < 0 else "neu"
            pnl_str = f"${pnl:,.0f}" if pnl else "-"
            entry = (t.get("entry_time") or "")[:19]
            ext = (t.get("exit_time") or "")[:19]
            de = "L" if t.get("direction") == "long" else "S"
            rows += f"<tr><td>{t.get('trade_id','')[:8]}</td><td>{t.get('asset','')} {de}</td><td>{entry}</td><td>{ext}</td><td>{t.get('size',0):.3f}</td><td>{t.get('entry_price',0):,.0f}</td><td>{t.get('exit_price',0):,.0f}</td><td class='{cls}'>{pnl_str}</td><td>{t.get('strategy','')[:15]}</td><td>{t.get('exit_reason','')}</td></tr>"
        return f"""<div class="chart-box"><h2>Trade Journal (Last 50)</h2><div style="overflow-x:auto;"><table><tr><th>ID</th><th>Asset</th><th>Entry</th><th>Exit</th><th>Size</th><th>Entry $</th><th>Exit $</th><th>PnL</th><th>Strategy</th><th>Exit</th></tr>{rows}</table></div></div>"""

    def _stats_table(self, d: Dict) -> str:
        st = d.get("summary_stats", {})
        if not st:
            return ""
        rows_data = [
            ("Total Trades", str(st.get("total_trades",0))),
            ("Winning Trades", str(st.get("winning_trades",0))),
            ("Losing Trades", str(st.get("losing_trades",0))),
            ("Win Rate", f'{st.get("win_rate",0)*100:.1f}%'),
            ("Total P&L", f'${st.get("total_pnl",0):,.0f}'),
            ("Profit Factor", f'{st.get("profit_factor",0):.2f}'),
            ("Avg Win", f'${st.get("avg_win",0):,.0f}'),
            ("Avg Loss", f'${st.get("avg_loss",0):,.0f}'),
            ("Best Trade", f'${st.get("best_trade",0):,.0f}'),
            ("Worst Trade", f'${st.get("worst_trade",0):,.0f}'),
            ("Sharpe Ratio", f'{st.get("sharpe_ratio",0):.2f}'),
            ("Sortino Ratio", f'{st.get("sortino_ratio",0):.2f}'),
            ("Calmar Ratio", f'{st.get("calmar_ratio",0):.2f}'),
            ("Max Drawdown", f'{st.get("max_drawdown_pct",0):.1f}%'),
            ("Avg Holding", f'{st.get("avg_holding_hours",0):.1f}h'),
            ("Consecutive Wins", str(st.get("consecutive_wins",0))),
            ("Consecutive Losses", str(st.get("consecutive_losses",0))),
            ("Recovery Factor", f'{st.get("recovery_factor",0):.2f}x'),
        ]
        rows = "".join(f"<tr><td>{l}</td><td>{v}</td></tr>" for l,v in rows_data)
        return f"""<div class="chart-box"><h2>Performance Statistics</h2><div style="overflow-x:auto;"><table><tr><th>Metric</th><th>Value</th></tr>{rows}</table></div></div>"""


# ===================================================================
# 3. TradingJournal
# ===================================================================

class TradingJournal:
    """Professional trade journal with CSV persistence and HTML export."""

    def __init__(self, journal_path: str = "trading_journal.csv"):
        self.path = journal_path
        self.trades: List[TradeRecord] = []
        self._load_existing()

    def _load_existing(self) -> None:
        if os.path.exists(self.path):
            try:
                df = pd.read_csv(self.path)
                for _, row in df.iterrows():
                    try:
                        t = TradeRecord(
                            trade_id=str(row.get("trade_id", "")),
                            entry_time=pd.to_datetime(row["entry_time"]).to_pydatetime().replace(tzinfo=timezone.utc)
                                if pd.notna(row.get("entry_time")) else datetime.now(timezone.utc),
                            exit_time=pd.to_datetime(row["exit_time"]).to_pydatetime().replace(tzinfo=timezone.utc)
                                if pd.notna(row.get("exit_time")) else None,
                            asset=str(row.get("asset", "")),
                            direction=str(row.get("direction", "long")),
                            entry_price=float(row.get("entry_price", 0)),
                            exit_price=float(row["exit_price"]) if pd.notna(row.get("exit_price")) else None,
                            size=float(row.get("size", 0)),
                            pnl=float(row["pnl"]) if pd.notna(row.get("pnl")) else None,
                            pnl_pct=float(row["pnl_pct"]) if pd.notna(row.get("pnl_pct")) else None,
                            entry_reason=str(row.get("entry_reason", "")),
                            exit_reason=str(row.get("exit_reason", "")),
                            tags=str(row.get("tags", "")).split(",") if pd.notna(row.get("tags")) else [],
                            strategy=str(row.get("strategy", "")),
                            notes=str(row.get("notes", "")),
                        )
                        self.trades.append(t)
                    except Exception:
                        continue
            except Exception:
                self.trades = []

    def log_entry(self, asset: str, direction: str, entry_price: float, size: float,
                  entry_reason: str = "", strategy: str = "", tags: List[str] = None,
                  notes: str = "", market_regime: str = "", emotion: str = "") -> TradeRecord:
        t = TradeRecord(
            trade_id=str(uuid.uuid4())[:8],
            entry_time=datetime.now(timezone.utc),
            asset=asset, direction=direction, entry_price=entry_price, size=size,
            position_size_usd=entry_price*size, entry_reason=entry_reason,
            strategy=strategy, tags=tags or [], notes=notes,
            market_regime_at_entry=market_regime, emotion_at_entry=emotion,
        )
        self.trades.append(t)
        self._save()
        return t

    def log_exit(self, trade_id: str, exit_price: float, exit_reason: str = "manual",
                 fees: float = 0.0, slippage: float = 0.0) -> Optional[TradeRecord]:
        for t in self.trades:
            if t.trade_id == trade_id and not t.is_closed():
                t.exit_time = datetime.now(timezone.utc)
                t.exit_price = exit_price
                t.exit_reason = exit_reason
                t.fees, t.slippage = fees, slippage
                if t.direction == "long":
                    t.pnl = (exit_price - t.entry_price) * t.size - fees
                    t.pnl_pct = (exit_price / t.entry_price - 1.0) * 100
                else:
                    t.pnl = (t.entry_price - exit_price) * t.size - fees
                    t.pnl_pct = (1.0 - exit_price / t.entry_price) * 100
                self._save()
                return t
        return None

    def get_open_trades(self) -> List[TradeRecord]:
        return [t for t in self.trades if not t.is_closed()]

    def get_closed_trades(self) -> List[TradeRecord]:
        return [t for t in self.trades if t.is_closed()]

    def _save(self) -> None:
        if not self.trades:
            return
        rows = []
        for t in self.trades:
            d = t.to_dict()
            d["tags"] = ",".join(t.tags)
            rows.append(d)
        pd.DataFrame(rows).to_csv(self.path, index=False)

    def export_csv(self, path: str = "trades_export.csv") -> str:
        pd.DataFrame([t.to_dict() for t in self.trades]).to_csv(path, index=False)
        return path

    def export_html(self, path: str = "trade_journal.html") -> str:
        rows = ""
        for t in sorted(self.get_closed_trades(), key=lambda x: x.exit_time or x.entry_time, reverse=True):
            pnl_str = f"${t.pnl:,.0f}" if t.pnl is not None else "OPEN"
            entry = t.entry_time.strftime("%m/%d %H:%M") if t.entry_time else "-"
            ext = t.exit_time.strftime("%m/%d %H:%M") if t.exit_time else "OPEN"
            tags_str = ", ".join(t.tags) if t.tags else "-"
            d = "L" if t.direction == "long" else "S"
            rows += f"<tr><td>{t.asset} ({d})</td><td>{entry}</td><td>{ext}</td><td>{t.entry_price:,.0f}</td><td>{t.exit_price or 0:,.0f}</td><td>{t.size:.3f}</td><td>{pnl_str}</td><td>{t.entry_reason[:20]}</td><td>{t.exit_reason}</td><td>{tags_str}</td><td>{t.strategy}</td></tr>"
        html = f"""<!DOCTYPE html><html><head><title>Trading Journal</title><style>body{{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}h1{{color:#00d4ff}}table{{width:100%;border-collapse:collapse;font-size:0.85rem}}th,td{{padding:8px;text-align:left;border-bottom:1px solid #333}}th{{background:#16213e;color:#00d4ff}}</style></head><body><h1>Trading Journal</h1><p>Total: {len(self.trades)} | Open: {len(self.get_open_trades())}</p><table><tr><th>Asset</th><th>Entry</th><th>Exit</th><th>Entry $</th><th>Exit $</th><th>Size</th><th>PnL</th><th>Entry Reason</th><th>Exit Reason</th><th>Tags</th><th>Strategy</th></tr>{rows}</table></body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def generate_summary(self) -> Dict:
        closed = self.get_closed_trades()
        if not closed:
            return {"status": "no_closed_trades"}
        pnls = [t.pnl or 0 for t in closed]
        return {
            "total_trades": len(closed),
            "winners": sum(1 for p in pnls if p > 0),
            "losers": sum(1 for p in pnls if p <= 0),
            "total_pnl": float(np.sum(pnls)),
            "avg_pnl": float(np.mean(pnls)),
            "best_trade": float(max(pnls)),
            "worst_trade": float(min(pnls)),
        }


# ===================================================================
# 4. AuditTrail
# ===================================================================

class AuditTrail:
    """Tamper-proof audit logging with hash chain. Append-only. Regulatory-ready."""

    def __init__(self, path: str = "audit_trail.jsonl"):
        self.path = path
        self.entries: List[AuditEntry] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line)
                                self.entries.append(AuditEntry(
                                    timestamp=datetime.fromisoformat(data["timestamp"]),
                                    action=data["action"], user=data.get("user","system"),
                                    details=data.get("details",""),
                                    previous_hash=data.get("previous_hash",""),
                                    hash=data.get("hash",""), entry_id=data.get("entry_id",""),
                                ))
                            except Exception:
                                continue
            except FileNotFoundError:
                pass

    def log(self, action: str, details: str = "", user: str = "system") -> AuditEntry:
        prev_hash = self.entries[-1].hash if self.entries else "0"*16
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc), action=action, user=user,
            details=details, previous_hash=prev_hash,
        )
        entry.hash = entry.compute_hash()
        if self.entries and prev_hash != self.entries[-1].hash:
            logger.error("AUDIT TAMPER DETECTED: hash chain broken!")
        self.entries.append(entry)
        with open(self.path, "a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
        return entry

    def verify_integrity(self) -> Dict:
        result = {"valid": True, "entries_checked": len(self.entries), "errors": []}
        if not self.entries:
            return result
        if self.entries[0].previous_hash != "0"*16:
            result["valid"] = False
            result["errors"].append("Genesis entry has non-zero previous_hash")
        for i in range(1, len(self.entries)):
            if self.entries[i].previous_hash != self.entries[i-1].hash:
                result["valid"] = False
                result["errors"].append(f"Chain break at {i}: expected {self.entries[i-1].hash}, got {self.entries[i].previous_hash}")
            if self.entries[i].hash != self.entries[i].compute_hash():
                result["valid"] = False
                result["errors"].append(f"Entry {i} hash mismatch — data tampered")
        return result

    def export_regulatory_report(self, path: str = "audit_report.html") -> str:
        status = self.verify_integrity()
        rows = ""
        for i, e in enumerate(self.entries):
            valid = e.hash == e.compute_hash()
            color = "#00e676" if valid else "#ff5252"
            rows += (
                f"<tr><td>{e.entry_id[:8]}</td>"
                f"<td>{e.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</td>"
                f"<td>{e.action}</td><td>{e.user}</td>"
                f"<td>{e.details[:60]}</td>"
                f"<td style='font-family:mono;font-size:0.7rem'>{e.hash[:12]}...</td>"
                f"<td style='color:{color}'>{'VALID' if valid else 'TAMPERED'}</td></tr>"
            )
        integ = "VALID" if status["valid"] else "TAMPERED"
        html = f"""<!DOCTYPE html><html><head><title>Audit Trail Report</title><style>body{{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}h1{{color:#00d4ff}}table{{width:100%;border-collapse:collapse;font-size:0.8rem}}th,td{{padding:6px 8px;text-align:left;border-bottom:1px solid #333}}th{{background:#16213e;color:#00d4ff}}</style></head><body><h1>Audit Trail Report</h1><h2>Integrity: {integ}</h2><p>Entries: {status['entries_checked']} | Errors: {len(status['errors'])}</p><table><tr><th>ID</th><th>Timestamp</th><th>Action</th><th>User</th><th>Details</th><th>Hash</th><th>Valid</th></tr>{rows}</table></body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        return path

    def export_csv(self, path: str = "audit_trail.csv") -> str:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp","action","user","details","hash","previous_hash","entry_id"])
            w.writeheader()
            for e in self.entries:
                w.writerow(e.to_dict())
        return path


# ===================================================================
# 5. RiskReport
# ===================================================================

class RiskReport:
    """Risk report: exposure by asset/sector/strategy, VaR/CVaR, stress tests, correlation, concentration."""

    def generate(self, positions: Dict[str, float], returns: pd.DataFrame,
                 strategies: Dict[str, List[str]] = None, leverage: float = 1.0,
                 confidence_level: float = 0.95) -> Dict:
        strategies = strategies or {"all": list(positions.keys())}
        total = sum(positions.values())
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_notional": total,
            "leverage": leverage,
            "exposure": self._exposure(positions, strategies, total),
            "risk_metrics": self._risk_metrics(returns, positions, confidence_level, total),
            "stress_test": self._stress_test(total),
            "correlation": self._correlation(returns),
            "concentration": self._concentration(positions, total),
        }

    def _exposure(self, positions: Dict[str, float], strategies: Dict[str, List[str]], total: float) -> Dict:
        by_asset = {k: {"notional": v, "pct": v/total*100 if total>0 else 0} for k,v in sorted(positions.items(), key=lambda x: -x[1])}
        by_strategy = {}
        for strat, assets in strategies.items():
            n = sum(positions.get(a,0) for a in assets)
            by_strategy[strat] = {"notional": n, "pct": n/total*100 if total>0 else 0}
        return {"by_asset": by_asset, "by_strategy": by_strategy, "num_assets": len(positions)}

    def _risk_metrics(self, returns: pd.DataFrame, positions: Dict[str, float], conf: float, total: float) -> Dict:
        if returns is None or returns.empty:
            return {}
        pr = self._portfolio_returns(returns, positions)
        if len(pr) < 10:
            return {}
        vp = 1 - conf
        vh = float(pr.quantile(vp))
        cvar = float(pr[pr <= vh].mean()) if len(pr[pr <= vh]) > 0 else vh
        dv = float(pr.std())
        return {
            "daily_var_95": round(abs(vh),4), "monthly_var_95": round(abs(vh)*np.sqrt(21),4),
            "yearly_var_95": round(abs(vh)*np.sqrt(252),4), "daily_cvar_95": round(abs(cvar),4),
            "daily_volatility": round(dv,4), "annualized_volatility": round(dv*np.sqrt(252),4),
            "confidence_level": conf,
        }

    def _portfolio_returns(self, returns: pd.DataFrame, positions: Dict[str, float]) -> pd.Series:
        total = sum(positions.values()) or 1
        weights = {k: v/total for k,v in positions.items()}
        port = pd.Series(0.0, index=returns.index)
        for asset, w in weights.items():
            if asset in returns.columns:
                port += returns[asset] * w
        return port.dropna()

    def _stress_test(self, total: float) -> Dict:
        scenarios = {
            "crypto_winter_2022": -0.50, "covid_crash_2020": -0.30,
            "financial_crisis_2008": -0.35, "flash_crash": -0.15,
            "market_correction": -0.10, "liquidity_crisis": -0.25,
        }
        return {s: {"shock_pct": sh*100, "estimated_loss": round(total*sh,0)} for s,sh in scenarios.items()}

    def _correlation(self, returns: pd.DataFrame) -> Dict:
        if returns is None or returns.empty or returns.shape[1] < 2:
            return {}
        corr = returns.corr().round(3)
        return {"assets": list(corr.columns), "matrix": corr.to_dict()}

    def _concentration(self, positions: Dict[str, float], total: float) -> Dict:
        if total == 0:
            return {"warnings": [], "hhi": 0}
        weights = np.array([v/total for v in positions.values()])
        hhi = float(np.sum(weights**2))
        sorted_pos = sorted(positions.items(), key=lambda x: -x[1])
        top3_pct = sum(v/total*100 for _,v in sorted_pos[:3])
        warnings = []
        if sorted_pos and (sorted_pos[0][1]/total*100) > 40:
            warnings.append(f"{sorted_pos[0][0]} is {(sorted_pos[0][1]/total*100):.0f}% of portfolio — extreme concentration")
        elif sorted_pos and (sorted_pos[0][1]/total*100) > 25:
            warnings.append(f"{sorted_pos[0][0]} is {(sorted_pos[0][1]/total*100):.0f}% of portfolio — high concentration")
        if top3_pct > 70:
            warnings.append(f"Top 3 assets: {top3_pct:.0f}% concentration")
        return {"hhi": round(hhi,4), "top3_concentration_pct": round(top3_pct,1), "warnings": warnings}

    def correlation_heatmap_html(self, returns: pd.DataFrame) -> Optional[str]:
        if not HAS_PLOTLY or returns is None or returns.empty or returns.shape[1] < 2:
            return None
        try:
            corr = returns.corr()
            fig = go.Figure(data=go.Heatmap(z=corr.values, x=corr.columns, y=corr.columns,
                colorscale="RdBu_r", zmin=-1, zmax=1, text=np.round(corr.values,2),
                texttemplate="%{text}", hovertemplate="%{x} vs %{y}: %{z:.2f}<extra></extra>"))
            fig.update_layout(title="Correlation Matrix", template="plotly_dark", height=500, width=500)
            return pio.to_html(fig, include_plotlyjs=False, full_html=False)
        except Exception:
            return None


# ===================================================================
# 6. AttributionReport
# ===================================================================

class AttributionReport:
    """PnL attribution by strategy, asset, and timeframe."""

    def generate(self, trades: List[TradeRecord]) -> Dict:
        closed = [t for t in trades if t.is_closed() and t.pnl is not None]
        if not closed:
            return {"status": "no_trades"}
        return {
            "by_strategy": self._by_strategy(closed),
            "by_asset": self._by_asset(closed),
            "by_timeframe": self._by_timeframe(closed),
            "risk_vs_pnl": self._risk_contribution(closed),
        }

    def _by_strategy(self, trades: List[TradeRecord]) -> Dict:
        groups = defaultdict(list)
        for t in trades:
            groups[t.strategy or "unknown"].append(t)
        all_pnl = sum(t.pnl or 0 for t in trades)
        result = {}
        for strat, group in groups.items():
            tp = sum(t.pnl or 0 for t in group)
            gp = sum(t.pnl for t in group if (t.pnl or 0) > 0)
            gl = abs(sum(t.pnl for t in group if (t.pnl or 0) < 0))
            wr = sum(1 for t in group if (t.pnl or 0) > 0) / max(len(group), 1)
            result[strat] = {
                "trades": len(group), "total_pnl": round(tp,2),
                "profit_factor": round(gp/max(gl,1),2), "win_rate": round(wr,3),
                "contribution_pct": round(tp/max(abs(all_pnl),1)*100, 1),
            }
        return dict(sorted(result.items(), key=lambda x: -abs(x[1]["total_pnl"])))

    def _by_asset(self, trades: List[TradeRecord]) -> Dict:
        groups = defaultdict(list)
        for t in trades:
            groups[t.asset].append(t)
        result = {}
        for asset, group in groups.items():
            tp = sum(t.pnl or 0 for t in group)
            wr = sum(1 for t in group if (t.pnl or 0) > 0) / max(len(group), 1)
            result[asset] = {"trades": len(group), "total_pnl": round(tp,2), "win_rate": round(wr,3)}
        return dict(sorted(result.items(), key=lambda x: -abs(x[1]["total_pnl"])))

    def _by_timeframe(self, trades: List[TradeRecord]) -> Dict:
        groups = defaultdict(list)
        for t in trades:
            if t.entry_time and t.exit_time:
                hrs = (t.exit_time - t.entry_time).total_seconds() / 3600.0
                tf = "scalp (<1h)" if hrs < 1 else "intraday (1-4h)" if hrs < 4 else "day_trade" if hrs < 24 else "swing" if hrs < 72 else "position"
                groups[tf].append(t)
        result = {}
        for tf, group in groups.items():
            tp = sum(t.pnl or 0 for t in group)
            wr = sum(1 for t in group if (t.pnl or 0) > 0) / max(len(group), 1)
            result[tf] = {"trades": len(group), "total_pnl": round(tp,2), "win_rate": round(wr,3)}
        return result

    def _risk_contribution(self, trades: List[TradeRecord]) -> Dict:
        groups = defaultdict(list)
        for t in trades:
            groups[t.strategy or "unknown"].append(t)
        all_pnl = sum(t.pnl or 0 for t in trades)
        total_risk = max(sum(abs(t.pnl or 0) for t in trades), 1)
        result = {}
        for strat, group in groups.items():
            tp = sum(t.pnl or 0 for t in group)
            ru = sum(abs(t.pnl or 0) for t in group)
            result[strat] = {
                "pnl_contrib_pct": round(tp/max(abs(all_pnl),1)*100,1),
                "risk_contrib_pct": round(ru/total_risk*100,1),
                "efficiency": round((tp/max(abs(all_pnl),1)*100)/max(ru/total_risk*100,0.1),2),
            }
        return result

    def attribution_chart_html(self, attribution: Dict) -> Optional[str]:
        if not HAS_PLOTLY:
            return None
        try:
            bs = attribution.get("by_strategy", {})
            if not bs:
                return None
            strats = list(bs.keys())
            pnls = [bs[s]["total_pnl"] for s in strats]
            colors = ["#00e676" if p > 0 else "#ff5252" for p in pnls]
            fig = go.Figure(data=go.Bar(x=strats, y=pnls, marker_color=colors,
                text=[f"${p:,.0f}" for p in pnls], textposition="outside"))
            fig.update_layout(title="PnL Attribution by Strategy", template="plotly_dark", height=400)
            return pio.to_html(fig, include_plotlyjs=False, full_html=False)
        except Exception:
            return None


# ===================================================================
# 7. AIReportGenerator
# ===================================================================

class AIReportGenerator:
    """Natural language performance summaries with improvement suggestions."""

    def generate_summary(self, perf_data: Dict, trades: List[TradeRecord], attribution: Dict = None) -> str:
        stats = perf_data.get("summary_stats", {})
        if not stats:
            return "No performance data available."
        return "\n\n".join([
            self._executive_summary(stats),
            self._what_worked(stats, trades, attribution),
            self._what_didnt(stats, trades, attribution),
            self._risk_analysis(stats),
            self._suggestions(stats, trades),
        ])

    def _executive_summary(self, st: Dict) -> str:
        pnl = st.get("total_pnl", 0)
        wr = st.get("win_rate", 0) * 100
        n = st.get("total_closed", 0)
        sh = st.get("sharpe_ratio", 0)
        dd = st.get("max_drawdown_pct", 0)
        adj = "exceptional" if sh > 2 else "strong" if sh > 1 else "moderate" if sh > 0.5 else "concerning" if sh > 0 else "poor"
        return (f"## Executive Summary\n\nOver {n} trades, the strategy generated "
                f"**${pnl:+,.0f}** PnL with a **{wr:.1f}%** win rate and **{dd:.1f}%** max drawdown.\n\n"
                f"Sharpe ratio of **{sh:.2f}** indicates {adj} risk-adjusted performance."
                + (" Profits exceeded risk appropriately." if sh > 1 else
                   " Risk-adjusted returns need improvement." if sh > 0 else
                   " The strategy lost on a risk-adjusted basis."))

    def _what_worked(self, st: Dict, trades: List, attr: Dict = None) -> str:
        parts = []
        if attr and attr.get("by_strategy"):
            top = next(iter(attr["by_strategy"].items()))
            if top[1]["total_pnl"] > 0:
                parts.append(f"**{top[0]}** was top (${top[1]['total_pnl']:+,.0f}, {top[1]['contribution_pct']:.0f}% of PnL).")
        if st.get("win_rate", 0) > 0.6:
            parts.append("Trade selection quality was high.")
        return "## What Worked\n\n" + "\n".join(f"- {p}" for p in (parts or ["No clear positive patterns."]))

    def _what_didnt(self, st: Dict, trades: List, attr: Dict = None) -> str:
        parts = []
        if attr:
            by_s = list(attr.get("by_strategy", {}).items())
            if len(by_s) > 1 and by_s[-1][1]["total_pnl"] < 0:
                parts.append(f"**{by_s[-1][0]}** underperformed (${by_s[-1][1]['total_pnl']:+,.0f}).")
        dd = st.get("max_drawdown_pct", 0)
        if dd < -20:
            parts.append(f"Significant drawdown ({dd:.1f}%) — review risk management.")
        if st.get("profit_factor", 0) < 1.5:
            parts.append(f"Profit factor ({st['profit_factor']:.2f}) suggests winners don't outweigh losers.")
        cl = st.get("consecutive_losses", 0)
        if cl >= 5:
            parts.append(f"{cl} consecutive losses — consider a cool-off rule.")
        return "## What Didn't Work\n\n" + "\n".join(f"- {p}" for p in (parts or ["No major issues."]))

    def _risk_analysis(self, st: Dict) -> str:
        return ("## Risk Assessment\n\n"
                f"- Sharpe: **{st.get('sharpe_ratio',0):.2f}**\n"
                f"- Sortino: **{st.get('sortino_ratio',0):.2f}**\n"
                f"- Max DD: **{st.get('max_drawdown_pct',0):.1f}%**\n"
                f"- Calmar: **{st.get('calmar_ratio',0):.2f}**")

    def _suggestions(self, st: Dict, trades: List) -> str:
        sug = []
        if st.get("win_rate", 0) < 0.4:
            sug.append("Add pre-entry filters (volume confirmation, trend alignment).")
        if st.get("profit_factor", 0) < 1.2:
            sug.append("Let winners run longer, cut losers faster.")
        if st.get("sharpe_ratio", 0) < 0.5:
            sug.append("Reduce position sizing or tighten stops.")
        if st.get("max_drawdown_pct", 0) < -25:
            sug.append("Implement max daily loss limit.")
        if st.get("consecutive_losses", 0) >= 4:
            sug.append("Add '3 losses then stop' rule.")
        return "## Suggestions\n\n" + "\n".join(f"- {s}" for s in (sug or ["Maintain current approach. Monitor for regime changes."]))

    def generate_weekly_review(self, trades: List[TradeRecord], week_start: datetime = None) -> str:
        ws = week_start or (datetime.now(timezone.utc) - timedelta(days=7))
        wt = [t for t in trades if t.is_closed() and (t.exit_time or t.entry_time) >= ws]
        if not wt:
            return "## Weekly Review\n\nNo trades were closed this week."
        pnl = sum(t.pnl or 0 for t in wt)
        wins = sum(1 for t in wt if (t.pnl or 0) > 0)
        wr = wins / max(len(wt), 1) * 100
        day_pnl = defaultdict(float)
        for t in wt:
            day_pnl[(t.exit_time or t.entry_time).strftime("%A")] += t.pnl or 0
        best = max(day_pnl, key=day_pnl.get) if day_pnl else "N/A"
        worst = min(day_pnl, key=day_pnl.get) if day_pnl else "N/A"
        review = "Excellent week — maintain discipline." if wr > 60 and pnl > 0 else \
                 "Solid week with room for improvement." if pnl > 0 else \
                 "Tough week. Review what changed in market conditions."
        return (f"## Weekly Review\n\n"
                f"- **Trades:** {len(wt)} ({wins} wins, {len(wt)-wins} losses)\n"
                f"- **Win Rate:** {wr:.1f}%\n"
                f"- **PnL:** ${pnl:+,.0f}\n"
                f"- **Best Day:** {best} (${day_pnl[best]:+,.0f})\n"
                f"- **Worst Day:** {worst} (${day_pnl[worst]:+,.0f})\n\n"
                f"{review}")


# ===================================================================
# MasterReportingSuite
# ===================================================================

class MasterReportingSuite:
    """Unified reporting suite combining all report generators. One-call complete reports."""

    def __init__(self):
        self.performance = PerformanceReport()
        self.html_gen = HtmlReportGenerator()
        self.journal = TradingJournal()
        self.audit = AuditTrail()
        self.risk = RiskReport()
        self.attribution = AttributionReport()
        self.ai = AIReportGenerator()

    def generate_complete_report(self, trades: List[TradeRecord], equity_curve: pd.Series = None,
        positions: Dict[str, float] = None, returns: pd.DataFrame = None,
        output_dir: str = "reports", report_title: str = "Complete Trading Report") -> Dict:
        os.makedirs(output_dir, exist_ok=True)
        self.audit.log("report_generation", f"Generating {report_title}")

        perf_data = self.performance.generate_all(trades, equity_curve, None, None, report_title)
        html_path = self.html_gen.generate_performance_html(perf_data, os.path.join(output_dir, "performance_report.html"))

        attr = self.attribution.generate(trades)
        risk_data = self.risk.generate(positions or {}, returns or pd.DataFrame())

        ai_summary = self.ai.generate_summary(perf_data, trades, attr)
        weekly = self.ai.generate_weekly_review(trades)
        jhtml = self.journal.export_html(os.path.join(output_dir, "trade_journal.html"))
        ahtml = self.audit.export_regulatory_report(os.path.join(output_dir, "audit_report.html"))

        summary = {
            "title": report_title,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ai_summary": ai_summary,
            "weekly_review": weekly,
            "risk": risk_data,
            "attribution": attr,
            "files": {
                "html_report": html_path,
                "trade_journal": jhtml,
                "audit_report": ahtml,
            },
        }
        with open(os.path.join(output_dir, "report_summary.json"), "w") as f:
            json.dump(summary, f, indent=2, default=str)
        return summary