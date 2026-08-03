import sys
import os
import re
import asyncio
import aiohttp
from urllib.parse import urlparse

async def fetch_m3u(url):
    """异步下载并解析 M3U 文件"""
    print(f"[*] 正在下载并解析播放源文件: {url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    print(f"[!] 下载失败，HTTP 状态码: {response.status}")
                    return []
                content = await response.text()
    except Exception as e:
        print(f"[!] 请求出错: {e}")
        return []

    lines = content.splitlines()
    channels = []
    current_name = "未知频道"

    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            match = re.search(r',(.+)$', line)
            if match:
                current_name = match.group(1).strip()
        elif line and not line.startswith("#"):
            parsed_url = urlparse(line)
            ip_or_domain = parsed_url.hostname or "unknown_ip"
            channels.append({
                "name": current_name,
                "url": line,
                "ip": ip_or_domain
            })
    
    print(f"[*] 成功解析出 {len(channels)} 个播放源。\n" + "="*60)
    return channels

async def test_and_print_stream(ch, semaphore, index, total):
    """测试单个源并实时打印结果"""
    url = ch["url"]
    name = ch["name"]
    ip = ch["ip"]

    cmd = [
        "ffmpeg",
        "-y",
        "-timeout", "5000000",
        "-i", url,
        "-t", "2",
        "-f", "null",
        "-"
    ]

    async with semaphore:
        print(f"[{index}/{total}] 开始测试 -> IP: {ip} | 频道: {name}")
        start_time = asyncio.get_event_loop().time()
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=7)
            duration = asyncio.get_event_loop().time() - start_time

            if process.returncode == 0:
                err_output = stderr.decode('utf-8', errors='ignore')
                resolution = "未知分辨率"
                res_match = re.search(r'(\d{3,4}x\d{3,4})', err_output)
                if res_match:
                    resolution = res_match.group(1)
                
                print(f"  └─ ✔ 【可用】耗时: {duration:.2f}s | 分辨率: {resolution} | 频道: {name}")
            else:
                print(f"  └─ ✖ 【不可用】拉流失败 | 频道: {name}")
        except asyncio.TimeoutError:
            print(f"  └─ ⌛ 【超时】响应过慢 | 频道: {name}")
        except Exception as e:
            print(f"  └─ ⚠ 【错误】{e} | 频道: {name}")

async def main():
    if len(sys.argv) < 2:
        print("错误: 请指定 M3U 播放源网址。")
        return

    target_url = sys.argv[1]
    print(f"=== IPTV 本地实时测速程序启动 ===")
    
    channels = await fetch_m3u(target_url)
    if not channels:
        return

    # 限制同时并发 5 个，避免瞬间打满 CPU 或本地带宽
    semaphore = asyncio.Semaphore(5)
    total = len(channels)

    # 创建所有任务并并发执行，每个任务完成后会立刻在屏幕滚动输出
    tasks = [test_and_print_stream(ch, semaphore, i+1, total) for i, ch in enumerate(channels)]
    await asyncio.gather(*tasks)

    print("\n" + "="*60)
    print(" 所有播放源实时测试完成！")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
