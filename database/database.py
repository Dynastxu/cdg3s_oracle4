import os
from datetime import date, timedelta
from typing import Optional

import oracledb
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class DatabaseManager:
    """数据库管理器（调用存储过程）"""

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

    def _call_proc_single_row(self, proc_name: str, **params) -> Optional[pd.Series]:
        """
        调用存储过程，返回第一行作为 Series（索引为大写列名）
        存储过程必须有一个 SYS_REFCURSOR 输出参数，且返回结果集最多一行。
        """
        engine = self.get_connection()
        # 构建调用语句: CALL schema.pkg.proc(:p_cursor, ...)
        # 使用 SQLAlchemy 的 text() 和 execution_options 处理 REF CURSOR
        with engine.connect() as conn:
            # 创建 REF CURSOR 变量
            cursor_var = conn.connection.cursor()
            # 调用存储过程
            # 注意：oracledb 驱动支持直接调用存储过程，但 SQLAlchemy 需要特殊处理
            # 我们使用原始连接调用
            # 构造 PL/SQL 调用块
            placeholders = []
            proc_params = []
            for name, value in params.items():
                placeholders.append(f":{name}")
                proc_params.append(value)
            proc_params.append(cursor_var)
            placeholders.append(":cur")

            call_sql = f"BEGIN {self.data_schema}.{proc_name}({','.join(placeholders)}); END;"
            # 构建参数字典
            call_params = {**params, "cur": cursor_var}

            conn.execute(text(call_sql), call_params)
            # 获取结果集
            rows = cursor_var.fetchall()
            if not rows:
                return None
            # 获取列名
            col_names = [col[0].upper() for col in cursor_var.description]
            df = pd.DataFrame(rows, columns=col_names)
            cursor_var.close()
            return df.iloc[0]

    def _call_proc_dataframe(self, proc_name: str, **params) -> pd.DataFrame:
        """
        调用存储过程，返回整个结果集 DataFrame（列名为大写）
        """
        engine = self.get_connection()
        with engine.connect() as conn:
            cursor_var = conn.connection.cursor()
            placeholders = []
            proc_params = []
            for name, value in params.items():
                placeholders.append(f":{name}")
                proc_params.append(value)
            proc_params.append(cursor_var)
            placeholders.append(":cur")

            call_sql = f"BEGIN {self.data_schema}.{proc_name}({','.join(placeholders)}); END;"
            call_params = {**params, "cur": cursor_var}

            conn.execute(text(call_sql), call_params)
            rows = cursor_var.fetchall()
            if not rows:
                return pd.DataFrame()
            col_names = [col[0].upper() for col in cursor_var.description]
            df = pd.DataFrame(rows, columns=col_names)
            cursor_var.close()
            return df

    # ---------- 业务方法 ----------
    def get_current_semester(self) -> Optional[pd.Series]:
        """获取当前学期或最近学期"""
        today = date.today()
        series = self._call_proc_single_row(
            "PKG_STUDENT_STATS.GET_CURRENT_SEMESTER",
            p_today=today
        )
        return series

    def get_stats(self, semester_id: Optional[int]) -> dict:
        """获取首页统计数据"""
        if semester_id is None:
            return {
                'total_students': 0,
                'enroll_count': 0,
                'absence_warning': 0,
                'resit_count': 0
            }
        df = self._call_proc_dataframe(
            "PKG_STUDENT_STATS.GET_STATS",
            p_semester_id=semester_id
        )
        if df.empty:
            return {}
        row = df.iloc[0]
        return {
            'total_students': int(row['TOTAL_STUDENTS']),
            'enroll_count': int(row['ENROLL_COUNT']),
            'absence_warning': int(row['ABSENCE_WARNING']),
            'resit_count': int(row['RESIT_COUNT'])
        }

    def get_college_distribution(self) -> pd.DataFrame:
        """学院人数分布"""
        return self._call_proc_dataframe("PKG_STUDENT_STATS.GET_COLLEGE_DISTRIBUTION")

    def get_weekly_absence(self, semester_id: Optional[int]) -> pd.DataFrame:
        """近四周缺勤趋势"""
        if semester_id is None:
            return pd.DataFrame()
        # 获取学期日期范围
        sem = self.get_current_semester()  # 注意：这里需要的是当前学期（传入的 semester_id 对应的学期）
        # 但 get_weekly_absence 使用的是给定的 semester_id，所以应该单独查询学期起止日期
        # 为了简单，我们可单独查询学期日期；或者修改存储过程内部自动计算四周范围。
        # 为保持原逻辑，我们在 Python 中计算起止日期并传入存储过程。
        # 先查询学期起止日期
        engine = self.get_connection()
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT start_date, end_date FROM {self.data_schema}.semester WHERE semester_id = :sid"),
                {"sid": semester_id}
            )
            row = result.fetchone()
            if not row:
                return pd.DataFrame()
            start = row[0]
            end = row[1]
        if hasattr(start, 'date'):
            start = start.date()
        if hasattr(end, 'date'):
            end = end.date()
        today = date.today()
        four_weeks_ago = today - timedelta(weeks=4)
        range_start = max(four_weeks_ago, start)
        range_end = today

        df = self._call_proc_dataframe(
            "PKG_STUDENT_STATS.GET_WEEKLY_ABSENCE",
            p_semester_id=semester_id,
            p_start_date=range_start,
            p_end_date=range_end
        )
        if not df.empty and 'WEEK_START' in df.columns:
            df['WEEK_START'] = pd.to_datetime(df['WEEK_START'])
        return df

    def get_score_distribution(self, semester_id: Optional[int]) -> pd.DataFrame:
        """成绩分布"""
        if semester_id is None:
            return pd.DataFrame()
        df = self._call_proc_dataframe(
            "PKG_STUDENT_STATS.GET_SCORE_DISTRIBUTION",
            p_semester_id=semester_id
        )
        if not df.empty:
            # 确保等级顺序
            order = ['优', '良', '中', '及格', '不及格']
            df['GRADE'] = pd.Categorical(df['GRADE'], categories=order, ordered=True)
            df = df.sort_values('GRADE')
        return df