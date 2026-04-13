#FROM python:3.11-slim
FROM python:3.14.3

WORKDIR /app

# 安装系统依赖（添加 LibreOffice）
RUN apt-get update && apt-get install -y \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-eng \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

# 设置 pip 使用清华镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 或者使用阿里云镜像
# RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY ./backend/app/ ./app/
COPY ./backend/run.py .

# 复制前端模板目录到容器内 /app/frontend
COPY ./frontend ./frontend

# 环境变量
ENV FLASK_APP=run.py
ENV FLASK_ENV=production

# 启动命令
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "run:app"]