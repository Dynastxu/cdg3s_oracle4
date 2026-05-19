import streamlit as st
import plotly.express as px
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

        # ---------- 图表区域 ----------
    st.markdown("---")
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("学院人数分布")
        if not college_df.empty:
            fig1 = px.bar(college_df, x='COLLEGE_NAME', y='CNT',
                          labels={'COLLEGE_NAME': '学院', 'CNT': '人数'},
                          color='CNT', color_continuous_scale='Blues')
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("暂无学院数据")

    with col_right:
        st.subheader("当前学期成绩分布（正考）")
        if not score_dist.empty:
            fig2 = px.pie(score_dist, values='CNT', names='GRADE',
                          color='GRADE',
                          color_discrete_map={
                              '优': '#2ca02c', '良': '#98df8a',
                              '中': '#ffbb78', '及格': '#ff7f0e',
                              '不及格': '#d62728'
                          })
            fig2.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("暂无成绩数据")

    st.markdown("---")
    st.subheader("近四周缺勤趋势")
    if not weekly_abs.empty:
        fig3 = px.line(weekly_abs, x='WEEK_START', y='ABSENCE_COUNT',
                       labels={'WEEK_START': '周起始日', 'ABSENCE_COUNT': '缺勤人次'},
                       markers=True)
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("近四周无缺勤记录")

    # ---------- 快捷操作 ----------
    st.markdown("---")
    st.subheader("快捷操作")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("➕ 新增学生", use_container_width=True):
            st.switch_page("pages/1_学生信息.py")  # 后续页面自行创建
    with col2:
        if st.button("📝 登记缺勤", use_container_width=True):
            st.switch_page("pages/2_缺勤登记.py")
    with col3:
        if st.button("📊 录入成绩", use_container_width=True):
            st.switch_page("pages/3_成绩录入.py")
    with col4:
        if st.button("📋 查看报表", use_container_width=True):
            st.switch_page("pages/4_统计报表.py")

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