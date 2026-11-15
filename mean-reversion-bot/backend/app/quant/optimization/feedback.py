from typing import List, Dict, Any
from app.backtesting.backtest_engine import BacktestReport

class FeedbackEngine:
    """
    Generates human-readable feedback based on calculated metrics.
    """
    
    @staticmethod
    def generate_feedback(report: BacktestReport) -> List[str]:
        insights = []
        
        if report.total_trades < 30:
            insights.append("This configuration has insufficient trade observations (less than 30).")
            return insights

        if report.expectancy_r < 0:
            if report.win_rate > 0.5:
                insights.append("Win rate is reasonable, but expectancy is negative because average losses exceed average wins.")
            else:
                insights.append("Expectancy is negative due to low win rate.")

        if report.exit_efficiency < 0.4:
            insights.append("Exit efficiency is low; investigate whether the exit rules are prematurely closing profitable trades.")

        # Session analysis
        by_hour = report.market_analysis.get("by_hour", {})
        losing_hours = [h for h, stats in by_hour.items() if stats["pnl"] < 0]
        if "hour_09" in losing_hours or "hour_10" in losing_hours:
            insights.append("Most losses occur during the first hours of the session.")

        if report.sharpe_ratio < 1.0:
            insights.append("Low Sharpe ratio indicates poor risk-adjusted returns.")

        if report.max_drawdown_pct > 0.2:
            insights.append("Maximum drawdown is high; consider tightening stop-loss or reducing stake.")

        return insights
