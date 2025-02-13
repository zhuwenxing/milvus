import os
import json
import re
import pandas as pd
from constants import RESULTS_DIR

from constants import TEST_PHRASES

# Use TEST_PHRASES as phrase probabilities mapping
phrase_probabilities = TEST_PHRASES

def extract_json_from_html(html_content):
    # Find content between <script> tags
    script_pattern = re.search(r'<script>\s*window\.templateArgs\s*=\s*({[\s\S]*?})\s*window\.theme', html_content)
    if script_pattern:
        try:
            # Extract and parse the JSON data
            json_str = script_pattern.group(1)
            # Clean up any trailing commas before arrays/objects close
            json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {str(e)}")
            print(f"Problematic JSON string: {json_str}")
            return None
    return None

def calculate_max_avg_qps(history):
    # Group data points by user_count
    user_groups = {}
    for point in history:
        user_count = point['user_count']
        if user_count not in user_groups:
            user_groups[user_count] = []
        user_groups[user_count].append(point['current_rps'])
    
    # Calculate average QPS for each user group
    avg_qps_by_users = {}
    for user_count, qps_values in user_groups.items():
        avg_qps_by_users[user_count] = sum(qps_values) / len(qps_values)
    
    # Return the maximum average QPS
    if avg_qps_by_users:
        max_avg_qps = max(avg_qps_by_users.values())
        max_user_count = max(k for k, v in avg_qps_by_users.items() if v == max_avg_qps)
        print(f"Max average QPS: {max_avg_qps:.2f} at {max_user_count} users")
        return max_avg_qps
    return None

def get_qps(phrase, expr_type, load_type):
    if load_type in ["progressive", "fixed"]:
        phrase_new = phrase.replace(" ", "_")
        filename = f"{RESULTS_DIR}/html/{phrase_new}_{expr_type}_{load_type}.html"
        print(filename)
        if not os.path.exists(filename):
            return None
        try:
            with open(filename, 'r') as f:
                html_content = f.read()
            
            data = extract_json_from_html(html_content)
            if data and 'history' in data:
                return calculate_max_avg_qps(data['history'])
            return None
        except Exception as e:
            print(f"Error reading {filename}: {str(e)}")
            return None
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

df.to_csv(RESULTS_DIR + "/qps_comparison_all.csv", index=False)

print("\nQPS Comparison Results:")
print(df)
