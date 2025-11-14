# Автоматизация развертывания в Docker Swarm с помощью GitLab CI и mTLS

Это руководство является продолжением [быстрого старта с Docker Swarm и Traefik](./docker_swarm_with_traefik_quickstart.md) и описывает, как автоматизировать процесс развертывания приложений с помощью GitLab CI/CD, обеспечив безопасность соединения с помощью mTLS.

## Цель

Настроить CI/CD пайплайн в GitLab, который будет автоматически развертывать или обновлять приложения в Docker Swarm кластере при каждом коммите в `master` ветку. Соединение между GitLab Runner и Docker хостом будет защищено с помощью mTLS (взаимной аутентификации по TLS).

## Часть 1: Защита Docker Daemon с помощью mTLS

Чтобы GitLab Runner мог удаленно и безопасно управлять Docker Swarm, необходимо настроить Docker daemon на узле-менеджере на прием команд только от клиентов, предоставивших валидный TLS-сертификат.

### Шаг 1.1: Генерация сертификатов

На узле-менеджере Swarm мы сгенерируем все необходимые ключи и сертификаты с помощью `openssl`.

1.  **Создайте директорию для сертификатов:**

    ```bash
    mkdir -p ~/docker-certs
    cd ~/docker-certs
    ```

2.  **Сгенерируйте ключ и сертификат для Центра Сертификации (CA):**
    Это будет корневой сертификат, которым мы будем подписывать все остальные.

    ```bash
    # Генерируем приватный ключ CA
    openssl genrsa -aes256 -out ca-key.pem 4096
    # Пароль потребуется для подписи других сертификатов

    # Создаем самоподписанный сертификат CA
    openssl req -new -x509 -days 365 -key ca-key.pem -sha256 -out ca.pem
    # В процессе нужно будет ввести информацию о сертификате (можно оставить по умолчанию)
    ```

3.  **Сгенерируйте ключ и сертификат для сервера (Docker Daemon):**
    Этот сертификат будет использоваться Docker daemon для подтверждения своей подлинности клиенту.

    ```bash
    # Генерируем приватный ключ сервера
    openssl genrsa -out server-key.pem 4096

    # Создаем запрос на подпись сертификата (CSR)
    # ВАЖНО: В поле "Common Name (CN)" укажите IP-адрес или доменное имя вашего менеджера Swarm
    openssl req -subj "/CN=<MANAGER_IP_OR_DOMAIN>" -sha256 -new -key server-key.pem -out server.csr

    # Подписываем сертификат сервера нашим CA
    openssl x509 -req -days 365 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out server-cert.pem
    ```

4.  **Сгенерируйте ключ и сертификат для клиента (GitLab Runner):**
    Этот сертификат будет использоваться GitLab Runner для аутентификации на сервере.

    ```bash
    # Генерируем приватный ключ клиента
    openssl genrsa -out key.pem 4096

    # Создаем запрос на подпись сертификата (CSR)
    openssl req -subj "/CN=client" -new -key key.pem -out client.csr

    # Добавляем расширения для клиентской аутентификации
    echo "extendedKeyUsage = clientAuth" > extfile.cnf

    # Подписываем сертификат клиента нашим CA
    openssl x509 -req -days 365 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -out cert.pem -extfile extfile.cnf
    ```

5.  **Очистка и проверка:**
    Удалите ненужные файлы запросов и установите правильные права на ключи.

    ```bash
    rm -v client.csr server.csr extfile.cnf ca.srl
    chmod -v 0400 ca-key.pem key.pem server-key.pem
    chmod -v 0444 ca.pem server-cert.pem cert.pem
    ```

### Шаг 1.2: Настройка Docker Daemon

1.  **Скопируйте серверные сертификаты в директорию Docker:**

    ```bash
    sudo mkdir -p /etc/docker/certs
    sudo cp -v {ca,server-cert,server-key}.pem /etc/docker/certs/
    ```

2.  **Отредактируйте конфигурационный файл Docker `/etc/docker/daemon.json`:**
    Добавьте следующие строки, чтобы включить TLS и указать пути к сертификатам.

    ```json
    {
      "tls": true,
      "tlscert": "/etc/docker/certs/server-cert.pem",
      "tlskey": "/etc/docker/certs/server-key.pem",
      "tlscacert": "/etc/docker/certs/ca.pem",
      "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"]
    }
    ```
    *   `hosts`: Указывает Docker слушать как на локальном сокете, так и на TCP-порту `2376` (стандартный порт для Docker с TLS).

