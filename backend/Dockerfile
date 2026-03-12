FROM python:3.11-slim

WORKDIR /app

# 复制依赖文件并安装
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