# FTP в Docker: Контейнеризация FTP-сервера

---

## Определения

**Контейнеризация FTP** — подход к развёртыванию FTP-сервера в изолированном контейнере (Docker/Podman), обеспечивающий мобильность, масштабируемость и изоляцию от хост-системы.

**Persistent Volume** — механизм сохранения данных за пределами жизненного цикла контейнера. Используется для хранения файлов пользователей, конфигураций и логов.

**Health Check** — механизм проверки состояния сервиса в контейнере. Используется для автоматического перезапуска и балансировки нагрузки.

**Docker Compose** — инструмент для определения и запуска мультиконтейнерных приложений. Описывает сервисы, сети и тома в YAML-файле.

---

## Основные концепции

### Архитектура

```
┌─────────────────────────────────────┐
│            Host System              │
├─────────────────────────────────────┤
│  Docker Engine                      │
│  ┌─────────────────────────────┐   │
│  │     vsftpd Container        │   │
│  │  ┌─────────────────────┐   │   │
│  │  │     vsftpd          │   │   │
│  │  │  Port 21 (control)  │   │   │
│  │  │  Ports 40000-40100  │   │   │
│  │  │    (data)           │   │   │
│  │  └─────────────────────┘   │   │
│  │           │                 │   │
│  │  ┌────────▼────────────┐   │   │
│  │  │  Persistent Volumes  │   │   │
│  │  │  /data (user files)  │   │   │
│  │  │  /config (vsftpd.conf)│   │   │
│  │  │  /logs (logs)        │   │   │
│  │  └─────────────────────┘   │   │
│  └─────────────────────────────┘   │
│           │                         │
│  ┌────────▼────────────┐           │
│  │   Docker Network     │           │
│  │  ftp-network (bridge)│           │
│  └─────────────────────┘           │
└─────────────────────────────────────┘
```

### Преимущества контейнеризации

| Преимущество | Описание |
| :--- | :--- |
| **Изоляция** | FTP-сервер не влияет на хост-систему |
| **Мобильность** | Контейнер запускается на любой системе с Docker |
| **Масштабируемость** | Легкое масштабирование через Docker Swarm/K8s |
| **Управление версиями** | Образы версионируются и откатываются |
| **Автоматизация** | Docker Compose для описания инфраструктуры |
| **Безопасность** | Ограничение ресурсов (CPU, RAM) |

### Рекомендации для production

1. **Persistent Volumes:** Всегда используйте тома для данных и конфигурации.
2. **Health Checks:** Настройте проверку состояния для автоматического перезапуска.
3. **Логирование:** Направляйте логи в Docker log driver или внешнюю систему.
4. **Сети:** Используйте изолированные сети для FTP-сервера.
5. **Ресурсы:** Ограничьте CPU и RAM через `deploy.resources`.
6. **Безопасность:** Запускайте контейнер от непривилегированного пользователя.

---

## Практические сценарии

### 1. Базовый vsftpd в Docker

#### Dockerfile

```dockerfile
# Dockerfile.vsftpd
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    vsftpd \
    db-util \
    && rm -rf /var/lib/apt/lists/*

# Создание директорий
RUN mkdir -p /var/run/vsftpd/empty \
    && chown root:root /var/run/vsftpd/empty \
    && chmod 755 /var/run/vsftpd/empty

# Копирование конфигурации
COPY vsftpd.conf /etc/vsftpd.conf
COPY virtual_users.txt /etc/vsftpd/virtual_users.txt

# Генерация БД пользователей
RUN db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db \
    && chmod 600 /etc/vsftpd/virtual_users.db

# Создание системного пользователя
RUN useradd -d /home/vsftpd -s /usr/sbin/nologin -M vsftpd \
    && mkdir -p /home/vsftpd

# Порты
EXPOSE 21 40000-40100

# Запуск
CMD ["vsftpd", "/etc/vsftpd.conf"]
```

#### vsftpd.conf

```ini
# vsftpd.conf (для Docker)
listen=YES
listen_port=21
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=022

# Виртуальные пользователи
guest_enable=YES
guest_username=vsftpd
virtual_use_local_privs=YES
pam_service_name=vsftpd.virtual
user_sub_token=$USER
local_root=/home/vsftpd/$USER

# Изоляция
chroot_local_user=YES
allow_writeable_chroot=YES
secure_chroot_dir=/var/run/vsftpd/empty

# Пассивный режим
pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100

# SSL/TLS
ssl_enable=YES
allow_anon_ssl=NO
force_local_data_ssl=YES
force_local_logins_ssl=YES
ssl_tlsv1_2=YES
ssl_tlsv1_3=YES
rsa_cert_file=/etc/ssl/certs/vsftpd.pem
rsa_private_key_file=/etc/ssl/private/vsftpd.key

# Таймауты
idle_session_timeout=300
data_connection_timeout=120

# Логирование
xferlog_enable=YES
vsftpd_log_file=/var/log/vsftpd.log
```

#### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  vsftpd:
    build:
      context: .
      dockerfile: Dockerfile.vsftpd
    container_name: vsftpd
    ports:
      - "21:21"
      - "40000-40100:40000-40100"
    volumes:
      - ./data:/home/vsftpd
      - ./config/vsftpd.conf:/etc/vsftpd.conf:ro
      - ./config/virtual_users.txt:/etc/vsftpd/virtual_users.txt:ro
      - ./ssl/certs:/etc/ssl/certs:ro
      - ./ssl/private:/etc/ssl/private:ro
      - ./logs:/var/log
    environment:
      - VSFTPD_MAX_CLIENTS=50
      - VSFTPD_MAX_PER_IP=5
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "21"]
      interval: 30s
      timeout: 10s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
```

### 2. ProFTPD с LDAP в Docker

```yaml
# docker-compose-proftpd.yml
version: '3.8'

services:
  proftpd:
    image: fauria/proftpd
    container_name: proftpd
    ports:
      - "21:21"
      - "40000-40100:40000-40100"
    volumes:
      - ./data:/home/ftp
      - ./config/proftpd.conf:/etc/proftpd/proftpd.conf:ro
      - ./ssl:/etc/ssl:ro
    environment:
      - FTP_HOSTNAME=ftp.example.com
      - FTP_USER=ftpuser
      - FTP_PASS=ftppass
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "21"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 3. Pure-FTPd с виртуальными пользователями

```yaml
# docker-compose-pure-ftpd.yml
version: '3.8'

services:
  pure-ftpd:
    image: stilliard/pure-ftpd:hardened
    container_name: pure-ftpd
    ports:
      - "21:21"
      - "40000-40100:40000-40100"
    volumes:
      - ./data:/home/ftpusers
      - ./config/pure-ftpd.conf:/etc/pure-ftpd.conf:ro
      - ./ssl:/etc/ssl/private:ro
    environment:
      - PUBLICHOST=ftp.example.com
      - FTP_USER_NAME=ftpuser
      - FTP_USER_PASS=ftppass
      - FTP_USER_HOME=/home/ftpusers/ftpuser
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "21"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 4. Kubernetes Deployment

```yaml
# k8s-ftp-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vsftpd
  labels:
    app: vsftpd
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vsftpd
  template:
    metadata:
      labels:
        app: vsftpd
    spec:
      containers:
      - name: vsftpd
        image: vsftpd:latest
        ports:
        - containerPort: 21
          name: control
        - containerPort: 40000
          name: data-start
        - containerPort: 40100
          name: data-end
        volumeMounts:
        - name: ftp-data
          mountPath: /home/vsftpd
        - name: vsftpd-config
          mountPath: /etc/vsftpd.conf
          subPath: vsftpd.conf
        - name: ssl-certs
          mountPath: /etc/ssl/certs/vsftpd.pem
          subPath: vsftpd.pem
        - name: ssl-private
          mountPath: /etc/ssl/private/vsftpd.key
          subPath: vsftpd.key
        resources:
          limits:
            cpu: "500m"
            memory: "256Mi"
          requests:
            cpu: "100m"
            memory: "128Mi"
        readinessProbe:
          tcpSocket:
            port: 21
          initialDelaySeconds: 10
          periodSeconds: 10
        livenessProbe:
          tcpSocket:
            port: 21
          initialDelaySeconds: 30
          periodSeconds: 30
      volumes:
      - name: ftp-data
        persistentVolumeClaim:
          claimName: vsftpd-data
      - name: vsftpd-config
        configMap:
          name: vsftpd-config
      - name: ssl-certs
        secret:
          secretName: vsftpd-ssl
      - name: ssl-private
        secret:
          secretName: vsftpd-ssl-key
---
apiVersion: v1
kind: Service
metadata:
  name: vsftpd
spec:
  selector:
    app: vsftpd
  ports:
  - name: control
    port: 21
    targetPort: 21
  - name: data
    port: 40000
    targetPort: 40000
    endPort: 40100
  type: LoadBalancer
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: vsftpd-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

---

## Дополнительная информация

### Диагностика

```bash
# Проверка статуса контейнера
docker ps | grep vsftpd
docker logs vsftpd

# Подключение к контейнеру
docker exec -it vsftpd bash

# Проверка логов
docker logs -f vsftpd
docker exec vsftpd tail -f /var/log/vsftpd.log

# Проверка сетевых соединений
docker exec vsftpd ss -tlnp
docker exec vsftpd netstat -tlnp
```

### Частые ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Connection refused** | Контейнер не запущен | `docker ps -a` и `docker logs` |
| **500 OOPS: chroot** | Неверные права на том | `chmod 755 /data` |
| **Passive mode failed** | Порты не проброшены | Проверьте `ports` в docker-compose |
| **Certificate error** | Сертификат не смонтирован | Проверьте volume mounts |

### Безопасность

1. **Non-root:** Запускайте контейнер от непривилегированного пользователя.
2. **Read-only filesystem:** Используйте `read_only: true` для конфигов.
3. **Сетевые ограничения:** Ограничьте подключения через Docker networks.
4. **Секреты:** Храните пароли в Docker secrets или Vault.
5. **Образы:** Используйте официальные образы или собирайте изtrusted sources.

### Связанные темы

- **[Docker: Overview](../../Docker/docker_overview.md)** — основы Docker
- **[Docker Compose](../../Docker/docker_compose_overview.md)** — мультиконтейнерные приложения
- **[Kubernetes: Volumes](../../Kubernetes/Base/Pod/pod_volumes.md)** — управление томами в K8s
- **[vsftpd: настройка](./vsftpd_setup.md)** — базовая конфигурация vsftpd
