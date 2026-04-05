"""
Misaka SQL 交互式控制台

支持三种运行模式:
  1. 交互式 REPL:  python src/sql.py
  2. 单条执行:      python src/sql.py "SELECT * FROM anime LIMIT 5"
  3. 文件批量执行:  python src/sql.py --file script.sql
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path
from typing import List, Sequence

# 将项目根目录添加到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text, inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine

from src.db import _get_db_url
from src.core.config import settings

# ── 危险 SQL 关键词 ──
_DANGEROUS_KEYWORDS = ("DROP", "TRUNCATE", "ALTER", "DELETE FROM", "UPDATE ")


# ═══════════════════════════════════════════════════════════
# 表格格式化
# ═══════════════════════════════════════════════════════════

def _format_table(columns: Sequence[str], rows: Sequence[Sequence], max_rows: int = 100) -> str:
    """将列名和数据行格式化为对齐的 ASCII 表格（纯内置，无依赖）。"""
    if not columns:
        return "(无数据)"

    # 计算每列最大宽度（列名 vs 数据），限制最大列宽60
    display_rows = rows[:max_rows]
    col_widths = [len(str(c)) for c in columns]
    for row in display_rows:
        for i, val in enumerate(row):
            col_widths[i] = min(max(col_widths[i], len(str(val))), 60)

    # 构造分隔线和格式串
    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in col_widths) + " |"

    lines = [sep]
    lines.append(fmt.format(*(str(c)[:w] for c, w in zip(columns, col_widths))))
    lines.append(sep)
    for row in display_rows:
        lines.append(fmt.format(*(str(v)[:w] for v, w in zip(row, col_widths))))
    lines.append(sep)

    if len(rows) > max_rows:
        lines.append(f"  ... 还有 {len(rows) - max_rows} 行未显示 (共 {len(rows)} 行)")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 核心 SQL 执行器
# ═══════════════════════════════════════════════════════════

class SqlConsole:
    """SQL 交互式控制台"""

    BUILTIN_COMMANDS = {
        "\\q":     "退出",
        "\\dt":    "列出所有表",
        "\\d 表名": "查看表结构",
        "\\count 表名": "统计表行数",
        "\\size":  "查看数据库大小",
        "\\h":     "显示帮助",
    }

    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self.db_type = settings.database.type.lower()
        self._table_names: List[str] = []
        self._column_cache: dict = {}  # table_name -> [col_names]

    # ── 初始化 ──

    async def init(self):
        """预加载表名和列名，用于 Tab 补全。"""
        try:
            async with self.engine.connect() as conn:
                def _inspect(sync_conn):
                    insp = sa_inspect(sync_conn)
                    tables = insp.get_table_names()
                    cols = {}
                    for t in tables:
                        try:
                            cols[t] = [c["name"] for c in insp.get_columns(t)]
                        except Exception:
                            cols[t] = []
                    return tables, cols
                self._table_names, self._column_cache = await conn.run_sync(_inspect)
        except Exception:
            pass  # 补全数据获取失败不影响正常使用

    def _print_banner(self):
        """打印欢迎信息。"""
        db_host = settings.database.host
        db_port = settings.database.port
        db_name = settings.database.name
        print(f"\n{'═' * 55}")
        print(f"  Misaka SQL Console")
        print(f"  数据库: {self.db_type} @ {db_host}:{db_port}/{db_name}")
        print(f"  输入 SQL 语句执行，\\h 查看帮助，\\q 退出")
        print(f"{'═' * 55}\n")

    # ── Tab 补全 ──

    def _setup_completer(self):
        """设置 readline Tab 补全。"""
        try:
            if sys.platform == "win32":
                try:
                    import pyreadline3 as readline  # noqa: F811
                except ImportError:
                    return  # Windows 无 readline 也不影响使用
            else:
                import readline

            sql_keywords = [
                "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
                "DELETE", "CREATE", "DROP", "ALTER", "TABLE", "INDEX", "AND", "OR", "NOT",
                "IN", "LIKE", "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET", "JOIN",
                "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AS", "DISTINCT", "COUNT", "SUM",
                "AVG", "MAX", "MIN", "DESC", "ASC", "NULL", "IS", "BETWEEN", "EXISTS",
                "CASE", "WHEN", "THEN", "ELSE", "END", "UNION", "ALL", "TRUNCATE",
            ]
            builtin_cmds = list(self.BUILTIN_COMMANDS.keys())
            all_words = sql_keywords + [k.lower() for k in sql_keywords] + \
                         self._table_names + builtin_cmds
            # 加入列名
            for cols in self._column_cache.values():
                all_words.extend(cols)

            def completer(text, state):
                matches = [w for w in all_words if w.startswith(text)]
                return matches[state] if state < len(matches) else None

            readline.set_completer(completer)
            readline.set_completer_delims(" \t\n;,()")
            readline.parse_and_bind("tab: complete")
        except Exception:
            pass  # 补全不可用不影响核心功能

    # ── 内置快捷命令 ──

    async def _cmd_tables(self):
        """\\dt — 列出所有表及行数"""
        async with self.session_factory() as session:
            rows = []
            for t in sorted(self._table_names):
                try:
                    r = await session.execute(text(f'SELECT COUNT(*) FROM "{t}"'))
                    cnt = r.scalar()
                except Exception:
                    cnt = "?"
                rows.append((t, cnt))
        print(_format_table(["表名", "行数"], rows))

    async def _cmd_describe(self, table_name: str):
        """\\d 表名 — 查看表结构"""
        if table_name not in self._table_names:
            print(f"❌ 表 '{table_name}' 不存在")
            return
        try:
            async with self.engine.connect() as conn:
                def _get_cols(sync_conn):
                    insp = sa_inspect(sync_conn)
                    return insp.get_columns(table_name)
                col_infos = await conn.run_sync(_get_cols)
        except Exception as e:
            print(f"❌ 获取表结构失败: {e}")
            return
        rows = []
        for c in col_infos:
            nullable = "YES" if c.get("nullable", True) else "NO"
            default = str(c.get("default", "")) if c.get("default") is not None else ""
            rows.append((c["name"], str(c["type"]), nullable, default))
        print(f"\n📋 表 {table_name} 的结构:")
        print(_format_table(["列名", "类型", "可空", "默认值"], rows))

    async def _cmd_count(self, table_name: str):
        """\\count 表名 — 统计行数"""
        if table_name not in self._table_names:
            print(f"❌ 表 '{table_name}' 不存在")
            return
        async with self.session_factory() as session:
            r = await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            cnt = r.scalar()
        print(f"  表 {table_name}: {cnt} 行")

    async def _cmd_size(self):
        """\\size — 查看数据库大小"""
        async with self.session_factory() as session:
            try:
                if self.db_type == "postgresql":
                    r = await session.execute(text(
                        f"SELECT pg_size_pretty(pg_database_size('{settings.database.name}'))"
                    ))
                    size = r.scalar()
                elif self.db_type == "mysql":
                    r = await session.execute(text(
                        f"SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) "
                        f"FROM information_schema.TABLES WHERE table_schema = '{settings.database.name}'"
                    ))
                    size = f"{r.scalar()} MB"
                else:
                    size = "不支持"
                print(f"  数据库大小: {size}")
            except Exception as e:
                print(f"❌ 获取大小失败: {e}")

    def _cmd_help(self):
        """\\h — 显示帮助"""
        print("\n📖 可用命令:")
        print("-" * 40)
        for cmd, desc in self.BUILTIN_COMMANDS.items():
            print(f"  {cmd:<16} {desc}")
        print(f"  {'SQL语句':<16} 直接输入 SQL 执行")
        print(f"  {'Tab':<16} 自动补全")
        print()

    # ── SQL 执行 ──

    async def execute(self, sql: str, skip_confirm: bool = False) -> bool:
        """执行一条 SQL 语句。"""
        sql = sql.strip().rstrip(";")
        if not sql:
            return True
        sql_upper = sql.upper().lstrip()
        is_select = sql_upper.startswith(("SELECT", "SHOW", "EXPLAIN"))
        is_dangerous = any(sql_upper.startswith(k) for k in _DANGEROUS_KEYWORDS)

        if not skip_confirm and not is_select:
            if is_dangerous:
                print(f"  ⚠️  危险操作: {sql[:60]}...")
                confirm = input("  输入 'yes' 确认执行: ")
                if confirm.lower() != "yes":
                    print("  ❌ 已取消")
                    return True
            else:
                confirm = input("  确认执行? (y/N): ")
                if confirm.lower() not in ("y", "yes"):
                    print("  ❌ 已取消")
                    return True

        t0 = time.time()
        async with self.session_factory() as session:
            try:
                result = await session.execute(text(sql))
                elapsed = time.time() - t0
                if is_select:
                    rows = result.fetchall()
                    columns = list(result.keys())
                    print(_format_table(columns, rows))
                    print(f"  ({len(rows)} 行, 耗时 {elapsed:.3f}s)")
                else:
                    await session.commit()
                    print(f"  ✅ 执行成功 (影响 {result.rowcount} 行, 耗时 {elapsed:.3f}s)")
            except Exception as e:
                print(f"  ❌ 执行失败: {e}")
                await session.rollback()
        return True

    # ── REPL 主循环 ──

    async def repl(self):
        """交互式 REPL 循环。"""
        self._print_banner()
        self._setup_completer()
        while True:
            try:
                line = input("sql> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n👋 再见!")
                break
            if not line:
                continue
            if line == "\\q" or line.lower() == "exit":
                print("👋 再见!")
                break
            elif line == "\\dt":
                await self._cmd_tables()
            elif line.startswith("\\d "):
                await self._cmd_describe(line[3:].strip())
            elif line.startswith("\\count "):
                await self._cmd_count(line[7:].strip())
            elif line == "\\size":
                await self._cmd_size()
            elif line in ("\\h", "\\help"):
                self._cmd_help()
            elif line.startswith("\\"):
                print(f"  未知命令: {line} (输入 \\h 查看帮助)")
            else:
                await self.execute(line)

    # ── 文件批量执行 ──

    async def execute_file(self, filepath: str, skip_confirm: bool = False):
        """从文件读取并逐条执行 SQL。"""
        path = Path(filepath)
        if not path.exists():
            print(f"❌ 文件不存在: {filepath}")
            return
        content = path.read_text(encoding="utf-8")
        statements = [s.strip() for s in content.split(";") if s.strip()]
        print(f"\n📄 从文件 {path.name} 中读取到 {len(statements)} 条 SQL")
        if not skip_confirm:
            confirm = input("  确认逐条执行? (y/N): ")
            if confirm.lower() not in ("y", "yes"):
                print("  ❌ 已取消")
                return
        for i, stmt in enumerate(statements, 1):
            print(f"\n── [{i}/{len(statements)}] ──")
            print(f"  {stmt[:80]}{'...' if len(stmt) > 80 else ''}")
            await self.execute(stmt, skip_confirm=True)



# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════

async def _main(args):
    try:
        db_url = _get_db_url()
    except ValueError as e:
        print(f"❌ {e}")
        return

    engine = create_async_engine(db_url, echo=False)
    console = SqlConsole(engine)
    await console.init()

    try:
        if args.file:
            await console.execute_file(args.file, skip_confirm=args.yes)
        elif args.sql:
            await console.execute(args.sql, skip_confirm=args.yes)
        else:
            await console.repl()
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Misaka SQL 交互式控制台",
        epilog=(
            "示例:\n"
            '  python src/sql.py                                # 交互式模式\n'
            '  python src/sql.py "SELECT * FROM anime LIMIT 5"  # 单条执行\n'
            '  python src/sql.py --file script.sql              # 文件批量执行\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sql", nargs="?", default=None, help="要执行的SQL语句 (不提供则进入交互模式)")
    parser.add_argument("--file", "-f", help="从文件读取并逐条执行SQL")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认提示")
    args = parser.parse_args()

    asyncio.run(_main(args))


if __name__ == "__main__":
    main()