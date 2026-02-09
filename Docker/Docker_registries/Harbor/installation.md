# Установка Harbor

Harbor устанавливается с помощью Docker Compose.

## Шаг 1.1 Ставим docker
Установим docker и docker-compose:
```bash
apt update && 
apt install containerd docker.io docker-compose -y
systemctl enable docker --now && 
sudo usermod -aG docker $USER
```

## Шаг 1.2 Скачиваем Harbor и готовим конфиги
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
*Примечание: Данная конфигурация Trivy предназначена для работы в закрытом контуре (без доступа к интернету). Это означает, что базы сканера уязвимостей Trivy не будут обновляться напрямую, а только вручную (см. [Оффлайн обновление Trivy](./offline_trivy_update.md)). Настройки конфигурации `skip_update: true` и `offline_scan: true` сделаны исходя из этого требования.*

## Шаг 2. Запуск установки
Запустите установку с компонентом Trivy:
```bash
sudo ./install.sh --with-trivy
```

## Шаг 2.1 Вход в UI
После установки вы сможете войти в веб-интерфейс Harbor по адресу, указанному в `hostname` (например, `https://harbor.example.local`). Логин и пароль администратора были заданы в `.env` файле.
