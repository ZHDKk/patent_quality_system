1、安装Docker：https://www.docker.com/products/docker-desktop/
    安装tailscale: https://login.tailscale.com ,使用Tailscale 做内网穿透(免费\不限速),在宿主机安装 Tailscale:根据系统选择安装方式安装，完成之后使用注册账号并登录。所有的使用者都用同一个主账号登录
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
4、Docker安装mysql：docker pull mysql:8.0.45 (用不到)
5、Docker 运行mysql：docker run --name mysql-local -p 3306:3306 -e MYSQL_ROOT_PASSWORD=zhdk123 -d mysql:8.0.45 (用不到)
6、代码生成 Fernet 密钥：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
7、代码生成 SECRET_KEY : python -c "import secrets; print(secrets.token_hex(32))"
    生成 RULE_ENCRYPT_KEY 的方法（Linux/Mac/WSL）：openssl rand -base64 32
8、安装requirements.txt：pip install -r requirements.txt
9、docker 常用指令：
检查所有容器的运行状态：docker-compose ps
停止并移除旧容器，避免冲突：docker-compose down
会强制重新构建镜像，应用新的基础镜像：docker-compose up -d --build
启动所有容器：docker-compose up -d
只启动某一个容器：docker-compose up -d mysql
重启某个容器指令：docker-compose restart celery_worker
                docker-compose restart backend celery_worker
查看日志前端：docker-compose logs celery_worker --tail=200
查看日志后端：docker-compose logs backend
检查容器内模板文件是否存在：docker-compose exec backend ls /app/frontend/templates

10、所有状态ok：
启动容器： docker-compose up -d
状态：
[+] up 7/7
 ✔ Network patent_quality_system_patent-network    Created                                                                                                                                                                                                                                                  0.0ss
 ✔ Container patent_quality_system-dedoc-1         Healthy                                                                                                                                                                                                                                                  30.8s
 ✔ Container patent_quality_system-redis-1         Healthy                                                                                                                                                                                                                                                  30.8s
 ✔ Container patent_quality_system-mysql-1         Healthy                                                                                                                                                                                                                                                  31.3s
 ✔ Container patent_quality_system-celery_worker-1 Started                                                                                                                                                                                                                                                  31.4s
 ✔ Container patent_quality_system-backend-1       Started                                                                                                                                                                                                                                                  31.6s
 ✔ Container patent_quality_system-nginx-1         Started

 10.1：
1. 初始化数据库（创建表结构）
由于容器是新创建的，数据库还没有表。需要先创建所有表，并添加一个管理员用户。
打开命令行（在项目根目录），执行以下命令进入 Flask shell：
docker-compose exec backend flask shell

2.进入 Python 交互环境后，依次执行：
from app import db
from app.models import User
from werkzeug.security import generate_password_hash
db.create_all()
admin = User(username='admin', password_hash=generate_password_hash('admin123'), role='admin')
db.session.add(admin)
db.session.commit()

# 退出
exit()

10.2.修改数据库字段类型:
进入终端输入:
docker ps
docker exec -it <容器名> mysql -uroot -p patent_quality  然后输入mysql密码
注意：语句末尾必须有分号 ;，然后按回车执行。
在 MySQL 命令行中执行：DESCRIBE patent_documents;
修改字段类型：ALTER TABLE patent_documents MODIFY parsed_json LONGTEXT;
验证修改结果：DESCRIBE patent_documents;
退出 MySQL：输入 exit 退出 MySQL 客户端。

10.3 修改管理员的用户名或密码：
1.进入 Flask shell：
docker-compose exec backend flask shell

2.查询管理员用户并修改：
from app.models import User
from werkzeug.security import generate_password_hash

# 假设原用户名为 admin
admin = User.query.filter_by(username='admin').first()
if admin:
    # 修改用户名
    admin.username = 'new_admin'
    # 修改密码（需要重新哈希）
    admin.password_hash = generate_password_hash('new_password')
    db.session.commit()
    print('管理员信息已更新')
else:
    print('用户不存在')

3.退出：
exit()

10.4 执行数据库迁移：
    1. 确保容器正在运行：docker-compose up -d
    2.进入后端容器：docker-compose exec backend bash
    3.在容器内执行迁移：flask db upgrade
    4.完整的容器内迁移流程：
        # 进入容器
        docker-compose exec backend bash

        # 确认当前目录
        pwd  # 应该是 /app

        # 如果 migrations 文件夹不存在，先初始化（确保数据库连接正常）
        flask db init

        # 生成迁移脚本（如果模型有变化）
        flask db migrate -m "add name to rule_name"

        # 执行升级
        flask db upgrade

        # 退出容器
        exit

10.5 停止并删除所有容器、网络、卷（谨慎）:停止并删除所有容器、网络、卷: docker-compose down -v

11、 访问前端界面
打开浏览器，访问：http://localhost:8888，如果从其他机器访问，将 localhost 替换为服务器 IP。

12、Docker使用花生壳做内网穿透：
12.1、拉取花生壳镜像：docker load -i ./phddns_docker.tar
12.2：查看镜像信息：docker images
12.3： 在运行：docker-compose up -d --build
12.4：查看花生壳SN码：docker exec phddns phddns status
12.5：记录下输出的 SN 码，然后访问 花生壳管理平台（https://console.hsk.oray.com/zh/passport/login），用该 SN 码和默认密码 admin 登录