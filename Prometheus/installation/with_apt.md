# Установка Prometheus и Grafana с использованием APT

---

### 1. Определения

*   **Prometheus Server**: Основной сервер, который собирает (scrape), хранит и обрабатывает метрики.
*   **Node Exporter**: Экспортер, устанавливаемый на отслеживаемые хосты для сбора метрик операционной системы (CPU, RAM, диск, сеть и т.д.).
*   **Grafana**: Платформа для визуализации данных, подключающаяся к Prometheus для отображения метрик в виде наглядных дашбордов.

---

### 2. Основные концепции

#### Общая схема мониторинга

1.  **Сбор метрик**: `Node Exporter` собирает метрики с отслеживаемых серверов и предоставляет их по HTTP.
2.  **Хранение и обработка**: `Prometheus Server` периодически опрашивает (scrape) `Node Exporter` и другие цели, сохраняя полученные метрики в своей временной базе данных (TSDB).
3.  **Визуализация**: `Grafana` подключается к `Prometheus Server` как к источнику данных и используется для построения графиков, дашбордов и анализа метрик.

#### Преимущества установки через APT

Установка через менеджер пакетов `apt` (для дистрибутивов на базе Debian/Ubuntu) упрощает процесс развертывания, обновления и управления сервисами, так как пакеты уже сконфигурированы для работы с `systemd`.

---

### 3. Практические сценарии

#### Установка компонентов на основной сервер

1.  **Обновление списка пакетов**:
    ```bash
    sudo apt update
    ```

2.  **Установка Prometheus Server и Node Exporter**:
    ```bash
    sudo apt install prometheus prometheus-node-exporter
    ```
    После установки `systemd` автоматически запустит сервисы `prometheus.service` и `prometheus-node-exporter.service`.

3.  **Проверка доступности Prometheus и Node Exporter**:
    Используйте утилиту `ss` для проверки открытых портов:
    ```bash
    ss -tnlp
    ```
    В выводе должны быть порты:
    *   `*:9090` — веб-интерфейс и API Prometheus Server.
    *   `*:9100` — эндпоинт метрик Node Exporter (собственного, на сервере мониторинга).

    Проверьте веб-интерфейс Prometheus по адресу `http://<ip_сервера>:9090`. На вкладке **Status -> Targets** должен быть виден `localhost:9100` со статусом `UP`.

4.  **Установка Grafana**:
    ```bash
    # Добавление репозитория Grafana и установка
    sudo apt-get install -y apt-transport-https software-properties-common wget
    sudo wget -q -O /usr/share/keyrings/grafana.key https://apt.grafana.com/gpg.key
    echo "deb [signed-by=/usr/share/keyrings/grafana.key] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list

    sudo apt-get update
    sudo apt-get install grafana
    ```
    После установки Grafana не запустится автоматически.

5.  **Запуск и включение автозапуска Grafana**:
    ```bash
    sudo systemctl start grafana-server
    sudo systemctl enable grafana-server
    ```

6.  **Проверка доступности Grafana**:
    ```bash
    ss -tnlp | grep 3000
    ```
    Grafana должна быть доступна по адресу `http://<ip_сервера>:3000`.

#### Настройка Grafana

1.  **Первый вход в систему**:
    *   Откройте `http://<ip_сервера>:3000`.
    *   Используйте логин/пароль по умолчанию: `admin`/`admin`.
    *   Система предложит сменить пароль.

2.  **Добавление источника данных Prometheus**:
    *   Перейдите в **Configuration (значок шестеренки) -> Data Sources**.
    *   Нажмите **Add data source** и выберите **Prometheus**.
    *   В поле **URL** укажите адрес вашего Prometheus-сервера: `http://localhost:9090`.
    *   Нажмите **Save & test**. Должно появиться сообщение "Data source is working".

3.  **Импорт дашборда Node Exporter Full**:
    *   Перейдите в **Dashboards (значок четырех квадратов) -> Browse**.
    *   Нажмите **Import**.
    *   В поле "Import via grafana.com" введите ID дашборда: `1860` (популярный дашборд для Node Exporter) и нажмите **Load**.
    *   На следующей странице в выпадающем списке выберите ваш источник данных Prometheus.
    *   Нажмите **Import**.

