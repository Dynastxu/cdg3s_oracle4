import os
from datetime import date, timedelta
from typing import Optional

import oracledb
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class DatabaseManager:
    """数据库管理器（使用 SQLAlchemy 引擎，统一大写列名）"""

    def __init__(self):
        load_dotenv()
        self.data_schema = os.getenv("DATA_SCHEMA_NAME")
        self.engine: Optional[Engine] = None

    def init_connection(self) -> Engine | None:
        """初始化数据库引擎"""
        oracledb.init_oracle_client(
            lib_dir=os.getenv("INSTANT_CLIENT_DIR")
        )
        user = os.getenv("ORACLE_USER")
        password = os.getenv("ORACLE_PASSWORD")
        dsn = os.getenv("ORACLE_DSN")
        # Oracle + oracledb 驱动连接字符串
        connection_string = f"oracle+oracledb://{user}:{password}@{dsn}"
        self.engine = create_engine(connection_string)
        return self.engine

    def get_connection(self) -> Engine | None:
        """获取数据库引擎"""
        if self.engine is None:
            self.init_connection()
        return self.engine

    def close_connection(self):
        """关闭数据库引擎"""
        if self.engine:
            self.engine.dispose()
            self.engine = None

    def _safe_read_sql(self, sql: str, params: Optional[dict] = None) -> pd.DataFrame:
        """
        执行 SQL 查询并返回列名均为大写的 DataFrame
        """
        engine = self.get_connection()
        if params is None:
            df = pd.read_sql(sql, engine)
        else:
            df = pd.read_sql(sql, engine, params=params)
        # 将所有列名转为大写
        df.columns = df.columns.str.upper()
        return df

    def get_current_semester(self) -> Optional[pd.Series]:
        """根据当前日期查找所在学期，若无则返回最新学期（返回 Series 索引为大写）"""
        today = date.today().strftime('%Y-%m-%d')

        query = f"""
            SELECT semester_id, semester_name, start_date, end_date
            FROM (
                SELECT semester_id, semester_name, start_date, end_date
                FROM {self.data_schema}.semester
                WHERE TO_DATE(:today, 'YYYY-MM-DD') BETWEEN start_date AND end_date
                ORDER BY start_date DESC
            )
            WHERE ROWNUM = 1
        """
        df = self._safe_read_sql(query, params={"today": today})

        if not df.empty:
            series = df.iloc[0]
            # 确保索引也是大写（_safe_read_sql 已经保证列名大写，但 iloc[0] 继承列名）
            # 实际上索引已是列名的大写形式，但为了安全再转换一次
            series.index = series.index.str.upper()
            return series

        query2 = f"""
            SELECT semester_id, semester_name, start_date, end_date
            FROM (
                SELECT semester_id, semester_name, start_date, end_date
                FROM {self.data_schema}.semester
                WHERE end_date <= TO_DATE(:today, 'YYYY-MM-DD')
                ORDER BY end_date DESC
            )
            WHERE ROWNUM = 1
        """
        df2 = self._safe_read_sql(query2, params={"today": today})

        if not df2.empty:
            series = df2.iloc[0]
            series.index = series.index.str.upper()
            return series

        return None

    def get_stats(self, semester_id: Optional[int]) -> dict:
        """加载首页统计数据"""
        stats = {}

        # 1. 在读学生总数
        df_total = self._safe_read_sql(
            f"SELECT COUNT(*) AS CNT FROM {self.data_schema}.student WHERE status = '在读'"
        )
        stats['total_students'] = df_total.iloc[0, 0]

        # 2. 本学期选课人次
        if semester_id is not None:
            df_enroll = self._safe_read_sql(
                f"SELECT COUNT(*) AS CNT FROM {self.data_schema}.student_course WHERE semester_id = :sid",
                params={"sid": semester_id}
            )
            stats['enroll_count'] = df_enroll.iloc[0, 0]
        else:
            stats['enroll_count'] = 0

        # 3. 缺勤预警人数（本学期缺勤总课时 >= 10）
        if semester_id is not None:
            df_absence = self._safe_read_sql(
                f"""SELECT COUNT(*) AS CNT FROM (
                       SELECT student_no, SUM(hours) AS total_hours
                       FROM {self.data_schema}.absence_record
                       WHERE semester_id = :sid
                       GROUP BY student_no
                       HAVING SUM(hours) >= 10
                   )""",
                params={"sid": semester_id}
            )
            stats['absence_warning'] = df_absence.iloc[0, 0]
        else:
            stats['absence_warning'] = 0

        # 4. 待补考人数
        if semester_id is not None:
            df_resit = self._safe_read_sql(
                f"""SELECT COUNT(DISTINCT sc.student_no) AS CNT
                   FROM {self.data_schema}.student_course sc
                   JOIN {self.data_schema}.score s ON sc.sc_id = s.sc_id
                   WHERE sc.semester_id = :sid
                     AND s.exam_type_code = '正考'
                     AND s.is_passed = 0""",
                params={"sid": semester_id}
            )
            stats['resit_count'] = df_resit.iloc[0, 0]
        else:
            stats['resit_count'] = 0

        return stats

    def get_college_distribution(self) -> pd.DataFrame:
        """学院人数分布（在读），返回的 DataFrame 列名为大写"""
        df = self._safe_read_sql(
            f"""SELECT c.college_name AS COLLEGE_NAME, COUNT(s.student_no) AS CNT
               FROM {self.data_schema}.student s
               JOIN {self.data_schema}.class cl ON s.class_id = cl.class_id
               JOIN {self.data_schema}.major m ON cl.major_id = m.major_id
               JOIN {self.data_schema}.college c ON m.college_id = c.college_id
               WHERE s.status = '在读'
               GROUP BY c.college_name
               ORDER BY CNT DESC"""
        )
        return df

    def get_weekly_absence(self, semester_id: Optional[int]) -> pd.DataFrame:
        """近四周缺勤趋势，返回的 DataFrame 列名为大写"""
        if semester_id is None:
            return pd.DataFrame()

        # 获取当前学期的起始和结束日期
        sem_df = self._safe_read_sql(
            f"SELECT start_date, end_date FROM {self.data_schema}.semester WHERE semester_id = :sid",
            params={"sid": semester_id}
        )
        if sem_df.empty:
            return pd.DataFrame()

        start = sem_df.iloc[0]['START_DATE']
        end = sem_df.iloc[0]['END_DATE']

        if hasattr(start, 'date'):
            start = start.date()
        if hasattr(end, 'date'):
            end = end.date()

        today = date.today()
        four_weeks_ago = today - timedelta(weeks=4)
        range_start = max(four_weeks_ago, start)
        range_end = today

        query = f"""
            SELECT TRUNC(absence_date, 'IW') AS WEEK_START,
                   COUNT(*) AS ABSENCE_COUNT
            FROM {self.data_schema}.absence_record
            WHERE semester_id = :sid
              AND absence_date BETWEEN :start_d AND :end_d
            GROUP BY TRUNC(absence_date, 'IW')
            ORDER BY WEEK_START
        """
        df = self._safe_read_sql(
            query,
            params={"sid": semester_id, "start_d": range_start, "end_d": range_end}
        )

        if not df.empty:
            # 确保 WEEK_START 列为 datetime 类型
            df['WEEK_START'] = pd.to_datetime(df['WEEK_START'])
        return df

    def get_score_distribution(self, semester_id: Optional[int]) -> pd.DataFrame:
        """成绩分布（当前学期正考成绩），返回的 DataFrame 列名为大写"""
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
                END AS GRADE,
                COUNT(*) AS CNT
            FROM {self.data_schema}.score s
            JOIN {self.data_schema}.student_course sc ON s.sc_id = sc.sc_id
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
            ORDER BY GRADE
        """
        df = self._safe_read_sql(query, params={"sid": semester_id})

        if not df.empty:
            # 确保等级顺序
            order = ['优', '良', '中', '及格', '不及格']
            df['GRADE'] = pd.Categorical(df['GRADE'], categories=order, ordered=True)
            df = df.sort_values('GRADE')
        return df