# Grafana, Graphite, Carbon, Collectd: Система мониторинга и визуализации

Эта статья описывает развертывание системы визуализации данных и мониторинга с использованием Grafana, Graphite и Collectd, с фокусом на современный подход с использованием Docker Compose.

---

## 1. Компоненты системы

-   **Grafana:** Мощная платформа для аналитики и интерактивной визуализации данных. Позволяет создавать дашборды, графики и алерты.
-   **Graphite:** Система для хранения и обработки временных рядов. Состоит из трех основных компонентов:
    -   **Carbon:** Демон, который принимает метрики по сети (например, от Collectd) и записывает их в базу данных.
    -   **Whisper:** Легковесная файловая база данных для хранения временных рядов с фиксированным размером.
    -   **Graphite-web:** Веб-интерфейс для визуализации данных и API для их получения (именно к нему будет обращаться Grafana).
-   **Collectd:** Демон, который собирает системные метрики (CPU, память, сеть, диск и т.д.) и отправляет их в Graphite или другие системы хранения.

## 2. Архитектура

Процесс сбора и визуализации метрик выглядит следующим образом:
1.  `Collectd`, запущенный на хост-машине, собирает системные метрики.
2.  `Collectd` отправляет эти метрики на `Carbon` (компонент Graphite), который слушает порт `2003`.
3.  `Carbon` записывает полученные метрики в базу данных `Whisper`.
4.  `Grafana` подключается к `Graphite-web` как к источнику данных (Data Source).
5.  `Grafana` запрашивает данные у `Graphite-web` API, который читает их из `Whisper`, и строит на их основе графики и дашборды.

---

## 3. Развертывание с помощью Docker Compose

Этот метод позволяет быстро развернуть Grafana и Graphite в изолированных контейнерах.

### Шаг 3.1: Создание файла `docker-compose.yml`

Создайте директорию для проекта (например, `~/monitoring`) и в ней файл `docker-compose.yml` со следующим содержимым:

```yaml
version: '3.8'

services:
  graphite:
    image: graphiteapp/graphite-statsd:1.1.10-1
    container_name: graphite
    restart: always
    ports:
      - "8080:80"   # Graphite Web UI (изменен на 8080, чтобы не конфликтовать с другими веб-серверами)
      - "2003:2003"   # Carbon Line Receiver (для Collectd)
      - "2004:2004"   # Carbon Pickle Receiver
      - "8125:8125/udp" # StatsD UDP
    volumes:
      - graphite_data:/opt/graphite/storage
      - graphite_conf:/opt/graphite/conf

  grafana:
    image: grafana/grafana:10.4.2
    container_name: grafana
    restart: always
    ports:
      - "3000:3000" # Grafana Web UI
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin # В реальной среде используйте более надежный пароль
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - graphite

volumes:
  graphite_data:
  graphite_conf:
  grafana_data:
```

### Шаг 3.2: Запуск стека

В директории с файлом `docker-compose.yml` выполните команду:
```bash
docker-compose up -d
```
Это запустит контейнеры Grafana и Graphite в фоновом режиме.

---

## 4. Настройка Collectd на хосте

Теперь необходимо установить и настроить `collectd` на хост-машине (или на любой другой машине, метрики которой вы хотите собирать), чтобы он отправлял данные в наш Graphite контейнер.

### Шаг 4.1: Установка Collectd
```bash
sudo apt update
sudo apt install collectd -y
```

### Шаг 4.2: Настройка плагина `write_graphite`

Откройте конфигурационный файл `collectd`:
```bash
sudo nano /etc/collectd/collectd.conf
```
Найдите секцию `<Plugin write_graphite>`. Если ее нет, добавьте. Раскомментируйте ее и приведите к следующему виду, чтобы `collectd` отправлял метрики на порт `2003` нашего Docker-хоста (предполагается, что Docker запущен на `localhost`).

```conf
<Plugin write_graphite>
  <Node "graphite">
    Host "localhost"
    Port "2003"
    Protocol "tcp"
    LogSendErrors true
    Prefix "collectd."
    StoreRates true
    AlwaysAppendDS false
    EscapeCharacter "_"
  </Node>
</Plugin>
```

После сохранения изменений перезапустите `collectd`:
```bash
sudo systemctl restart collectd
```

---

## 5. Настройка Grafana

### Шаг 5.1: Вход в Grafana
Откройте в браузере `http://localhost:3000`. Используйте логин `admin` и пароль `admin` (или тот, что вы указали в `docker-compose.yml`).

### Шаг 5.2: Добавление Graphite как источника данных
1.  Перейдите в **Connections -> Data sources**.
2.  Нажмите **Add new data source**.
3.  Выберите **Graphite**.
4.  В поле **URL** укажите адрес вашего Graphite контейнера. Поскольку Grafana и Graphite находятся в одной Docker-сети, можно использовать имя сервиса из `docker-compose.yml`: `http://graphite:80`.
5.  Нажмите **Save & test**. Grafana должна сообщить об успешном подключении.

### Шаг 5.3: Создание дашборда
Теперь вы можете создавать дашборды, используя `Graphite` как источник данных. При создании панели в режиме запроса вы увидите иерархию метрик, поступающих от `collectd`, например: `collectd.имя_хоста.cpu-0.cpu-idle`.