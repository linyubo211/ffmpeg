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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TEST_DURATION = 15     
SAMPLES_PER_IP = 3     
MAX_WORKERS = 10       

def fetch_m3u_content(url):
    print(f"[*] 正在动态下载 M3U 文件: {url}", flush=True)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, timeout=15, headers=headers, verify=False)
        if response.status_code != 200:
            print(f"[!] 下载失败，HTTP 状态码: {response.status_code}", flush=True)
            return None
        return response.text
    except Exception as e:
        print(f"[!] 请求出错: {e}", flush=True)
        return None

def test_stream_traffic(name, url, index, total):
    ip_port = urlparse(url).netloc
    print(f"[{index}/{total}] 开始测试 -> 服务器: {ip_port} | 频道: {name}", flush=True)
    
    start_time = time.time()
    total_bytes = 0
    speeds_mbps = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        r = requests.get(url, timeout=5, headers=headers, verify=False)
        if r.status_code != 200:
            print(f"  └─ ✖ 【失败】HTTP 状态码: {r.status_code} | 频道: {name}", flush=True)
            return None
        
        base_dir = url.rsplit('/', 1)[0]
        ts_lines = [line.strip() for line in r.text.split('\n') if line.strip() and not line.startswith('#')]
        if not ts_lines: 
            print(f"  └─ ✖ 【失败】无有效 TS 片段 | 频道: {name}", flush=True)
            return None

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

    except Exception as e:
        print(f"  └─ ⚠ 【错误】{e} | 频道: {name}", flush=True)
        return None

    test_time = time.time() - start_time
    if test_time > 0 and speeds_mbps:
        avg_speed = (total_bytes * 8) / (test_time * 1024 * 1024)
        max_speed = max(speeds_mbps)
        print(f"  └─ ✔ 【完成】服务器: {ip_port} | 平均码率: {round(avg_speed, 2)} Mbps | 峰值: {round(max_speed, 2)} Mbps", flush=True)
        return {
            "name": name, "ip_port": ip_port,
            "avg_mbps": round(avg_speed, 2), "max_mbps": round(max_speed, 2)
        }
    else:
        print(f"  └─ ⌛ 【超时/无流量】拉流过慢 | 频道: {name}", flush=True)
        return None

def main():
    if len(sys.argv) < 2:
        print("错误: 请至少指定一个 M3U 播放源网址。", flush=True)
        return

    # 获取命令行传入的所有 M3U 网址
    target_urls = sys.argv[1:]
    print(f"=== IPTV 流量测速程序启动 (共收到 {len(target_urls)} 个订阅源) ===", flush=True)
    
    all_groups = {} # 全局 IP 组字典，用于跨链接去重
    
    # 循环遍历并下载解析每一个 M3U 链接
    for idx, target_url in enumerate(target_urls, 1):
        print(f"\n[{idx}/{len(target_urls)}] 正在下载解析订阅源: {target_url}", flush=True)
        content = fetch_m3u_content(target_url)
        if not content:
            continue

        lines = content.split('\n')
        for i in range(len(lines)):
            if lines[i].startswith('#EXTINF') and i+1 < len(lines):
                url = lines[i+1].strip()
                if url.startswith('http'):
                    ip_port = urlparse(url).netloc
                    if not ip_port: continue
                    # 全局合并：相同服务器 IP 归纳到同一组
                    if ip_port not in all_groups: 
                        all_groups[ip_port] = []
                    
                    name_match = re.search(r',(.+)$', lines[i])
                    name = name_match.group(1).strip() if name_match else "Unknown"
                    all_groups[ip_port].append((name, url))

    all_tasks = []
    # 全局每个唯一 IP 只随机抽样一次（最多抽 SAMPLES_PER_IP 个频道）
    for ip_port, urls in all_groups.items():
        samples = random.sample(urls, min(len(urls), SAMPLES_PER_IP))
        for s in samples:
            all_tasks.append((s[0], s[1]))

    total_tasks = len(all_tasks)
    if total_tasks == 0:
        print("❌ 错误: 没有从任何网址中解析到有效的频道源。", flush=True)
        return

    print(f"\n📡 全局去重合并完毕，总计识别到 {total_tasks} 个唯一频道样本，开始多线程流量压测...\n" + "="*50, flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_stream_traffic, n, u, i+1, total_tasks): (n, u) for i, (n, u) in enumerate(all_tasks)}
        for future in futures:
            try:
                res = future.result()
                if res: 
                    results.append(res)
            except Exception:
                pass

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

    output_json_path = os.path.join(os.getcwd(), "traffic_summary.json")
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*50, flush=True)
    print(f"✨ 测速任务全部结束！报告已成功保存至: {output_json_path}", flush=True)
    print("="*50, flush=True)

if __name__ == "__main__":
    main()
