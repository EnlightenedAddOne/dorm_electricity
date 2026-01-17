# 定时任务与周报统计实现入口
# 依赖：pip install apscheduler
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from power_db import get_db
from config import Config, logger
import time
import threading

scheduler = BackgroundScheduler()

# ========== 每日消耗统计 ==========
def calc_daily_power():
    """统计前一天每个source的电量消耗，写入power_daily表"""
    conn = get_db()
    try:
        # 统计所有source、所有房间
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        sql = '''
        SELECT source, room,
            MAX(remain_power) as max_power,
            MIN(remain_power) as min_power
        FROM power_log
        WHERE date = ?
        GROUP BY source, room
        '''
        for row in conn.execute(sql, (yesterday,)):
            source, room, max_power, min_power = row['source'], row['room'], row['max_power'], row['min_power']
            if max_power is not None and min_power is not None:
                consume = max_power - min_power
                # 写入/更新power_daily
                conn.execute('''
                    INSERT INTO power_daily (source, date, consume_power)
                    VALUES (?, ?, ?)
                ''', (source, yesterday, consume))
        conn.commit()
    except Exception as e:
        logger.error(f"[power_daily] 统计失败: {e}")
    finally:
        conn.close()

# ========== 周报邮件任务 ==========
def send_weekly_report():
    """每周一10:00发送上周电量消耗周报邮件"""
    cfg = Config()
    conn = get_db()
    try:
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday()+7)  # 上周一
        week_end = week_start + timedelta(days=6)               # 上周日
        week_dates = [(week_start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7)]
        # 查询所有source
        sources = set([row['source'] for row in conn.execute('SELECT DISTINCT source FROM power_daily')])
        for source in sources:
            # 查询一周消耗
            rows = list(conn.execute('''
                SELECT date, consume_power FROM power_daily
                WHERE source=? AND date BETWEEN ? AND ?
                ORDER BY date
            ''', (source, week_start.strftime('%Y-%m-%d'), week_end.strftime('%Y-%m-%d'))))
            daily = {r['date']: r['consume_power'] for r in rows}
            # 查询最新剩余电量
            last_remain = conn.execute('''
                SELECT remain_power FROM power_log
                WHERE source=?
                ORDER BY date DESC, time DESC LIMIT 1
            ''', (source,)).fetchone()
            remain_power = last_remain['remain_power'] if last_remain else '未知'
            # 统计
            values = [daily.get(d, 0) for d in week_dates]
            total = sum(values)
            maxv = max(values) if values else 0
            minv = min(values) if values else 0
            maxd = week_dates[values.index(maxv)] if values else ''
            mind = week_dates[values.index(minv)] if values else ''
            # 构造表格
            table = '日期      | 消耗\n' + '\n'.join([f'{d} | {daily.get(d, 0):.2f}' for d in week_dates])
            content = f'''电量周报（{week_start}~{week_end}）\n\n{table}\n\n总消耗: {total:.2f}\n最高: {maxv:.2f}（{maxd}）\n最低: {minv:.2f}（{mind}）\n当前剩余: {remain_power}'''
            # 收件人策略
            recipients = cfg.get_source_recipients(source)
            if recipients:
                cfg.send_email(f'【电量周报】{source}', content, to_override=recipients)
            else:
                logger.warning(f"[周报] 未找到source={source}的收件人")
    except Exception as e:
        logger.error(f"[周报] 发送失败: {e}")
    finally:
        conn.close()

# ========== 半年数据清理 ==========
def cleanup_history():
    conn = get_db()
    try:
        conn.execute("DELETE FROM power_log WHERE date < date('now', '-180 days')")
        conn.execute("DELETE FROM power_daily WHERE date < date('now', '-180 days')")
        conn.commit()
    except Exception as e:
        logger.error(f"[清理] 失败: {e}")
    finally:
        conn.close()

# ========== 定时任务注册 ==========
def start_schedules():
    # 每天0:10统计昨日消耗
    scheduler.add_job(calc_daily_power, 'cron', hour=0, minute=10)
    # 每周一10:00发周报
    scheduler.add_job(send_weekly_report, 'cron', day_of_week='mon', hour=10, minute=0)
    # 每天1:00清理历史
    scheduler.add_job(cleanup_history, 'cron', hour=1, minute=0)
    scheduler.start()

# ========== 启动入口 ==========
if __name__ == '__main__':
    start_schedules()
    logger.info('定时任务已启动，按Ctrl+C退出')
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown()
        logger.info('定时任务已停止')
