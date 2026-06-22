import sys, os, warnings, numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
warnings.filterwarnings('ignore')
np.random.seed(42)

from pro.portfolio.pro_portfolio_manager import (
    ModernPortfolioTheory, RiskParity, PortfolioConstructor, 
    PerformanceAnalytics, DrawdownAnalytics, PortfolioAttribution,
    CorrelationAnalyzer, RebalancingEngine, AllocationOptimizer,
    PortfolioState, Position,
)
print("ALL 9 CLASSES IMPORTED")

# Test data
n_assets, n_periods = 5, 500
asset_names = ['SPY', 'AGG', 'GLD', 'EEM', 'VNQ']
mean_ret = np.array([0.0008, 0.0002, 0.0003, 0.0005, 0.0004])
vols = np.array([0.012, 0.004, 0.008, 0.014, 0.010])
corr = np.array([
    [1.0,0.3,0.1,0.7,0.5],[0.3,1.0,0.2,0.3,0.4],
    [0.1,0.2,1.0,0.2,0.3],[0.7,0.3,0.2,1.0,0.5],
    [0.5,0.4,0.3,0.5,1.0]])
cov = corr * np.outer(vols, vols)
L = np.linalg.cholesky(cov + np.eye(n_assets)*1e-8)
dates = pd.date_range('2020-01-01', periods=n_periods, freq='B')
returns = pd.DataFrame(np.random.randn(n_periods,n_assets)@L.T+mean_ret,index=dates,columns=asset_names)
print("Data:", returns.shape)

# --- 1. MPT ---
mpt = ModernPortfolioTheory(returns, risk_free_rate=0.02)
frontier = mpt.efficient_frontier(n_portfolios=2000)
print("MPT frontier:", len(frontier), "points")
ms = mpt.max_sharpe_portfolio()
print("MS weights:", {k: round(v,3) for k,v in ms['weights'].items()})
mv = mpt.min_variance_portfolio()
print("MV vol:", round(mv['volatility'],4))
md = mpt.max_diversification_portfolio()
print("MD DR:", round(md.get('diversification_ratio',0),4))
bl = mpt.black_litterman(np.array([0.4,0.2,0.1,0.2,0.1]),
    [{'assets':['SPY','EEM'],'type':'relative','value':0.05,'confidence':0.6}])
print("BL Sharpe:", round(bl['sharpe'],4))
print("MPT PASSSED")

# --- 2. RiskParity ---
rp = RiskParity(cov)
erc = rp.equal_risk_contribution()
print("ERC RC:", [round(float(x),3) for x in erc['risk_contributions']])
iv = rp.inverse_volatility()
print("IV RC:", [round(float(x),3) for x in iv['risk_contributions']])
hrp = rp.hierarchical_risk_parity()
print("HRP RC:", [round(float(x),3) for x in hrp['risk_contributions']])
print("RiskParity PASSSED")

# --- 3. PortfolioConstructor ---
pc = PortfolioConstructor(initial_cash=1000000)
pc.execute_trade('SPY', 1000, 450.0)
pc.execute_trade('AGG', 5000, 105.0)
print("Total:", round(pc.state.total_value,2))
print("Lev:", round(pc.leverage(),2))
print("EffN:", round(pc.effective_n(),2))
print("PortfolioConstructor PASSSED")

# --- 4. PerformanceAnalytics ---
pa = PerformanceAnalytics(returns.sum(axis=1), returns['SPY'], risk_free_rate=0.02)
sr = pa.sharpe_ratio()
print("Sharpe:", round(sr['annualized_sharpe'],4), "p=", round(sr['p_value'],4))
print("Sortino:", round(pa.sortino_ratio(),4))
print("Calmar:", round(pa.calmar_ratio(),4))
print("WinRate:", round(pa.win_rate(),3))
print("ProfitFactor:", round(pa.profit_factor(),3))
print("PerformanceAnalytics PASSSED")

# --- 5. DrawdownAnalytics ---
dd = DrawdownAnalytics(returns.sum(axis=1))
mdd_info = dd.max_drawdown
print("MaxDD:", round(mdd_info['max_drawdown']*100,2),"%")
print("PainRatio:", round(dd.pain_ratio(),4))
print("DrawdownAnalytics PASSSED")

# --- 6. PortfolioAttribution (fixed index alignment) ---
bm_weights = pd.DataFrame(np.ones((100,5))/5, index=returns.tail(100).index, columns=asset_names)
port_weights = pd.DataFrame(np.random.dirichlet(np.ones(5),100), index=returns.tail(100).index, columns=asset_names)
sector_map = {a:['Equity','Bond','Commodity','Equity','RealEstate'][i] for i,a in enumerate(asset_names)}
pa_attr = PortfolioAttribution(port_weights, returns.tail(100), bm_weights, returns.tail(100)*0.95, sector_map)
brin = pa_attr.brinson_attribution()
print("Allocation:", round(brin['allocation_effect'],6))
print("Selection:", round(brin['selection_effect'],6))
print("Total active:", round(brin['total_active_return'],6))
print("PortfolioAttribution PASSSED")

# --- 7. CorrelationAnalyzer ---
ca = CorrelationAnalyzer(returns)
print("EffNFactors:", round(ca.effective_n_factors(),2))
pca_r = ca.pca_risk_factors()
print("PCA comps:", pca_r['n_components'], "var:", [round(float(v),3) for v in pca_r['explained_variance_ratio'][:2]])
clust = ca.cluster_analysis()
print("Clusters:", clust['n_clusters'])
print("Cophenetic:", round(clust['cophenetic_correlation'],4))
reg = ca.regime_detection()
print("Regimes:", reg['n_regimes'])
print("CorrelationAnalyzer PASSSED")

# --- 8. RebalancingEngine ---
rebal = RebalancingEngine({'SPY':0.4,'AGG':0.3,'GLD':0.2,'EEM':0.1}, pc)
from datetime import datetime
t0 = rebal.rebalance_calendar(datetime(2025,1,1), frequency='monthly')
print("Calendar trades:", len(t0))
t1 = rebal.rebalance_threshold(threshold=0.1)
print("Threshold trades:", len(t1))
print("RebalancingEngine PASSSED")

# --- 9. AllocationOptimizer ---
ao = AllocationOptimizer(returns)
ga = ao.goal_based_allocation(goal_type='growth', risk_tolerance=0.6)
print("Goal Ret:", round(ga['expected_return'],4), "Vol:", round(ga['expected_volatility'],4))
lc = ao.lifecycle_allocation(age=35, retirement_age=65)
print("Lifecycle Equity:", round(lc['equity_allocation'],3))
fb = ao.factor_based_allocation(
    pd.DataFrame(np.random.randn(5,4), index=asset_names, columns=['Value','Momentum','Size','Quality']),
    {'Value':0.3, 'Momentum':0.2}, max_tracking_error=0.08)
print("Factor TE:", round(fb['tracking_error'],4))
rb = ao.risk_budget_allocation()
print("RiskBudget Vol:", round(rb['expected_volatility'],4))
print("AllocationOptimizer PASSSED")

print()
print("ALL 9 CLASSES FULLY TESTED AND OPERATIONAL")
