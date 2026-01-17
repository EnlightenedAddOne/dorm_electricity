-- Active: 1768659184794@@127.0.0.1@3306
-- SQLite表结构设计
-- 1. 电量抓取日志表
CREATE TABLE IF NOT EXISTS power_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    date TEXT NOT NULL,         -- 格式: YYYY-MM-DD
    time TEXT NOT NULL,         -- 格式: HH:MM:SS
    remain_power REAL NOT NULL
);

-- 2. 每日消耗统计表
CREATE TABLE IF NOT EXISTS power_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    date TEXT NOT NULL,         -- 格式: YYYY-MM-DD
    consume_power REAL NOT NULL
);

-- 3. 半年数据清理建议
-- 可定期执行: DELETE FROM power_log WHERE date < date('now', '-180 days');
--             DELETE FROM power_daily WHERE date < date('now', '-180 days');
