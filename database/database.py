import os
from datetime import date, timedelta
from typing import Optional
import oracledb
import pandas as pd
from dotenv import load_dotenv


class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        load_dotenv()
        self.data_schema = os.getenv("DATA_SCHEMA_NAME")
        self.conn = None

    def init_connection(self):
        """初始化数据库连接"""
        oracledb.init_oracle_client(
            lib_dir=os.getenv("INSTANT_CLIENT_DIR")
        )
        self.conn = oracledb.connect(
            user=os.getenv("ORACLE_USER"),
            password=os.getenv("ORACLE_PASSWORD"),
            dsn=os.getenv("ORACLE_DSN")
        )
        return self.conn

    def get_connection(self):
        """获取数据库连接"""
        if self.conn is None:
            self.init_connection()
        return self.conn

    def close_connection(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def get_current_semester(self) -> Optional[pd.Series]:
        """根据当前日期查找所在学期，若无则返回最新学期"""
        conn = self.get_connection()
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
        df = pd.read_sql(query, conn, params={"today": today})

        if not df.empty:
            return df.iloc[0]

        # 如果当前日期不在任何学期内，取最近结束的学期
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
        df2 = pd.read_sql(query2, conn, params={"today": today})

        if not df2.empty:
            return df2.iloc[0]

        return None

    def get_stats(self, semester_id: Optional[int]) -> dict:
        """加载首页统计数据"""
        conn = self.get_connection()

        # 1. 在读学生总数
        stats = {'total_students': pd.read_sql(
            f"SELECT COUNT(*) AS CNT FROM {self.data_schema}.student WHERE status = '在读'",
            conn
        ).iloc[0, 0]}

        # 2. 本学期选课人次
        if semester_id is not None:
            stats['enroll_count'] = pd.read_sql(
                f"SELECT COUNT(*) FROM {self.data_schema}.student_course WHERE semester_id = :sid",
                conn, params={"sid": semester_id}
            ).iloc[0, 0]
        else:
            stats['enroll_count'] = 0

        # 3. 缺勤预警人数（本学期缺勤总课时 >= 10）
        if semester_id is not None:
            stats['absence_warning'] = pd.read_sql(
                f"""SELECT COUNT(*) FROM (
                       SELECT student_no, SUM(hours) AS total_hours
                       FROM {self.data_schema}.absence_record
                       WHERE semester_id = :sid
                       GROUP BY student_no
                       HAVING SUM(hours) >= 10
                   )""",
                conn, params={"sid": semester_id}
            ).iloc[0, 0]
        else:
            stats['absence_warning'] = 0

        # 4. 待补考人数（正考未通过且考试类型为正考，关联当前学期选课）
        if semester_id is not None:
            stats['resit_count'] = pd.read_sql(
                f"""SELECT COUNT(DISTINCT sc.student_no)
                   FROM {self.data_schema}.student_course sc
                   JOIN {self.data_schema}.score s ON sc.sc_id = s.sc_id
                   WHERE sc.semester_id = :sid
                     AND s.exam_type_code = '正考'
                     AND s.is_passed = 0""",
                conn, params={"sid": semester_id}
            ).iloc[0, 0]
        else:
            stats['resit_count'] = 0

        return stats

    def get_college_distribution(self) -> pd.DataFrame:
        """学院人数分布（在读）"""
        conn = self.get_connection()
        df = pd.read_sql(
            f"""SELECT c.college_name, COUNT(s.student_no) AS cnt
               FROM {self.data_schema}.student s
               JOIN {self.data_schema}.class cl ON s.class_id = cl.class_id
               JOIN {self.data_schema}.major m ON cl.major_id = m.major_id
               JOIN {self.data_schema}.college c ON m.college_id = c.college_id
               WHERE s.status = '在读'
               GROUP BY c.college_name
               ORDER BY cnt DESC""",
            conn
        )
        return df

    def get_weekly_absence(self, semester_id: Optional[int]) -> pd.DataFrame:
        """近四周缺勤趋势"""
        if semester_id is None:
            return pd.DataFrame()

        conn = self.get_connection()

        # 获取当前学期的起始和结束日期
        sem_info = pd.read_sql(
            f"SELECT start_date, end_date FROM {self.data_schema}.semester WHERE semester_id = :sid",
            conn, params={"sid": semester_id}
        ).iloc[0]

        start = sem_info['START_DATE']
        end = sem_info['END_DATE']

        # 将数据库返回的 Timestamp 转换为 date 对象
        if hasattr(start, 'date'):
            start = start.date()
        if hasattr(end, 'date'):
            end = end.date()

        # 计算近四周的日期范围：从今天往前推4周，但不得早于学期开始
        today = date.today()
        four_weeks_ago = today - timedelta(weeks=4)
        range_start = max(four_weeks_ago, start)
        range_end = today

        query = f"""
            SELECT TRUNC(absence_date, 'IW') AS week_start,
                   COUNT(*) AS absence_count
            FROM {self.data_schema}.absence_record
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

    def get_score_distribution(self, semester_id: Optional[int]) -> pd.DataFrame:
        """成绩分布（当前学期正考成绩）"""
        if semester_id is None:
            return pd.DataFrame()

        conn = self.get_connection()

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
            ORDER BY grade
        """
        df = pd.read_sql(query, conn, params={"sid": semester_id})

        # 确保顺序
        order = ['优', '良', '中', '及格', '不及格']
        df['grade'] = pd.Categorical(df['GRADE'], categories=order, ordered=True)
        df = df.sort_values('grade')

        return df