3.  **Перезапустите Docker:**

    ```bash
    sudo systemctl restart docker
    ```

### Шаг 1.3: Проверка удаленного подключения

С локальной машины (не с сервера) проверьте, что вы можете подключиться к удаленному Docker daemon.

1.  Скопируйте клиентские сертификаты (`ca.pem`, `cert.pem`, `key.pem`) с сервера на вашу локальную машину в директорию `~/.docker/`.
2.  Выполните команду:

    ```bash
    docker --tlsverify \
      --tlscacert=~/.docker/ca.pem \
      --tlscert=~/.docker/cert.pem \
      --tlskey=~/.docker/key.pem \
      -H=<MANAGER_IP_OR_DOMAIN>:2376 \
      version
    ```
    Если команда успешно выполнилась и показала версию удаленного Docker, значит, mTLS настроен правильно.

## Часть 2: Настройка GitLab CI/CD

### Шаг 2.1: Добавление сертификатов в переменные GitLab CI

Никогда не храните ключи и сертификаты в репозитории. Используйте для этого переменные CI/CD в GitLab.

1.  Перейдите в вашем проекте GitLab в **Settings -> CI/CD**.
2.  Найдите раздел **Variables** и раскройте его.
3.  Создайте следующие переменные типа **File**:
    *   `DOCKER_CA_PEM`: Вставьте содержимое файла `ca.pem`.
    *   `DOCKER_CERT_PEM`: Вставьте содержимое файла `cert.pem`.
    *   `DOCKER_KEY_PEM`: Вставьте содержимое приватного ключа клиента `key.pem`.

### Шаг 2.2: Создание `.gitlab-ci.yml`

Создайте или отредактируйте файл `.gitlab-ci.yml` в корне вашего проекта, добавив в него этап `deploy`.

```yaml
stages:
  # - build
  # - test
  - deploy

deploy_to_swarm:
  stage: deploy
  image: docker:20.10
  before_script:
    # Устанавливаем переменные окружения для Docker CLI
    # GitLab автоматически создаст файлы из переменных типа "File"
    # и запишет пути к ним в переменные с таким же именем.
    - export DOCKER_TLS_CERTDIR=$(pwd)/.docker-certs
    - mkdir -p $DOCKER_TLS_CERTDIR
    - cp "$DOCKER_CA_PEM" "$DOCKER_TLS_CERTDIR/ca.pem"
    - cp "$DOCKER_CERT_PEM" "$DOCKER_TLS_CERTDIR/cert.pem"
    - cp "$DOCKER_KEY_PEM" "$DOCKER_TLS_CERTDIR/key.pem"
    - export DOCKER_HOST=tcp://<MANAGER_IP_OR_DOMAIN>:2376
    - export DOCKER_TLS_VERIFY=1
    - export DOCKER_CERT_PATH=$DOCKER_TLS_CERTDIR
  script:
    - docker info # Проверяем, что подключение установлено
    - docker stack deploy -c docker-compose.yml my-app
  only:
    - master
```

**Разбор конфигурации:**

*   `image: docker:20.10`: Используем официальный образ Docker, в котором есть все необходимые инструменты.
*   `before_script`:
    *   Создается директория для сертификатов.
    *   Содержимое из **File**-переменных GitLab (`$DOCKER_CA_PEM` и т.д.) копируется в файлы с нужными именами (`ca.pem`, `cert.pem`, `key.pem`).
    *   `DOCKER_HOST`: Указывает Docker CLI на адрес вашего защищенного Swarm менеджера.
    *   `DOCKER_TLS_VERIFY=1`: Включает проверку TLS.
    *   `DOCKER_CERT_PATH`: Указывает Docker CLI, где искать сертификаты.
*   `script`:
    *   `docker info`: Простая команда для проверки успешности подключения к удаленному хосту.
    *   `docker stack deploy`: Та же команда, что и при ручном развертывании. Она выполняется на GitLab Runner, но команды отправляются на удаленный, защищенный Docker Swarm.
*   `only: - master`: Ограничивает автоматическое развертывание только для `master` ветки.

## Заключение

Теперь при каждом пуше в `master` ветку GitLab CI будет автоматически запускать пайплайн, который безопасно подключится к вашему Docker Swarm кластеру и развернет последнюю версию приложения. Этот подход обеспечивает полностью автоматизированный и безопасный процесс "Git-to-Production".

```