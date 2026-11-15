import hashlib
import json
from dataclasses import asdict
from typing import Any, Dict
from app.core.engine.signal_engine import EngineConfig

class ConfigurationFingerprinter:
    """
    Generates a unique, stable fingerprint for an EngineConfig.
    Ensures that identical configurations have the same fingerprint.
    """
    
    @staticmethod
    def get_fingerprint(config: EngineConfig, instrument: str, timeframe: str) -> str:
        # Convert config to dict and remove non-parameter fields if any
        # (EngineConfig is a dataclass, so asdict works well)
        data = asdict(config)
        
        # Add instrument and timeframe as they are part of the combination identity
        data["_instrument"] = instrument
        data["_timeframe"] = timeframe
        
        # Sort keys to ensure stable JSON
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def config_to_dict(config: EngineConfig) -> Dict[str, Any]:
        return asdict(config)
