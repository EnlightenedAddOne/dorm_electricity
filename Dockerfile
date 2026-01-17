# 使用官方 Python 基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 1. 换源并安装 Chrome、驱动、中文字体和必要依赖
# 注意：已移除 libgconf-2-4
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list; \
    fi && \
    apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    chromium \
    chromium-driver \
    fonts-wqy-zenhei \
    fonts-liberation \
    libglib2.0-0 \
    libnss3 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# 2. 复制依赖并安装 Python 库
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3. 复制所有代码
COPY . .

# 4. 暴露端口
EXPOSE 5000

# 5. 启动命令
# CMD ["python", "main.py"]
CMD ["python", "app/main.py"]
# CMD ["python", "run.py"]