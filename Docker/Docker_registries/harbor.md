### Пример: Harbor — корпоративный реестр образов

**Harbor** — это бесплатный open-source реестр для хранения Docker-образов, запущенный в 2016 году командой VMware. В 2018 году Harbor перешел под контроль организации [CNCF](../../Kubernetes/cncf_overview.md) и с тех пор активно развивается (новые релизы выходят несколько раз в месяц). Он предоставляет функциональность частного реестра с расширенными возможностями для корпоративного использования, включая сканирование образов на уязвимости.

#### Ключевые возможности Harbor



*   **Управление доступом (RBAC)**: Проекты, пользователи и роли для гранулярного контроля доступа.

*   **Сканирование уязвимостей**: Интеграция со сканерами (например, Trivy, Clair) для автоматического анализа образов на известные уязвимости.

*   **Подпись образов**: Обеспечение целостности и происхождения образов с помощью Notary или Cosign.

*   **Репликация**: Автоматическая синхронизация образов между несколькими инстансами Harbor (например, для геораспределенных команд).

*   **Веб-интерфейс**: Удобный UI для управления проектами, пользователями и образами.

*   **Аудит**: Детальное логирование всех действий пользователей.



#### Назначение Harbor



В то время как Docker Hub удобен для публичного хранения образов, большинство компаний предпочитают хранить свои контейнерные образы приватно на собственных серверах. Harbor разработан для решения этой задачи, особенно в условиях закрытого контура компании (без доступа к интернету). Данное руководство фокусируется именно на такой установке, где ключевыми отличиями являются настройка переменных для отключения автоматического обновления сканера уязвимостей Trivy и необходимость ручного обогащения его баз.

#### Установка Harbor

Harbor устанавливается с помощью Docker Compose.

**Шаг 1.1 Ставим docker**
Установим docker и docker-compose:
```bash
apt update && 
apt install containerd docker.io docker-compose -y
systemctl enable docker --now && 
sudo usermod -aG docker $USER
```

**Шаг 1.2 Скачиваем Harbor и готовим конфиги**
Клонируем репозиторий Harbor, используя актуальную версию:
```bash
LATEST=$(curl -s https://api.github.com/repos/goharbor/harbor/releases/latest 
  | grep browser_download_url 
  | grep offline-installer 
  | cut -d '"' -f 4)

FILE=$(basename "$LATEST")

wget "$LATEST" && 
tar xvzf "$FILE" && 
rm "$FILE" && 
cd harbor
```
Создаём файл `.env` для хранения паролей:
```bash
sudo nano .env
```
Прописываем в переменных пароль Админа и БД:
```
HARBOR_ADMIN_PASSWORD=super_admin_pazzword
DB_PASSWORD=super_db_mazafaka
```
Изменяем права:
```bash
sudo chmod 600 .env
```
Далее работаем с файлом `harbor.yml`. Создаём резервную копию:
```bash
sudo cp harbor.yml.copy harbor.yml
```
Чтобы хосты доверяли этому репозиторию, нужно создать сертификаты в Центре Сертификации (CA).
Создайте сертификаты в вашем ЦА с именами:
`harbor.example.local.key`
`harbor.example.local.crt`
где `harbor.example.local` доменное имя вашего будущего репозитория.
Или перейдите на Шаг 3 (в отдельном разделе ниже), затем вернитесь сюда.

Открываем на редактирование:
```bash
sudo nano harbor.yml
```
Удаляем содержимое файла и вставляем следующие параметры:
```yaml
hostname: harbor.example.local
http:
  port: 80
https:
  port: 443
  certificate: /opt/harbor/harbor.example.local.crt
  private_key: /opt/harbor/harbor.example.local.key
harbor_admin_password: ${HARBOR_ADMIN_PASSWORD}
database:
  password: ${DB_PASSWORD}
  max_idle_conns: 200
  max_open_conns: 100
  conn_max_lifetime: 5m
  conn_max_idle_time: 5m
data_volume: /data
trivy:
  ignore_unfixed: false
  skip_update: true           # Если нет интернета, базу Trivy нужно обновлять вручную
  skip_java_db_update: true   # Если нет интернета, базу Trivy нужно обновлять вручную
  offline_scan: true          # Если нет интернета, то сканирование будет в оффлайн режиме
  security_check: vuln
  insecure: false
  timeout: 5m0s
jobservice:
  max_job_workers: 10
  max_job_duration_hours: 24
  job_loggers:
    - STD_OUTPUT
    - FILE
  logger_sweeper_duration: 1 #days
notification:
  webhook_job_max_retry: 3
  webhook_job_http_client_timeout: 3 #seconds
log:
  level: info
  local:
    rotate_count: 50
    rotate_size: 200M
    location: /var/log/harbor
_version: 2.14.0
proxy:
  http_proxy:
  https_proxy:
  no_proxy:
  components:
    - core
    - jobservice
    - trivy
upload_purging:
  enabled: true
  age: 168h
  interval: 24h
  dryrun: false
cache:
  enabled: false
  expire_hours: 24
```
*Примечание: Данная конфигурация Trivy предназначена для работы в закрытом контуре (без доступа к интернету). Это означает, что базы сканера уязвимостей Trivy не будут обновляться напрямую, а только вручную (см. Шаг 4). Настройки конфигурации `skip_update: true` и `offline_scan: true` сделаны исходя из этого требования.*

