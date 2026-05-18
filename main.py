import os

from dotenv import load_dotenv
import oracledb
import pandas as pd
import streamlit as st

load_dotenv()

password = os.getenv("ORACLE_PASSWORD")

# 让 oracledb 进入 thick 模式，加载 Instant Client
oracledb.init_oracle_client(lib_dir=r".\lib\instantclient-basic-windows.x64-19.30.0.0.0dbru\instantclient_19_30")

print(os.getenv("ORACLE_PASSWORD"))

conn = oracledb.connect(
    user=os.getenv("ORACLE_USER"),
    password=os.getenv("ORACLE_PASSWORD"),
    dsn=os.getenv("ORACLE_DSN")
)