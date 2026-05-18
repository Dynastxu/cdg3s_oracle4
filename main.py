import streamlit as st
from database.database import DatabaseManager

db_manager = DatabaseManager()


@st.cache_resource
def get_db_manager():
    """获取数据库管理器实例"""
    db_manager.init_connection()
    return db_manager


@st.cache_data(ttl=600)
def load_stats(semester_id):
    """加载首页统计数据"""
    return db_manager.get_stats(semester_id)


@st.cache_data(ttl=600)
def load_college_distribution():
    """学院人数分布（在读）"""
    return db_manager.get_college_distribution()


@st.cache_data(ttl=600)
def load_weekly_absence(semester_id):
    """近四周缺勤趋势"""
    return db_manager.get_weekly_absence(semester_id)


@st.cache_data(ttl=600)
def load_score_distribution(semester_id):
    """成绩分布（当前学期正考成绩）"""
    return db_manager.get_score_distribution(semester_id)


def render_main_page():
    """渲染主页面"""
    st.title("🎓 学生管理信息系统")
    st.markdown("欢迎使用学生管理信息系统，以下为实时数据概览。")

    # 获取当前学期
    current_sem = db_manager.get_current_semester()
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


def main():
    """主函数"""
    # 页面配置
    st.set_page_config(
        page_title="学生管理信息系统",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 初始化数据库连接
    get_db_manager()

    # 渲染页面
    render_main_page()

if __name__ == "__main__":
    main()