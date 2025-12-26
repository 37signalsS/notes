# Практическое руководство по установке Prometheus и Grafana

Данное руководство описывает практические шаги по установке. Для получения общей теоретической информации обратитесь к основным заметкам:
- **Prometheus:** [[../overview.md]]
- **Grafana:** [[../../Grafana/grafana_overview.md]]
- **Node Exporter:** [[../exporters.md]]

## 1. Общая схема

1.  **[[../overview.md|Prometheus Server]]**: Основной сервер, который собирает (scrape), хранит и обрабатывает метрики.
2.  **[[../exporters.md|Node Exporter]]**: Экспортер, который устанавливается на каждый отслеживаемый хост и собирает метрики операционной системы (CPU, RAM, диск и т.д.).
3.  **[[../../Grafana/grafana_overview.md|Grafana]]**: Платформа для визуализации данных, которая подключается к Prometheus и отображает метрики в виде наглядных дашбордов.

## 2. Установка компонентов на основной сервер

### Установка Prometheus и Node Exporter

```bash
# Устанавливаем Prometheus и Node Exporter из стандартных репозиториев
# Общие принципы работы с пакетными менеджерами, такими как apt, описаны в [[../../Linux/PackageManagement/linux_package_management_overview.md|обзоре управления пакетами в Linux]].
sudo apt update
sudo apt install prometheus prometheus-node-exporter
```

После установки система автоматически запустит два сервиса (подробнее об управлении службами см. в [[../../Linux/Core/systemd/service_management.md|руководстве по управлению службами Systemd]]):

*   `prometheus.service`
*   `prometheus-node-exporter.service`

Проверим, что они слушают нужные порты:

```bash
ss -tnlp
```
В выводе должны появиться:

*   `*:9090` — веб-интерфейс и API Prometheus.
*   `*:9100` — эндпоинт с метриками от Node Exporter.

На этом этапе Prometheus уже собирает метрики сам с себя. Это можно проверить, открыв в браузере `http://<ip_сервера>:9090`. Во вкладке **Status -> Targets** будет виден один эндпоинт (`localhost:9100`) со статусом `UP`.

### Установка Grafana

```bash
# Добавление репозитория Grafana и установка
sudo apt-get install -y apt-transport-https software-properties-common wget
sudo wget -q -O /usr/share/keyrings/grafana.key https://apt.grafana.com/gpg.key
echo "deb [signed-by=/usr/share/keyrings/grafana.key] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list

sudo apt-get update
sudo apt-get install grafana
```

После установки Grafana не запустится автоматически. Запустим и добавим в автозагрузку:

```bash
sudo systemctl start grafana-server
sudo systemctl enable grafana-server
```

Проверяем порт `3000`:

```bash
ss -tnlp | grep 3000
```
Теперь Grafana доступна по адресу `http://<ip_сервера>:3000`.

## 3. Настройка Grafana

1.  **Вход в систему**:
    *   Откройте `http://<ip_сервера>:3000`.
    *   Логин/пароль по умолчанию: `admin`/`admin`.
    *   Система предложит сменить пароль.

2.  **Добавление источника данных (Data Source)**:
    *   Перейдите в **Configuration (значок шестеренки) -> Data Sources**.
    *   Нажмите **Add data source**.
    *   Выберите **Prometheus**.
    *   В поле **URL** укажите адрес вашего Prometheus-сервера: `http://localhost:9090`.
    *   Нажмите **Save & test**. Должно появиться сообщение "Data source is working".

3.  **Импорт дашборда**:
    *   Grafana имеет огромное сообщество, которое создает готовые дашборды. Мы воспользуемся популярным дашбордом для Node Exporter. Процесс импорта и управления дашбордами подробно описан в руководстве [[../../Grafana/grafana_dashboards.md|Дашборды в Grafana]].
    *   Перейдите в **Dashboards (значок четырех квадратов) -> Browse**.
    *   Нажмите **Import**.
    *   В поле "Import via grafana.com" введите ID дашборда: `1860` и нажмите **Load**.
    *   На следующей странице внизу выберите ваш источник данных Prometheus.
    *   Нажмите **Import**.

## 4. Добавление нового хоста для мониторинга

### На целевом хосте

Нам нужно установить только **Node Exporter**, так как он будет лишь поставлять метрики.

```bash
# На целевом хосте
sudo apt update
sudo apt install prometheus-node-exporter
```

Убедитесь, что сервис запущен и порт `9100` слушается. Проверьте, что с сервера мониторинга есть сетевой доступ к эндпоинту с метриками. Для этого можно использовать `curl`:

```bash
# На сервере мониторинга
curl http://<ip_целевого_хоста>:9100/metrics
```
В ответ вы должны получить большой текстовый вывод с метриками. Если команда завершается ошибкой (например, `Connection refused`), проверьте сетевые правила и статус сервиса `prometheus-node-exporter` на целевом хосте.

### На сервере мониторинга

Нужно сообщить Prometheus, что ему следует опрашивать новый хост.

1.  **Найти конфигурационный файл Prometheus**:
    Чтобы найти путь к конфигу, можно использовать `help` самого бинарного файла, но вывод может идти в `stderr`.
    ```bash
    /usr/bin/prometheus --help 2>&1 | grep 'config.file'
    # Вывод покажет путь, обычно /etc/prometheus/prometheus.yml
    ```

2.  **Отредактировать `prometheus.yml`**:
    Откройте файл `/etc/prometheus/prometheus.yml`. Детальное описание структуры конфигурационного файла и его директив можно найти в заметке [[../configuration.md|Конфигурация Prometheus]]. Найдите секцию `scrape_configs` и `job_name: 'node'`. Добавьте адрес нового хоста в список `targets`.

    ```yaml
    # ...
    scrape_configs:
      - job_name: "prometheus"
        static_configs:
          - targets: ["localhost:9090"]

      - job_name: "node"
        static_configs:
          - targets: ["localhost:9100", "192.168.1.100:9100"] # <-- Добавьте сюда IP:порт вашего хоста
    ```

3.  **Перезагрузить конфигурацию Prometheus**:
    Prometheus может перезагружать конфигурацию без перезапуска сервиса.
    ```bash
    # Отправляем сигнал HUP процессу Prometheus
    sudo killall -HUP prometheus
    ```
    *Или можно просто перезапустить сервис: `sudo systemctl restart prometheus.service`.*

4.  **Проверка**:
    *   Вернитесь в веб-интерфейс Prometheus (**Status -> Targets**). Через некоторое время в списке `node` появится новый хост.
    *   В дашборде Grafana в выпадающем списке `Node` вверху слева теперь можно будет выбрать новый хост и посмотреть его метрики.

## 5. (Опционально) Настройка Nginx как обратного прокси для Grafana

Чтобы обращаться к Grafana по стандартному 80-му порту, а не по 3000, можно настроить [[../../WebServers/Nginx/Core/nginx_overview.md|Nginx]].

1.  **Установите Nginx**:
    ```bash
    sudo apt install nginx
    ```

2.  **Настройте конфигурацию сайта**:
    Отредактируйте файл `/etc/nginx/sites-available/default`.
    **Важно:** стандартная директива `try_files` в `location /` конфликтует с Grafana. Ее нужно закомментировать или удалить.

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
        }
    }
    ```

3.  **Перезапустите Nginx**:
    ```bash
    sudo systemctl restart nginx
    ```

Теперь Grafana будет доступна по адресу `http://<ip_сервера>`.

Подробное руководство по этой теме: [[../../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md]].

