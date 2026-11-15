import logging
from typing import List, Dict, Any, Optional
import numpy as np
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import StrategyCombination, SimilarityCluster, ExplorationRound
from app.quant.optimization.similarity import SimilarityCalculator

logger = logging.getLogger(__name__)

class DiversityScheduler:
    """
    Implements diversity-first exploration rules.
    1. Never schedule duplicate fingerprints.
    2. Never schedule two configurations from the same similarity cluster in the same exploration batch.
    3. Prioritize unexplored clusters and parameter regions.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db

    async def cluster_combinations(self, strategy_family: str, distance_threshold: float = 0.2):
        """
        Groups combinations into clusters based on similarity.
        Simple greedy clustering for now (DBSCAN-like).
        """
        # Fetch all candidates for this family that don't have a cluster
        stmt = select(StrategyCombination).where(
            and_(
                StrategyCombination.strategy_name == strategy_family,
                StrategyCombination.cluster_id == None
            )
        )
        res = await self.db.execute(stmt)
        candidates = res.scalars().all()
        
        if not candidates:
            return

        # Fetch existing clusters for this family
        stmt_clusters = select(SimilarityCluster).where(SimilarityCluster.strategy_family == strategy_family)
        res_clusters = await self.db.execute(stmt_clusters)
        existing_clusters = res_clusters.scalars().all()
        
        for cand in candidates:
            assigned = False
            cand_params = cand.parameters_json
            
            # Try to assign to existing cluster
            for cluster in existing_clusters:
                dist = SimilarityCalculator.calculate_distance(cand_params, cluster.centroid_json)
                if dist < distance_threshold:
                    cand.cluster_id = cluster.id
                    assigned = True
                    break
            
            if not assigned:
                # Create new cluster
                new_cluster = SimilarityCluster(
                    strategy_family=strategy_family,
                    centroid_json=cand_params
                )
                self.db.add(new_cluster)
                await self.db.flush() # Get ID
                cand.cluster_id = new_cluster.id
                existing_clusters.append(new_cluster)
                
        await self.db.commit()

    async def get_next_batch(self, strategy_family: str, batch_size: int = 5) -> List[StrategyCombination]:
        """
        Selects the next batch of combinations to run.
        Rule: One per cluster per batch.
        """
        # Get all clusters that have pending combinations
        stmt = select(StrategyCombination.cluster_id).where(
            and_(
                StrategyCombination.strategy_name == strategy_family,
                StrategyCombination.status == "candidate"
            )
        ).distinct()
        res = await self.db.execute(stmt)
        cluster_ids = [r for r in res.scalars().all() if r is not None]
        
        if not cluster_ids:
            return []
            
        # Prioritize clusters that haven't been tested as much in the current round
        # For simplicity, we just pick one from each cluster until we hit batch_size
        selected_combs = []
        for cid in cluster_ids[:batch_size]:
            # Select one candidate from this cluster
            stmt_pick = select(StrategyCombination).where(
                and_(
                    StrategyCombination.cluster_id == cid,
                    StrategyCombination.status == "candidate"
                )
            ).limit(1)
            res_pick = await self.db.execute(stmt_pick)
            comb = res_pick.scalar_one_or_none()
            if comb:
                # Mark as queued
                comb.status = "queued"
                selected_combs.append(comb)
        
        await self.db.commit()
        return selected_combs

    async def reserve_combination(self, fingerprint: str) -> bool:
        """
        Atomic reservation of a combination to prevent concurrent workers 
        from picking the same one.
        """
        stmt = update(StrategyCombination).where(
            and_(
                StrategyCombination.fingerprint == fingerprint,
                StrategyCombination.status == "queued"
            )
        ).values(status="running").execution_options(synchronize_session="fetch")
        
        res = await self.db.execute(stmt)
        await self.db.commit()
        return res.rowcount > 0
