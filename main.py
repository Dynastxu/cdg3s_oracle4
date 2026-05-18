import os
from datetime import date

import oracledb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# ---------- 数据库连接 ----------
@st.cache_resource
def get_connection():
    """建立并缓存数据库连接"""
    oracledb.init_oracle_client(
        lib_dir=os.getenv("INSTANT_CLIENT_DIR")
    )
    return oracledb.connect(
        user=os.getenv("ORACLE_USER"),
        password=os.getenv("ORACLE_PASSWORD"),
        dsn=os.getenv("ORACLE_DSN")
    )


# ---------- 辅助函数：获取当前学期 ----------
def get_current_semester():
    """根据当前日期查找所在学期，若无则返回最新学期"""
    today = date.today().strftime('%Y-%m-%d')
    query = f"""
        SELECT semester_id, semester_name, start_date, end_date
        FROM (
            SELECT semester_id, semester_name, start_date, end_date
            FROM {data_schema}.semester
            WHERE TO_DATE(:today, 'YYYY-MM-DD') BETWEEN start_date AND end_date
            ORDER BY start_date DESC
        )
        WHERE ROWNUM = 1
    """
    df = pd.read_sql(query, conn, params={"today": today})
    if not df.empty:
        return df.iloc[0]
    # 如果当前日期不在任何学期内，取最近结束的学期
    query2 = f"""
        SELECT semester_id, semester_name, start_date, end_date
        FROM (
            SELECT semester_id, semester_name, start_date, end_date
            FROM {data_schema}.semester
            WHERE end_date <= TO_DATE(:today, 'YYYY-MM-DD')
            ORDER BY end_date DESC
        )
        WHERE ROWNUM = 1
    """
    df2 = pd.read_sql(query2, conn, params={"today": today})
    if not df2.empty:
        return df2.iloc[0]
    return None

def main():
    """主页面"""
    st.title("🎓 学生管理信息系统")
    st.markdown("欢迎使用学生管理信息系统，以下为实时数据概览。")

    # 获取当前学期
    current_sem = get_current_semester()
    if current_sem is not None:
        sem_id = int(current_sem['SEMESTER_ID'])
        sem_name = current_sem['SEMESTER_NAME']
        st.caption(f"当前统计学期：{sem_name}")
    else:
        sem_id = None
        sem_name = "未设置学期"
        st.warning("未找到当前学期，部分数据可能为空。请先设置学期。")

if __name__ == "__main__":
    load_dotenv()
    conn = get_connection()
    data_schema = os.getenv("DATA_SCHEMA_NAME")
    # 页面配置
    st.set_page_config(
        page_title="学生管理信息系统",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    main()