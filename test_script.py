import sys
import os
import re
import asyncio
import aiohttp
from urllib.parse import urlparse

async def fetch_m3u(url):
    """异步下载并解析 M3U 文件"""
    print(f"正在下载并解析播放源文件: {url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    print(f"下载失败，HTTP 状态码: {response.status}")
                    return []
                content = await response.text()
    except Exception as e:
        print(f"请求出错: {e}")
        return []

    # 解析 M3U 文件
    lines = content.splitlines()
    channels = []
    current_name = "未知频道"

    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            # 提取频道名称
            match = re.search(r',(.+)$', line)
            if match:
                current_name = match.group(1).strip()
        elif line and not line.startswith("#"):
            # 这是一个播放链接
            parsed_url = urlparse(line)
            ip_or_domain = parsed_url.hostname or "unknown_ip"
            channels.append({
                "name": current_name,
                "url": line,
                "ip": ip_or_domain
            })
    
    print(f"成功解析出 {len(channels)} 个播放源。")
    return channels

async def test_stream_with_ffmpeg(channel, timeout=5):
    """利用 ffmpeg 测试单个源的拉流和播放质量"""
    url = channel["url"]
    name = channel["name"]
    ip = channel["ip"]

    # 使用 ffmpeg 尝试拉取 2 秒钟的数据，限制超时时间
    # -i 输入, -t 持续时间, -vframes 收集帧数, -f null 丢弃输出只测解码
    cmd = [
        "ffmpeg",
        "-y",
        "-timeout", str(timeout * 1000000),  # ffmpeg 的微秒级超时设置
        "-i", url,
        "-t", "2",
        "-f", "null",
        "-"
    ]

    start_time = asyncio.get_event_loop().time()
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout + 2)
        
        duration = asyncio.get_event_loop().time() - start_time
        
        if process.returncode == 0:
            # 提取分辨率或码率等特征（从 stderr 中简单判断）
            err_output = stderr.decode('utf-8', errors='ignore')
            resolution = "未知分辨率"
            res_match = re.search(r'(\d{3,4}x\d{3,4})', err_output)
            if res_match:
                resolution = res_match.group(1)
            
            return {
                "name": name,
                "url": url,
                "ip": ip,
                "status": "可用",
                "latency": round(duration, 2),
                "resolution": resolution
            }
        else:
            return {
                "name": name,
                "url": url,
                "ip": ip,
                "status": "不可用 (拉流失败)",
                "latency": -1,
                "resolution": "-"
            }
    except asyncio.TimeoutError:
        return {
            "name": name,
            "url": url,
            "ip": ip,
            "status": "超时 (响应慢)",
            "latency": -1,
            "resolution": "-"
        }
    except Exception as e:
        return {
            "name": name,
            "url": url,
            "ip": ip,
            "status": f"错误: {str(e)}",
            "latency": -1,
            "resolution": "-"
        }

async def main():
    if len(sys.argv) < 2:
        print("错误: 请指定 M3U 播放源网址。")
        return

    target_url = sys.argv[1]
    print(f"=== IPTV 本地测速程序启动 ===")
    
    channels = await fetch_m3u(target_url)
    if not channels:
        print("没有找到有效的播放源。")
        return

    # 为了防止瞬间并发过大压垮网络或被源服务器封禁，限制同时测试 5 个通道
    semaphore = asyncio.Semaphore(5)

    async def bounded_test(ch):
        async with semaphore:
            print(f"正在测试: [{ch['ip']}] {ch['name']} ...")
            return await test_stream_with_ffmpeg(ch)

    print("\n开始进行本地网络连通与解码测试（并发中）...")
    results = await asyncio.gather(*(bounded_test(ch) for ch in channels))

    # 按 IP 分类整理结果
    ip_groups = {}
    for res in results:
        ip = res["ip"]
        if ip not in ip_groups:
            ip_groups[ip] = []
        ip_groups[ip].append(res)

    print("\n" + "="*40)
    print(" 测 速 结 果 统 计 (按 IP 分类) ")
    print("="*40)

    for ip, items in ip_groups.items():
        print(f"\n【IP / 域名: {ip}】 (共 {len(items)} 个源)")
        print("-" * 60)
        for item in items:
            print(f"  频道: {item['name']}")
            print(f"  状态: {item['status']} | 耗时: {item['latency']}s | 分辨率: {item['resolution']}")
            print(f"  链接: {item['url']}")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
