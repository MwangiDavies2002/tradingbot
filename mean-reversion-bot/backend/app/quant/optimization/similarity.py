import numpy as np
from typing import Dict, Any, List
from app.core.engine.signal_engine import EngineConfig

class SimilarityCalculator:
    """
    Calculates similarity between two EngineConfig configurations.
    Uses normalized Euclidean distance for numeric parameters and 
    Simple Matching Coefficient (SMC) for boolean toggles.
    """
    
    # Define which parameters are numeric and their typical ranges for normalization
    NUMERIC_PARAMS = {
        "zscore_period": (10, 100),
        "bb_period": (10, 100),
        "bb_std_dev": (1.0, 4.0),
        "rsi_period": (7, 30),
        "atr_period": (7, 30),
        "stoch_k_period": (7, 30),
        "swing_lookback": (2, 20),
        "risk_pct": (0.001, 0.05),
        "sl_atr_mult": (0.5, 5.0),
        "tp_rr": (0.5, 10.0),
        "min_confluence": (1, 15)
    }
    
    # Define boolean toggles
    BOOLEAN_PARAMS = [
        "use_zscore", "use_bb", "use_rsi", "use_vwap", "use_stoch", 
        "use_lsl", "use_smc", "use_volume", "use_hurst", "use_smt"
    ]

    @classmethod
    def calculate_distance(cls, config1: Dict[str, Any], config2: Dict[str, Any]) -> float:
        """
        Returns a distance score between 0 and 1.
        0 = Identical
        1 = Completely different
        """
        numeric_dist = 0.0
        numeric_count = 0
        
        for param, (p_min, p_max) in cls.NUMERIC_PARAMS.items():
            if param in config1 and param in config2:
                v1 = config1[param]
                v2 = config2[param]
                # Normalize values
                n1 = (v1 - p_min) / (p_max - p_min)
                n2 = (v2 - p_min) / (p_max - p_min)
                numeric_dist += (n1 - n2) ** 2
                numeric_count += 1
        
        if numeric_count > 0:
            numeric_dist = np.sqrt(numeric_dist / numeric_count)
            
        boolean_diff = 0
        boolean_count = 0
        for param in cls.BOOLEAN_PARAMS:
            if param in config1 and param in config2:
                if config1[param] != config2[param]:
                    boolean_diff += 1
                boolean_count += 1
        
        boolean_dist = boolean_diff / boolean_count if boolean_count > 0 else 0.0
        
        # Weighted average (equal weight to numeric and boolean groups for now)
        return (numeric_dist + boolean_dist) / 2.0
