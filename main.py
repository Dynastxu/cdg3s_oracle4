import os
from datetime import date

import oracledb
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from datetime import date, timedelta

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


@st.cache_data(ttl=600)
def load_stats(semester_id):
    """加载首页统计数据"""
    # 1. 在读学生总数
    __stats = {'total_students': pd.read_sql(
        f"SELECT COUNT(*) AS CNT FROM {data_schema}.student WHERE status = '在读'", conn
    ).iloc[0, 0]}

    # 2. 本学期选课人次
    if semester_id is not None:
        __stats['enroll_count'] = pd.read_sql(
            f"SELECT COUNT(*) FROM {data_schema}.student_course WHERE semester_id = :sid",
            conn, params={"sid": semester_id}
        ).iloc[0, 0]
    else:
        __stats['enroll_count'] = 0

    # 3. 缺勤预警人数（本学期缺勤总课时 >= 10）
    if semester_id is not None:
        __stats['absence_warning'] = pd.read_sql(
            f"""SELECT COUNT(*) FROM (
                   SELECT student_no, SUM(hours) AS total_hours
                   FROM {data_schema}.absence_record
                   WHERE semester_id = :sid
                   GROUP BY student_no
                   HAVING SUM(hours) >= 10
               )""",
            conn, params={"sid": semester_id}
        ).iloc[0, 0]
    else:
        __stats['absence_warning'] = 0

    # 4. 待补考人数（正考未通过且考试类型为正考，关联当前学期选课）
    if semester_id is not None:
        __stats['resit_count'] = pd.read_sql(
            f"""SELECT COUNT(DISTINCT sc.student_no)
               FROM {data_schema}.student_course sc
               JOIN {data_schema}.score s ON sc.sc_id = s.sc_id
               WHERE sc.semester_id = :sid
                 AND s.exam_type_code = '正考'
                 AND s.is_passed = 0""",
            conn, params={"sid": semester_id}
        ).iloc[0, 0]
    else:
        __stats['resit_count'] = 0

    return __stats

@st.cache_data(ttl=600)
def load_college_distribution():
    """学院人数分布（在读）"""
    df = pd.read_sql(
        f"""SELECT c.college_name, COUNT(s.student_no) AS cnt
           FROM {data_schema}.student s
           JOIN {data_schema}.class cl ON s.class_id = cl.class_id
           JOIN {data_schema}.major m ON cl.major_id = m.major_id
           JOIN {data_schema}.college c ON m.college_id = c.college_id
           WHERE s.status = '在读'
           GROUP BY c.college_name
           ORDER BY cnt DESC""",
        conn
    )
    return df

@st.cache_data(ttl=600)
def load_weekly_absence(semester_id):
    """近四周缺勤趋势"""
    if semester_id is None:
        return pd.DataFrame()
    # 获取当前学期的起始和结束日期
    sem_info = pd.read_sql(
        f"SELECT start_date, end_date FROM {data_schema}.semester WHERE semester_id = :sid",
        conn, params={"sid": semester_id}
    ).iloc[0]
    start = sem_info['START_DATE']
    end = sem_info['END_DATE']

    # 将数据库返回的 Timestamp 转换为 date 对象
    if hasattr(start, 'date'):
        start = start.date() if hasattr(start, 'date') else start
    if hasattr(end, 'date'):
        end = end.date() if hasattr(end, 'date') else end

    # 计算近四周的日期范围：从今天往前推4周，但不得早于学期开始
    today = date.today()
    four_weeks_ago = today - timedelta(weeks=4)
    range_start = max(four_weeks_ago, start)
    range_end = today

    query = f"""
        SELECT TRUNC(absence_date, 'IW') AS week_start,
               COUNT(*) AS absence_count
        FROM {data_schema}.absence_record
        WHERE semester_id = :sid
          AND absence_date BETWEEN :start_d AND :end_d
        GROUP BY TRUNC(absence_date, 'IW')
        ORDER BY week_start
    """
    df = pd.read_sql(query, conn,
                     params={"sid": semester_id,
                             "start_d": range_start,
                             "end_d": range_end})
    df['WEEK_START'] = pd.to_datetime(df['WEEK_START'])
    return df

@st.cache_data(ttl=600)
def load_score_distribution(semester_id):
    """成绩分布（当前学期正考成绩）"""
    if semester_id is None:
        return pd.DataFrame()
    query = f"""
        SELECT 
            CASE 
                WHEN s.score_value >= 90 THEN '优'
                WHEN s.score_value >= 80 THEN '良'
                WHEN s.score_value >= 70 THEN '中'
                WHEN s.score_value >= 60 THEN '及格'
                ELSE '不及格'
            END AS grade,
            COUNT(*) AS cnt
        FROM {data_schema}.score s
        JOIN {data_schema}.student_course sc ON s.sc_id = sc.sc_id
        WHERE sc.semester_id = :sid
          AND s.exam_type_code = '正考'
        GROUP BY 
            CASE 
                WHEN s.score_value >= 90 THEN '优'
                WHEN s.score_value >= 80 THEN '良'
                WHEN s.score_value >= 70 THEN '中'
                WHEN s.score_value >= 60 THEN '及格'
                ELSE '不及格'
            END
        ORDER BY grade
    """
    df = pd.read_sql(query, conn, params={"sid": semester_id})
    # 确保顺序
    order = ['优', '良', '中', '及格', '不及格']
    df['grade'] = pd.Categorical(df['GRADE'], categories=order, ordered=True)
    df = df.sort_values('grade')
    return df

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

    # 加载统计数据
    with st.spinner("正在加载统计数据..."):
        stats = load_stats(sem_id)
        college_df = load_college_distribution()
        weekly_abs = load_weekly_absence(sem_id)
        score_dist = load_score_distribution(sem_id)

    # ---------- 统计卡片 ----------
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="在读学生总数", value=stats['total_students'])
    with col2:
        st.metric(label="本学期选课人次", value=stats['enroll_count'])
    with col3:
        st.metric(label="缺勤预警人数 (≥10课时)", value=stats['absence_warning'])
    with col4:
        st.metric(label="待补考人数", value=stats['resit_count'])


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