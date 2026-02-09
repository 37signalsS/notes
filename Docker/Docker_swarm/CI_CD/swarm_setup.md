# CI/CD с Docker Swarm: Настройка кластера

## Шаг 1: Настройка кластера Docker Swarm

1. **Инициализация Swarm:**
    На узле, который будет менеджером, выполните:

    ```bash
    # Замените <MANAGER-IP> на реальный IP вашего узла
    docker swarm init --advertise-addr <MANAGER-IP>
    ```

    Сохраните команду `docker swarm join` с токеном для подключения рабочих узлов.

2. **Проверка кластера:**

    ```bash
    docker node ls
    ```

## Шаг 2: Защита Docker Daemon с помощью mTLS

Эта настройка позволяет GitLab Runner'у безопасно управлять Docker Swarm.

1. **Генерация сертификатов (`openssl`):**
    На узле-менеджере Swarm:

    ```bash
    # Создание директории для сертификатов
    mkdir -p ~/docker-certs && cd ~/docker-certs

    # 1. Генерация ключа и сертификата для Центра Сертификации (CA)
    openssl genrsa -aes256 -out ca-key.pem 4096
    openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem

    # 2. Генерация ключа и сертификата для сервера (Docker Daemon)
    # ВАЖНО: В поле "Common Name (CN)" укажите IP или FQDN вашего менеджера Swarm
    openssl genrsa -out server-key.pem 4096
    openssl req -subj "/CN=$(hostname -f)" -sha256 -new -key server-key.pem -out server.csr
    echo "subjectAltName = DNS:$(hostname -f),IP:$(hostname -I | awk '{print $1}')" > extfile.cnf
    openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem 
      -CAcreateserial -out server-cert.pem -extfile extfile.cnf

    # 3. Генерация ключа и сертификата для клиента (GitLab Runner)
    openssl genrsa -out key.pem 4096
    openssl req -subj "/CN=client" -new -key key.pem -out client.csr
    echo "extendedKeyUsage = clientAuth" > extfile-client.cnf
    openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem 
      -CAcreateserial -out cert.pem -extfile extfile-client.cnf

    # 4. Очистка и установка прав
    rm -v *.csr *.srl *.cnf
    chmod -v 0400 ca-key.pem key.pem server-key.pem
    chmod -v 0444 ca.pem server-cert.pem cert.pem
    ```

2. **Настройка Docker Daemon:**
    Создайте или отредактируйте `/etc/docker/daemon.json`:

    ```json
    {
      "tls": true,
      "tlscert": "/etc/docker/certs/server-cert.pem",
      "tlskey": "/etc/docker/certs/server-key.pem",
      "tlscacert": "/etc/docker/certs/ca.pem",
      "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
    }
    ```

    В качестве альтернативы, можно использовать `systemd` для переопределения команды запуска сервиса. Этот способ считается более гибким.

    Пример конфигурации для `/etc/systemd/system/docker.service.d/override.conf`:

    ```ini
    [Service]
    ExecStart=
    ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2376 --tlsverify --tlscacert=/etc/docker/certs/ca.pem --tlscert=/etc/docker/certs/server-cert.pem --tlskey=/etc/docker/certs/server-key.pem
    ```

    После создания файла необходимо выполнить `sudo systemctl daemon-reload`.

3. **Копирование сертификатов и перезапуск Docker:**

    ```bash
    sudo mkdir -p /etc/docker/certs
    sudo cp ~/docker-certs/{ca.pem,server-cert.pem,server-key.pem} /etc/docker/certs/
    sudo systemctl restart docker
    ```

## Шаг 2.1: Упрощение удаленного доступа с Docker Context

После настройки mTLS, вместо того чтобы каждый раз указывать хост и ключи в командной строке или использовать переменные окружения, можно использовать **Docker Context**. Это позволяет легко переключаться между разными Docker-окружениями (локальным, удаленным dev, удаленным prod).

- **Создание контекста:**

    На вашей локальной машине или в окружении, откуда вы будете управлять кластером, выполните команду. У вас должны быть файлы сертификатов клиента (`ca.pem`, `cert.pem`, `key.pem`), полученные на предыдущем шаге.

    ```sh
    docker context create prod-swarm 
      --docker "host=tcp://prod.example.com:2376,ca=/path/to/ca.pem,cert=/path/to/cert.pem,key=/path/to/key.pem"
    ```

    Где `prod.example.com` — это доменное имя вашего Swarm менеджера.

- **Переключение на контекст:**

    ```sh
    docker context use prod-swarm
    ```

- После этого все команды `docker` (например, `docker ps`, `docker service ls`) будут выполняться на удаленном Swarm-кластере. Чтобы вернуться к локальному окружению, выполните `docker context use default`.

Этот механизм используется в CI/CD пайплайнах для удобного и безопасного взаимодействия с кластером.
