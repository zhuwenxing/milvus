import random
import pandas as pd
import numpy as np
import argparse
import os

def generate_dataset_batch(batch_size, array_length, hit_probabilities, target_values):
    dataset = []
    all_target_values = set(
        val for sublist in target_values.values() for val in (sublist if isinstance(sublist, list) else [sublist]))
    for i in range(batch_size):
        entry = {"id": i}

        for condition in hit_probabilities.keys():
            available_values = [val for val in range(1, 100) if val not in all_target_values]
            array = random.sample(available_values, array_length)

            if random.random() < hit_probabilities[condition]:
                if condition == 'contains':
                    if target_values[condition] not in array:
                        array[random.randint(0, array_length - 1)] = target_values[condition]
                elif condition == 'contains_any':
                    if not any(val in array for val in target_values[condition]):
                        array[random.randint(0, array_length - 1)] = random.choice(target_values[condition])
                elif condition == 'contains_all':
                    indices = random.sample(range(array_length), len(target_values[condition]))
                    for idx, val in zip(indices, target_values[condition]):
                        array[idx] = val
                elif condition == 'equals':
                    array = target_values[condition][:]

            entry[condition] = array

        dataset.append(entry)

    return dataset

def save_batch_to_parquet(batch, batch_number, output_dir):
    data = {
        "id": pd.Series([x["id"] for x in batch]),
        "contains": pd.Series([x["contains"] for x in batch]),
        "contains_any": pd.Series([x["contains_any"] for x in batch]),
        "contains_all": pd.Series([x["contains_all"] for x in batch]),
        "equals": pd.Series([x["equals"] for x in batch]),
        "emb": pd.Series([np.array([random.random() for j in range(128)], dtype=np.dtype("float32")) for _ in
                          range(len(batch))])
    }

    df = pd.DataFrame(data)
    filename = f"train_batch_{batch_number}.parquet"
    df.to_parquet(os.path.join(output_dir, filename))
    print(f"Saved {filename}")

def main(data_size, hit_rate=0.005, batch_size=1000000):
    # Parameters
    array_length = 10  # Length of each array

    # Probabilities that an array hits the target condition
    hit_probabilities = {
        'contains': hit_rate,
        'contains_any': hit_rate,
        'contains_all': hit_rate,
        'equals': hit_rate
    }

    # Target values for each condition
    target_values = {
        'contains': 42,
        'contains_any': [21, 37, 42],
        'contains_all': [15, 30],
        'equals': [x for x in range(array_length)]
    }

    # Create output directory
    output_dir = "train_data"
    os.makedirs(output_dir, exist_ok=True)

    # Generate and save data in batches
    for batch_number in range(0, data_size, batch_size):
        current_batch_size = min(batch_size, data_size - batch_number)
        batch = generate_dataset_batch(current_batch_size, array_length, hit_probabilities, target_values)
        save_batch_to_parquet(batch, batch_number // batch_size, output_dir)

    # Perform tests on the last batch (as an example)
    contains_value = target_values['contains']
    contains_any_values = target_values['contains_any']
    contains_all_values = target_values['contains_all']
    equals_array = target_values['equals']

    contains_result = [d for d in batch if contains_value in d["contains"]]
    contains_any_result = [d for d in batch if any(val in d["contains_any"] for val in contains_any_values)]
    contains_all_result = [d for d in batch if all(val in d["contains_all"] for val in contains_all_values)]
    equals_result = [d for d in batch if d["equals"] == equals_array]

    # Calculate and print proportions for the last batch
    contains_ratio = len(contains_result) / current_batch_size
    contains_any_ratio = len(contains_any_result) / current_batch_size
    contains_all_ratio = len(contains_all_result) / current_batch_size
    equals_ratio = len(equals_result) / current_batch_size

    print("\nProportions for the last batch:")
    print("Proportion of arrays that contain the value:", contains_ratio)
    print("Proportion of arrays that contain any of the values:", contains_any_ratio)
    print("Proportion of arrays that contain all of the values:", contains_all_ratio)
    print("Proportion of arrays that equal the target array:", equals_ratio)

    # Generate test data
    target_id = {
        "contains": [r["id"] for r in contains_result],
        "contains_any": [r["id"] for r in contains_any_result],
        "contains_all": [r["id"] for r in contains_all_result],
        "equals": [r["id"] for r in equals_result]
    }
    target_id_list = [target_id[key] for key in ["contains", "contains_any", "contains_all", "equals"]]

    query_data = {
        "filter": ["contains", "contains_any", "contains_all", "equals"],
        "value": [[42], [21, 37, 42], [15, 30], [0, 1, 2, 3, 4]],
        "target_id": target_id_list
    }
    df = pd.DataFrame(query_data)
    print(df)
    df.to_parquet("test.parquet")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_size", type=int, default=100000)
    parser.add_argument("--hit_rate", type=float, default=0.005)
    parser.add_argument("--batch_size", type=int, default=100000)
    args = parser.parse_args()
    main(args.data_size, args.hit_rate, args.batch_size)
