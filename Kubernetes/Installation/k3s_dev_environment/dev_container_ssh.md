## 5. Создание рабочего контейнера с SSH

Это нетрадиционный подход, но он позволяет получить изолированное рабочее пространство внутри кластера.

#### Dockerfile (`dev-container/Dockerfile`)

```dockerfile
FROM ubuntu:24.04

# Устанавливаем SSH-сервер и базовые утилиты
RUN apt-get update && apt-get install -y --no-install-recommends 
    openssh-server 
    sudo 
    git 
    curl 
    && rm -rf /var/lib/apt/lists/*

# Копируем и настраиваем скрипт инициализации
COPY init-container.sh /init-container.sh
RUN chmod +x /init-container.sh

# Открываем порт для SSH
EXPOSE 22

# Скрипт инициализации будет запущен при старте контейнера
ENTRYPOINT ["/init-container.sh"]
```

#### Скрипт инициализации (`dev-container/init-container.sh`)

Скрипт создает пользователя и группу при старте контейнера, используя переменные окружения, а также добавляет CA-сертификат в доверенные.

```bash
#!/bin/sh
set -e

# Переменные окружения, передаваемые при запуске пода
USER_NAME=${DEV_USER_NAME:-user}
GROUP_NAME=${DEV_GROUP_NAME:-user}
USER_ID=${DEV_USER_ID:-1000}
GROUP_ID=${DEV_GROUP_ID:-1000}

# Создание группы и пользователя
addgroup -g ${GROUP_ID} ${GROUP_NAME}
adduser -u ${USER_ID} -G ${GROUP_NAME} -s /bin/bash -D ${USER_NAME}
echo "${USER_NAME} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Добавление CA в доверенные, если он был смонтирован в контейнер
CA_CERT_PATH="/etc/ssl/certs/dfca.crt"
if [ -f "$CA_CERT_PATH" ]; then
    cp "$CA_CERT_PATH" /usr/local/share/ca-certificates/
    update-ca-certificates
fi

# Запуск SSH-демона
/usr/sbin/sshd -D
```

Развертывание этого контейнера в кластере будет рассмотрено в отдельном руководстве по созданию соответствующего Helm-чарта. Он будет запускать контейнер как `Deployment` и передавать в него переменные окружения и CA-сертификат через `ConfigMap`.