**Шаг 2. Запуск установки**
Запустите установку с компонентом Trivy:
```bash
sudo ./install.sh --with-trivy
```

**Шаг 2.1 Вход в UI**
После установки вы сможете войти в веб-интерфейс Harbor по адресу, указанному в `hostname` (например, `https://harbor.example.local`). Логин и пароль администратора были заданы в `.env` файле.

#### Работа с Harbor

1. **Аутентификация**:

    ```bash
    docker login harbor.yourdomain.com
    # Username: admin
    # Password: <YourAdminPassword>
    ```

2. **Тегирование и отправка образа**:

    ```bash
    # В Harbor образы организованы по проектам (например, 'library')
    docker tag my-app:latest harbor.yourdomain.com/library/my-app:v1
    docker push harbor.yourdomain.com/library/my-app:v1
    ```

3. **Получение образа**:

    ```bash
    docker pull harbor.yourdomain.com/library/my-app:v1
    ```

#### Шаг 3. Создание ЦА и подписание сертификата
Для обеспечения доверия хостов к репозиторию Harbor необходимо создать Центр Сертификации (CA) и выпустить подписанные сертификаты.

Создаём директорию для хранения сертификатов:
```bash
sudo mkdir -p ~/harbor/certs
cd ~/harbor/certs
```
Создаём сертификаты корневого ЦА:
```bash
# Root CA key
openssl genrsa -out root-ca.key 4096

# Root CA cert (на 10 лет, можно меньше)
openssl req -x509 -new -nodes -sha256 -days 3650 
  -key root-ca.key -out root-ca.crt 
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/OU=ITZM/CN=My-Root-CA"
```
Измените значения переменных на ваше имя и IP Harbor сервера:
```bash
export HARBOR_HOST=harbor.example.local
export MyIP=2.2.2.2
```
Выполните команды для создания серверных сертификатов Harbor:
```bash
# server key
openssl genrsa -out ${HARBOR_HOST}.key 4096

# csr config with SAN
cat > ${HARBOR_HOST}.csr.cnf <<EOF
[req]
default_bits       = 4096
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[dn]
C=RU
ST=Moscow
L=Moscow
O=HomeLab
OU=ITZM
CN=${HARBOR_HOST}

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${HARBOR_HOST}
IP.1  = ${MyIP}
EOF

# create CSR
openssl req -new -key ${HARBOR_HOST}.key -out ${HARBOR_HOST}.csr -config ${HARBOR_HOST}.csr.cnf

# sign server cert by our CA
openssl x509 -req -in ${HARBOR_HOST}.csr -CA root-ca.crt -CAkey root-ca.key -CAcreateserial 
  -out ${HARBOR_HOST}.crt -days 825 -sha256 
  -extensions req_ext -extfile ${HARBOR_HOST}.csr.cnf
```
В результате будут созданы:
*   `root-ca.crt` - корневой сертификат, который необходимо распространить на все клиентские хосты.
*   `${HARBOR_HOST}.crt` и `${HARBOR_HOST}.key` - серверные сертификаты для Harbor.

**Распространение корневого CA сертификата:**
Скопируйте `root-ca.crt` на все хосты, которые будут взаимодействовать с Harbor.

Для **Ubuntu**:
```bash
sudo cp root-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```
Для **CentOS**:
```bash
sudo cp root-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust extract
```
После установки сертификатов перезапустите Docker на хостах:
```bash
systemctl restart docker.service
```

#### Шаг 4. Оффлайн обновление Trivy
Сканер уязвимостей Trivy требует регулярных обновлений баз. В случае работы Harbor в закрытом контуре (без доступа к интернету), базы необходимо обновлять вручную.

**На компьютере с доступом в интернет:**
Установите Docker и загрузите базы Trivy:
```bash
apt update && 
apt install docker.io -y
systemctl enable docker --now && 
sudo usermod -aG docker $USER
```
Скачайте образы баз уязвимостей:
```bash
docker pull ghcr.io/aquasecurity/trivy-db:2
docker pull ghcr.io/aquasecurity/trivy-java-db:1
```
Упакуйте скачанные базы:
```bash
# DB
cid=$(docker create ghcr.io/aquasecurity/trivy-db:2)
docker cp $cid:/db db
docker rm $cid

# Java DB
cid=$(docker create ghcr.io/aquasecurity/trivy-java-db:1)
docker cp $cid:/java-db java-db
docker rm $cid

tar czf trivy-db.tgz db
tar czf trivy-java-db.tgz java-db
```
**Перенос на Harbor-хост (закрытый контур) и распаковка:**
Перенесите файлы `trivy-db.tgz` и `trivy-java-db.tgz` на Harbor-хост, где нет доступа к интернету. Затем распакуйте их в соответствующие директории внутри контейнера `trivy-adapter`:
```bash
sudo mkdir -p /data/trivy-adapter/trivy/db
sudo mkdir -p /data/trivy-adapter/trivy/java-db
sudo tar -xzf trivy-db.tgz -C /data/trivy-adapter/trivy/db
sudo tar -xzf trivy-java-db.tgz -C /data/trivy-adapter/trivy/java-db
sudo chown -R 10000:10000 /data/trivy-adapter/trivy 2>/dev/null || true
docker restart trivy-adapter
```
Таким образом, базы Trivy будут обновлены вручную, и сканер сможет функционировать в оффлайн-режиме.
