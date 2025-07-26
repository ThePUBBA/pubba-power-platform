import pandas as pd

class ISO:
    @staticmethod
    def get_lmp(date: str, market: str, locations: list[str]) -> pd.DataFrame:
        if market not in ["LMP", "DAM"]:
            raise ValueError(f"{market} is not a valid Markets")

        # Placeholder response for testing
        return pd.DataFrame([
            {"location": loc, "date": date, "market": market, "price": 42.0}
            for loc in locations
        ])
