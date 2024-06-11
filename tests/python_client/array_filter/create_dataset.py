import random

import numpy as np
import pandas as pd
import polars as pl


def create_dataset(data_size: int, dimension: int, file_name: str):
    batch_size = 100000
    array_len = 100
    epoch = data_size // batch_size
    remain = data_size % batch_size
    for i in range(epoch):
        data = {
            "id": pd.Series([np.int64(x) for x in range(i * batch_size, (i + 1) * batch_size)]),
            "int_array": pd.Series(
                [np.array([random.randint(0, 200) for j in range(array_len)], dtype=np.dtype("int64")) for _ in
                 range(batch_size)]),
            "varchar_array": pd.Series(
                [np.array([str(random.randint(0, 200)) for j in range(array_len)], dtype=np.dtype("str")) for _ in
                 range(batch_size)]),
            "bool_array": pd.Series(
                [np.array([random.choice([True, False]) for j in range(array_len)], dtype=np.dtype("bool")) for _ in
                 range(batch_size)]),
            "emb": pd.Series([np.array([random.random() for j in range(dimension)], dtype=np.dtype("float32")) for _ in
                              range(batch_size)])
        }

        df = pd.DataFrame(data)
        # df = pl.DataFrame(df)
        df.to_parquet(file_name + f"_{i}.parquet")


if __name__ == "__main__":
    create_dataset(100000, 128, "array_test")
