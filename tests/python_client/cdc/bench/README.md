```bash
locust -f insert_perf_progressive_load.py --milvus-uri http://10.104.9.80:19530 --processes 15 --headless

locust -f insert_perf_static_load.py --milvus-uri http://10.255.180.125:19530 --processes 15 -u 50 -t 1h -r 10 --headless
```