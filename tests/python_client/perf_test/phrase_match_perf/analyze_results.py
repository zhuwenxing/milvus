import pandas as pd
import os

from constants import RESULTS_DIR

# Define phrase probabilities mapping
phrase_probabilities = {
    "vector_similarity": 0.1,        # Most common phrase
    "milvus_search": 0.01,         # Medium frequency phrase
    "nearest_neighbor_search": 0.001,  # Less common phrase
    "high_dimensional_vector_index": 0.0001,  # Rare phrase
}

def get_qps(phrase, expr_type, load_type):
    if load_type == "progressive":
        phrase_new = phrase.replace(" ", "_")
        filename = f"{RESULTS_DIR}/{phrase_new}_{expr_type}_progressive_stats_history.csv"
        if not os.path.exists(filename):
            return None
        df = pd.read_csv(filename)
        return df["Requests/s"].max()
    if load_type == "fixed":
        phrase_new = phrase.replace(" ", "_")
        filename = f"{RESULTS_DIR}/{phrase_new}_{expr_type}_fixed_stats.csv"
        if not os.path.exists(filename):
            return None
        df = pd.read_csv(filename)
        return df["Requests/s"].iloc[0]
    return None



results = []
for phrase, hit_rate in phrase_probabilities.items():
    print(f"Phrase: {phrase}, Hit Rate: {hit_rate}")
    for expr_type in ["phrase_match", "like"]:
        for load_type in ["progressive", "fixed"]:
            qps = get_qps(phrase, expr_type, load_type)
            results.append({
                "expr": expr_type,
                "hit_rate": hit_rate,
                "qps": qps,
                "load_type": load_type
            })

df = pd.DataFrame(results)
df = df[["expr", "hit_rate", "qps", "load_type"]]

df.to_csv("results/qps_comparison_all.csv", index=False)

print("\nQPS Comparison Results:")
print(df)
