import os
import json
import re
import sys
import time
import random
import urllib3
import requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# 1. 禁用 SSL 安全警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 性能压测配置 ---
TEST_DURATION = 15     # 每个频道样本测试 15 秒
SAMPLES_PER_IP = 3     # 每个独立 IP 随机抽取 3 个频道进行压测
MAX_WORKERS = 10       # 并行线程数

def fetch_m3u_content(url):
    """通过动态传入的 URL 实时下载并解析 M3U 内容"""
    print(f"[*] 正在动态下载 M3U 文件: {url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, timeout=15, headers=headers, verify=False)
        if response.status_code != 200:
            print(f"[!] 下载失败，HTTP 状态码: {response.status_code}")
            return None
        return response.text
    except Exception as e:
        print(f"[!] 请求出错: {e}")
        return None

def test_stream_traffic(name, url):
    """模拟真实播放并统计下行流量，纯粹计算 Mbps 码率，不检测分辨率"""
    ip_port = urlparse(url).netloc
    start_time = time.time()
    total_bytes = 0
    speeds_mbps = []
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    try:
        r = requests.get(url, timeout=5, headers=headers, verify=False)
        if r.status_code != 200: return None
        
        base_dir = url.rsplit('/', 1)[0]
        ts_lines = [line.strip() for line in r.text.split('\n') if line.strip() and not line.startswith('#')]
        if not ts_lines: return None

        # 采样部分 TS 片段进行带宽压测
        while time.time() - start_time < TEST_DURATION:
            target_ts = ts_lines[-2:] if len(ts_lines) > 2 else ts_lines
            for ts_path in target_ts:
                if time.time() - start_time > TEST_DURATION: break
                ts_url = ts_path if ts_path.startswith('http') else f"{base_dir}/{ts_path}"
                
                ts_start = time.time()
                try:
                    ts_r = requests.get(ts_url, timeout=5, headers=headers, stream=True, verify=False)
                    chunk_bytes = 0
                    for chunk in ts_r.iter_content(chunk_size=128*1024):
                        if chunk:
                            chunk_bytes += len(chunk)
                            total_bytes += len(chunk)
                            if time.time() - start_time > TEST_DURATION: break
                    
                    ts_duration = time.time() - ts_start
                    if ts_duration > 0 and chunk_bytes > 10240:
                        mbps = (chunk_bytes * 8) / (ts_duration * 1024 * 1024)
                        speeds_mbps.append(mbps)
                except: 
                    continue
            time.sleep(1) 

    except Exception:
        return None

    test_time = time.time() - start_time
    if test_time > 0 and speeds_mbps:
        avg_speed = (total_bytes * 8) / (test_time * 1024 * 1024)
        max_speed = max(speeds_mbps)
        
        return {
            "name": name, "ip_port": ip_port,
            "avg_mbps": round(avg_speed, 2), "max_mbps": round(max_speed, 2)
        }
    return None

def main():
    if len(sys.argv) < 2:
        print("错误: 请指定 M3U 播放源网址。")
        return

    target_url = sys.argv[1]
    print(f"=== IPTV 流量测速程序启动 ===")
    
    content = fetch_m3u_content(target_url)
    if not content:
        return

    groups = {}
    lines = content.split('\n')
    for i in range(len(lines)):
        if lines[i].startswith('#EXTINF') and i+1 < len(lines):
            url = lines[i+1].strip()
            if url.startswith('http'):
                ip_port = urlparse(url).netloc
                if not ip_port: continue
                if ip_port not in groups: groups[ip_port] = []
                name_match = re.search(r',(.+)$', lines[i])
                name = name_match.group(1).strip() if name_match else "Unknown"
                groups[ip_port].append((name, url))

    tasks = []
    for ip_port, urls in groups.items():
        samples = random.sample(urls, min(len(urls), SAMPLES_PER_IP))
        tasks.extend(samples)

    print(f"📡 识别到 {len(groups)} 个独立服务器源，共抽取 {len(tasks)} 个频道样本进行流量压测...")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_stream_traffic, n, u): (n, u) for n, u in tasks}
        for future in futures:
            try:
                res = future.result()
                if res: 
                    results.append(res)
                    print(f"✅ 测速成功: {res['ip_port']} -> 平均码率 {res['avg_mbps']} Mbps")
            except Exception as e:
                pass

    # 按照您指定的 JSON 格式重组输出
    final_json = {"summary": {}}
    for res in results:
        ip = res['ip_port']
        if ip not in final_json["summary"]:
            final_json["summary"][ip] = {"alive_count": 0, "max_mbps": 0, "avg_mbps_list": []}
        
        s = final_json["summary"][ip]
        s["alive_count"] += 1
        s["max_mbps"] = max(s["max_mbps"], res["max_mbps"])
        s["avg_mbps_list"].append(res['avg_mbps'])

    for ip, data in final_json["summary"].items():
        if data["avg_mbps_list"]:
            data["avg_mbps"] = round(sum(data["avg_mbps_list"]) / len(data["avg_mbps_list"]), 2)
        del data["avg_mbps_list"]

    # 保存至当前工作目录（即宿主机通过 -v 挂载的目录）
    output_json_path = os.path.join(os.getcwd(), "traffic_summary.json")
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
    
    print(f"\n✨ 测速任务全部结束！报告已成功保存至: {output_json_path}")

if __name__ == "__main__":
    main()