#### Добавление нового хоста для мониторинга

1.  **На целевом хосте (Node Exporter)**:
    Установите `Node Exporter` на целевой хост, который вы хотите мониторить:
    ```bash
    sudo apt update
    sudo apt install prometheus-node-exporter
    ```
    Убедитесь, что сервис запущен и порт `9100` слушается. Проверьте сетевой доступ с сервера мониторинга:
    ```bash
    # На сервере мониторинга
    curl http://<ip_целевого_хоста>:9100/metrics
    ```
    Вы должны получить большой текстовый вывод с метриками.

2.  **На сервере мониторинга (Prometheus Server)**:
    *   Найдите конфигурационный файл Prometheus:
        ```bash
        /usr/bin/prometheus --help 2>&1 | grep 'config.file'
        # Обычно это /etc/prometheus/prometheus.yml
        ```
    *   Отредактируйте `/etc/prometheus/prometheus.yml`, добавив новый хост в секцию `scrape_configs` для `job_name: "node"`:
        ```yaml
        # ...
        scrape_configs:
          - job_name: "prometheus"
            static_configs:
              - targets: ["localhost:9090"]

          - job_name: "node"
            static_configs:
              - targets: ["localhost:9100", "192.168.1.100:9100"] # <-- Добавьте IP:порт вашего хоста
        ```
    *   Перезагрузите конфигурацию Prometheus (без перезапуска сервиса):
        ```bash
        sudo killall -HUP prometheus
        ```
        *Или: `sudo systemctl reload prometheus.service`*
    *   **Проверка**: Вернитесь в веб-интерфейс Prometheus (**Status -> Targets**). Новый хост должен появиться в списке `node` со статусом `UP`. В дашборде Grafana вы сможете выбрать его из выпадающего списка `Node`.

#### (Опционально) Настройка Nginx как обратного прокси для Grafana

Для доступа к Grafana по стандартному 80-му порту вместо 3000 можно настроить [Nginx](../../WebServers/Nginx/Core/nginx_overview.md).

1.  **Установите Nginx**:
    ```bash
    sudo apt install nginx
    ```

2.  **Настройте конфигурацию сайта**:
    Отредактируйте файл `/etc/nginx/sites-available/default`. **Важно**: закомментируйте или удалите стандартную директиву `try_files` в `location /`.
    ```nginx
    server {
        listen 80 default_server;
        listen [::]:80 default_server;

        root /var/www/html;
        index index.html index.htm index.nginx-debian.html;

        server_name _;

        location / {
                # try_files $uri $uri/ =404; # <-- Закомментировать эту строку
                proxy_pass http://localhost:3000;
                proxy_set_header Host \$host;
                proxy_set_header X-Real-IP \$remote_addr;
                proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto \$scheme;
        }
    }
    ```

3.  **Перезапустите Nginx**:
    ```bash
    sudo systemctl restart nginx
    ```
    Теперь Grafana будет доступна по адресу `http://<ip_сервера>`. Подробное руководство по этой теме: [[../../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md]].

---

### 4. Дополнительная информация

*   **Prometheus**: Общая информация об архитектуре и компонентах [[../overview.md]].
*   **Grafana**: Полный обзор возможностей и функций платформы [[../../Grafana/grafana_overview.md]].
*   **Node Exporter**: Детальное описание и настройка [[../exporters.md]].
*   **Управление пакетами в Linux**: Принципы работы `apt` и других пакетных менеджеров [[../../Linux/PackageManagement/linux_package_management_overview.md]].
*   **Управление службами Systemd**: Подробное руководство по `systemctl` [[../../Linux/Core/systemd/service_management.md]].
*   **Конфигурация Prometheus**: Детальное описание директив `prometheus.yml` [[../configuration.md]].
*   **Дашборды в Grafana**: Создание, импорт и управление дашбордами [[../../Grafana/grafana_dashboards.md]].
*   **Утилита `ss`**: Подробнее о проверке сетевых соединений [[../../Linux/Diagnostics/Networking/ss.md]].