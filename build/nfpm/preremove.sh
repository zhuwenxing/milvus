#!/bin/bash
set -e
systemctl stop milvus 2>/dev/null || true
systemctl disable milvus 2>/dev/null || true
