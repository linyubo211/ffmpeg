FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置 Python 输出不使用缓冲区，实现日志实时打印
ENV PYTHONUNBUFFERED=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    iputils-ping \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖声明并安装 Python 库
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 赋予启动脚本权限
RUN chmod +x entrypoint.sh

# 设置容器入口
ENTRYPOINT ["./entrypoint.sh"]
