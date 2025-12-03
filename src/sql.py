import asyncio
import argparse
import sys
from pathlib import Path

# 将项目根目录添加到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from src.database import _get_db_url


async def execute_sql(sql_statement: str, skip_confirm: bool = False):
    """
    执行传入的SQL语句。
    """
    # 1. 设置数据库连接
    try:
        db_url = _get_db_url()
    except ValueError as e:
        print(f"❌ {e}")
        return

    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # 2. 显示SQL预览
    print("\n" + "=" * 60)
    print("📋 将要执行的SQL语句:")
    print("-" * 60)
    print(sql_statement)
    print("-" * 60)

    # 3. 确认执行
    if not skip_confirm:
        confirm = input("\n⚠️  确认执行此SQL吗? (输入 'yes' 确认): ")
        if confirm.lower() != 'yes':
            print("❌ 已取消执行。")
            await engine.dispose()
            return

    # 4. 执行SQL
    async with session_factory() as session:
        try:
            result = await session.execute(text(sql_statement))
            
            # 判断是否是SELECT语句
            sql_upper = sql_statement.strip().upper()
            if sql_upper.startswith("SELECT"):
                # SELECT语句：显示查询结果
                rows = result.fetchall()
                columns = result.keys()
                
                print("\n" + "=" * 60)
                print("✅ 查询成功!")
                print(f"   返回行数: {len(rows)}")
                print("=" * 60)
                
                if rows:
                    # 打印列名
                    print("\n" + " | ".join(str(col) for col in columns))
                    print("-" * 60)
                    # 打印数据（最多显示50行）
                    for i, row in enumerate(rows[:50]):
                        print(" | ".join(str(val) for val in row))
                    if len(rows) > 50:
                        print(f"\n... 还有 {len(rows) - 50} 行未显示")
                else:
                    print("\n(无数据)")
            else:
                # 非SELECT语句：提交并显示影响行数
                await session.commit()
                print("\n" + "=" * 60)
                print("✅ 执行成功!")
                print(f"   影响行数: {result.rowcount}")
                print("=" * 60)
                
        except Exception as e:
            print("\n" + "=" * 60)
            print("❌ 执行失败!")
            print(f"   错误: {e}")
            print("=" * 60)
            await session.rollback()

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="执行SQL语句。",
        epilog="示例: python src/sql.py \"SELECT * FROM anime LIMIT 10\""
    )
    parser.add_argument("sql", help="要执行的SQL语句")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过确认提示（危险操作，请谨慎使用）"
    )
    args = parser.parse_args()
    
    asyncio.run(execute_sql(args.sql, args.yes))


if __name__ == "__main__":
    main()

