"""
清除登录锁定工具

用于管理员被暴力破解防护锁定时的紧急解锁：
  python -m src.reset_login_lockout                    # 查看当前锁定状态
  python -m src.reset_login_lockout --clear             # 清除所有 IP 锁定
  python -m src.reset_login_lockout --clear --ip x.x.x  # 清除指定 IP 锁定
  python -m src.reset_login_lockout --port 8080          # 指定服务端口

注意：此工具需要服务正在运行（通过 API 操作内存数据）。
      如果服务已停止，直接重启即可清除所有锁定。
"""

import argparse
import json
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def main():
    parser = argparse.ArgumentParser(
        description="清除登录暴力破解防护的 IP 锁定。"
    )
    parser.add_argument("--clear", action="store_true", help="执行清除操作（不传则仅查看状态）")
    parser.add_argument("--ip", type=str, default=None, help="指定要清除的 IP（不传则清除全部）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="服务地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=7768, help="服务端口（默认 7768）")
    parser.add_argument("--token", type=str, default=None, help="JWT Token（可选，白名单 IP 无需提供）")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}/api/ui/auth/login-lockout"
    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    if args.clear:
        # 清除锁定
        url = base_url
        if args.ip:
            url += f"?ip={args.ip}"
        req = Request(url, method="DELETE", headers=headers)
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                print("\n" + "=" * 50)
                print(f"✅ {data.get('message', '操作完成')}")
                print(f"   清除数量: {data.get('cleared', 0)}")
                print("=" * 50)
        except HTTPError as e:
            body = e.read().decode()
            if e.code == 401:
                print("❌ 认证失败。请使用 --token 参数传入有效的 JWT Token，或确保从白名单 IP 访问。")
            else:
                print(f"❌ 请求失败 (HTTP {e.code}): {body}")
            sys.exit(1)
        except URLError as e:
            print(f"❌ 无法连接到服务 {base_url}: {e.reason}")
            print("   提示：如果服务未运行，直接重启服务即可清除所有登录锁定。")
            sys.exit(1)
    else:
        # 查看状态
        req = Request(base_url, method="GET", headers=headers)
        try:
            with urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                locked_ips = data.get("lockedIps", [])
                total = data.get("total", 0)
                print("\n" + "=" * 50)
                print(f"📊 当前登录锁定状态（共 {total} 条）")
                print("=" * 50)
                if not locked_ips:
                    print("   无锁定记录。")
                else:
                    for item in locked_ips:
                        elapsed_min = item['elapsedSeconds'] // 60
                        elapsed_sec = item['elapsedSeconds'] % 60
                        print(f"   IP: {item['ip']}")
                        print(f"      失败次数: {item['failCount']}")
                        print(f"      已过时间: {elapsed_min}分{elapsed_sec}秒")
                        print()
                print("提示：使用 --clear 参数执行清除操作。")
                print("      使用 --clear --ip x.x.x.x 清除指定 IP。")
        except HTTPError as e:
            if e.code == 401:
                print("❌ 认证失败。请使用 --token 参数传入有效的 JWT Token，或确保从白名单 IP 访问。")
            else:
                body = e.read().decode()
                print(f"❌ 请求失败 (HTTP {e.code}): {body}")
            sys.exit(1)
        except URLError as e:
            print(f"❌ 无法连接到服务 {base_url}: {e.reason}")
            print("   提示：如果服务未运行，直接重启服务即可清除所有登录锁定。")
            sys.exit(1)


if __name__ == "__main__":
    main()
