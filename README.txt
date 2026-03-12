1、安装Docker：https://www.docker.com/products/docker-desktop/
2、Docker 汉化：https://github.com/asxez/DockerDesktop-CN/releases
3、Docker 镜像：
{
  "builder": {
    "gc": {
      "defaultKeepStorage": "20GB",
      "enabled": true
    }
  },
  "experimental": false,
  "registry-mirrors": [
    "https://docker.1panel.live",
    "https://docker.xuanyuan.me",
    "https://docker.m.daocloud.io",
    "https://docker.mirrors.ustc.edu.cn",
    "http://hub-mirror.c.163.com",
    "https://registry.docker-cn.com",
    "https://docker.1ms.run"
  ]
}
4、Docker安装mysql：docker pull mysql:8.0.45
5、Docker 运行mysql：docker run --name mysql-local -p 3306:3306 -e MYSQL_ROOT_PASSWORD=zhdk123 -d mysql:8.0.45
6、代码生成 Fernet 密钥：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
7、代码生成 SECRET_KEY : python -c "import secrets; print(secrets.token_hex(32))"
8、安装requirements.txt：pip install -r requirements.txt
9、检查所有容器的运行状态：docker-compose ps
10、 停止并移除旧容器，避免冲突：docker-compose down
11、会强制重新构建镜像，应用新的基础镜像：docker-compose up -d --build
12、所有状态ok：
(.venv) PS D:\pro\pro\other_pro\python\patent_quality_system> docker-compose up -d
[+] up 7/7
 ✔ Network patent_quality_system_patent-network    Created                                                                                                                                                                                                                                                  0.0ss
 ✔ Container patent_quality_system-dedoc-1         Healthy                                                                                                                                                                                                                                                  30.8s
 ✔ Container patent_quality_system-redis-1         Healthy                                                                                                                                                                                                                                                  30.8s
 ✔ Container patent_quality_system-mysql-1         Healthy                                                                                                                                                                                                                                                  31.3s
 ✔ Container patent_quality_system-celery_worker-1 Started                                                                                                                                                                                                                                                  31.4s
 ✔ Container patent_quality_system-backend-1       Started                                                                                                                                                                                                                                                  31.6s
 ✔ Container patent_quality_system-nginx-1         Started

 12.1：1. 初始化数据库（创建表结构）
由于容器是新创建的，数据库还没有表。需要先创建所有表，并添加一个管理员用户。
打开命令行（在项目根目录），执行以下命令进入 Flask shell：docker-compose exec backend flask shell

进入 Python 交互环境后，依次执行：
from app import db
from app.models import User
from werkzeug.security import generate_password_hash

# 创建所有表
db.create_all()

# 创建管理员用户（用户名/密码可自定义）
admin = User(
    username='admin',
    password_hash=generate_password_hash('admin123'),
    role='admin'
)
db.session.add(admin)
db.session.commit()

# 退出
exit()

12.2 访问前端界面
打开浏览器，访问：http://localhost:8080，如果从其他机器访问，将 localhost 替换为服务器 IP。

停止删除旧容器：docker-compose down
重新构建镜像：docker-compose up -d --build
检查容器内模板文件是否存在：docker-compose exec backend ls /app/frontend/templates