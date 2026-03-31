import pandas as pd

# -------- LOAD DATA --------
df = pd.read_csv("database_24_25.csv")

# print(df.head())
# print(df.columns.tolist())
# print(df.shape)
# print(df.isnull().sum())

# -------- CLEAN DATA --------
df = df.dropna(subset=["Player"])
df["Data"] = pd.to_datetime(df["Data"], errors="coerce")

numeric_cols = [
    "MP", "FG", "FGA", "FG%", "3P", "3PA", "3P%", "FT", "FTA", "FT%",
    "ORB", "DRB", "TRB", "AST", "STL", "BLK", "TOV", "PF", "PTS", "GmSc"
]

for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(subset=["MP", "PTS", "GmSc"])

# print(df.head())
# print(df.shape)
# print(df[numeric_cols].dtypes)

# -------- PLAYER AGGREGATION --------
player_stats = df.groupby("Player").agg({
    "Tm": "first",
    "MP": "mean",
    "PTS": "mean",
    "AST": "mean",
    "TRB": "mean",
    "STL": "mean",
    "BLK": "mean",
    "TOV": "mean",
    "FG%": "mean",
    "3P%": "mean",
    "FT%": "mean",
    "GmSc": "mean"
}).reset_index()

# -------- ADD GAMES PLAYED --------
games_played = df.groupby("Player").size().reset_index(name="Games")
player_stats = player_stats.merge(games_played, on="Player", how="left")

# -------- CREATE NEW METRICS --------
player_stats["PTS_per_min"] = player_stats["PTS"] / player_stats["MP"]
player_stats["AST_per_min"] = player_stats["AST"] / player_stats["MP"]
player_stats["TRB_per_min"] = player_stats["TRB"] / player_stats["MP"]

round_cols = [
    "MP", "PTS", "AST", "TRB", "STL", "BLK", "TOV",
    "FG%", "3P%", "FT%", "GmSc",
    "PTS_per_min", "AST_per_min", "TRB_per_min"
]

player_stats[round_cols] = player_stats[round_cols].round(3)

# -------- FILTER SMALL SAMPLES --------
player_stats = player_stats[player_stats["Games"] >= 10].copy()

# -------- FINAL OUTPUT --------
print(player_stats.head())
print(player_stats.shape)
print(player_stats.columns.tolist())
print(player_stats.sort_values("PTS", ascending=False).head(10))
player_stats.to_csv(r"C:\Users\harrison\Desktop\Projects\nba_cleaned.csv", index=False)
print("File saved successfully")
import os
print(os.getcwd())