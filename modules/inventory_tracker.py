# modules/inventory_tracker.py

from nubra_python_sdk.portfolio.portfolio_data import NubraPortfolio

class PairInventoryTracker:
    def __init__(self, target_assets):
        """
        Maintains optimistic RAM state for Cash and Futures legs.
        State format: { "HDFCBANK": {"spot_qty": 0, "fut_qty": 0} }
        """
        self.inventory = {
            asset: {"spot_qty": 0, "fut_qty": 0} 
            for asset in target_assets
        }

    def sync_with_broker(self, nubra_client, pair_mapping):
        """
        THE SLOW PATH: Run only once at startup (08:45 AM).
        Fetches true net positions from the broker and updates RAM.
        """
        print("[INVENTORY] Syncing true positions from broker...")
        portfolio = NubraPortfolio(nubra_client)
        
        try:
            # Attempt V2 API (per latest documentation)
            try:
                result = portfolio.positions(version="V2")
                positions_list = result.portfolio.positions
                is_v2 = True
            except TypeError:
                # Fallback to V1 if the local SDK is outdated
                print("[INVENTORY] ⚠️ SDK outdated. Falling back to V1 positions API.")
                result = portfolio.positions()
                positions_list = result.portfolio.positions
                is_v2 = False

            if not positions_list:
                print("[INVENTORY] No open positions found. Starting fresh.")
                return

            # Map broker ref_ids back to our target assets
            for pos in positions_list:
                pos_ref_id = pos.ref_id
                
                # V2 uses 'net_quantity', V1 uses 'quantity'
                net_qty = pos.net_quantity if is_v2 else pos.quantity
                
                if net_qty == 0:
                    continue

                # Find which asset and leg this ref_id belongs to
                for asset, refs in pair_mapping.items():
                    if pos_ref_id == refs["spot_ref_id"]:
                        self.inventory[asset]["spot_qty"] = net_qty
                        print(f"[INVENTORY SYNC] {asset} SPOT: {net_qty}")
                        break
                    elif pos_ref_id == refs["futures_ref_id"]:
                        self.inventory[asset]["fut_qty"] = net_qty
                        print(f"[INVENTORY SYNC] {asset} FUT: {net_qty}")
                        break

        except Exception as e:
            print(f"[INVENTORY] ⚠️ Warning: Failed to sync positions: {e}")

    def assume_filled(self, asset, spot_qty_change, fut_qty_change):
        """
        THE HOT PATH: Called instantly when ML Risk Engine fires a Final Signal.
        """
        self.inventory[asset]["spot_qty"] += spot_qty_change
        self.inventory[asset]["fut_qty"] += fut_qty_change

    def revert_fill(self, asset, spot_qty_revert, fut_qty_revert):
        """
        THE FEEDBACK LOOP: Called only if Execution Engine reports a rejection.
        """
        self.inventory[asset]["spot_qty"] -= spot_qty_revert
        self.inventory[asset]["fut_qty"] -= fut_qty_revert
        print(f"[INVENTORY FIX] Reverted {asset}. "
              f"Current Spot: {self.inventory[asset]['spot_qty']}, "
              f"Fut: {self.inventory[asset]['fut_qty']}")

    def get_net_basis_exposure(self, asset):
        """
        Returns the directional bias of the pair to feed into the Avellaneda (C5) risk gate.
        """
        return {
            "spot": self.inventory[asset]["spot_qty"],
            "fut": self.inventory[asset]["fut_qty"]
        }