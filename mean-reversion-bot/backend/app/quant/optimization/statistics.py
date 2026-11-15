import numpy as np
from typing import List

class ExpectancyCalculator:
    """
    Calculates expectancy and confidence intervals.
    """
    
    @staticmethod
    def calculate_expectancy_r(returns: List[float]) -> float:
        if not returns:
            return 0.0
        return float(np.mean(returns))

    @staticmethod
    def block_bootstrap_ci(returns: List[float], n_iterations: int = 1000, block_size: int = 5) -> float:
        """
        Uses block bootstrap to estimate the lower 95% confidence bound of expectancy.
        Accounting for dependence between consecutive trades.
        """
        if len(returns) < 30:
            return -999.0
            
        boot_means = []
        n = len(returns)
        for _ in range(n_iterations):
            # Sample blocks
            resampled = []
            while len(resampled) < n:
                idx = np.random.randint(0, n - block_size + 1)
                resampled.extend(returns[idx : idx + block_size])
            boot_means.append(np.mean(resampled[:n]))
            
        # Lower 5th percentile for 95% confidence
        return float(np.percentile(boot_means, 5))
