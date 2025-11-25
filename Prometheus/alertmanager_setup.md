# Установка и настройка Alertmanager

## Установка Alertmanager

*Этот раздел представляет собой практическое руководство по установке.*

Практика выполняется на сервере мониторинга с root-привилегиями.

1.  **Создаем пользователя `alertmanager`:**
    ```bash
    adduser --comment "User to run Alertmanager" --shell /bin/false alertmanager 
    ```
    Для запуска Alertmanager не требуются root-привилегии, и с точки зрения безопасности лучше его запускать от непривилегированного пользователя.

2.  **Скачиваем и распаковываем архив:**
    Используется версия `0.21.0`. Список актуальных версий можно посмотреть на [странице GitHub](https://github.com/prometheus/alertmanager/releases).
    ```bash
    cd /tmp
    wget https://github.com/prometheus/alertmanager/releases/download/v0.21.0/alertmanager-0.21.0.linux-amd64.tar.gz
    tar xvfz alertmanager-0.21.0.linux-amd64.tar.gz
    cd alertmanager-0.21.0.linux-amd64
    mv alertmanager /usr/local/bin/
    ```

3.  **Создаем каталоги и копируем конфигурацию:**
    ```bash
    mkdir /etc/alertmanager          
    cp alertmanager.yml /etc/alertmanager/alertmanager.yml 
    chown alertmanager:alertmanager -R /etc/alertmanager
    ```

4.  **Создаем каталог для данных:**
    ```bash
    mkdir /var/lib/alertmanager/
    chown alertmanager:alertmanager /var/lib/alertmanager/  
    ```

5.  **Создаем файл с опциями запуска:**
    Ключи запуска выносятся в файл `/etc/sysconfig/alertmanager` для удобства.
    ```bash
    cat <<EOF > /etc/sysconfig/alertmanager
    OPTIONS="--config.file=/etc/alertmanager/alertmanager.yml \
      --storage.path=/var/lib/alertmanager/"
    EOF
    ```

6.  **Создаем systemd-сервис:**
    ```bash
    cat <<EOF > /usr/lib/systemd/system/alertmanager.service 
    [Unit]
    Description=Prometheus Alertmanager
    Documentation=https://github.com/alertmanager/alertmanager

    [Service]
    User=alertmanager
    Group=alertmanager
    Restart=always
    EnvironmentFile=/etc/sysconfig/alertmanager
    ExecStart=/usr/local/bin/alertmanager $OPTIONS
    ExecReload=/bin/kill -HUP $MAINPID
    TimeoutStopSec=20s
    SendSIGKILL=no

    [Install]
    WantedBy=multi-user.target
    EOF
    ```

7.  **Запускаем Alertmanager:**
    ```bash
    systemctl daemon-reload
    systemctl start alertmanager.service
    systemctl enable alertmanager.service
    ```

8.  **Проверяем работу:**
    По умолчанию Alertmanager слушает порт `9093`.
    ```bash
    curl -LI -XGET http://localhost:9093
    ```

9.  **Интегрируем с Prometheus:**
    Добавьте секцию `alerting` в `prometheus.yml`.
    ```yaml
    # /etc/prometheus/prometheus.yml
    alerting:
      alertmanagers:
        - static_configs: 
           - targets: 
              - 'localhost:9093'
    ```

10. **Проверяем и перезагружаем Prometheus:**
    ```bash
    promtool check config /etc/prometheus/prometheus.yml
    systemctl reload prometheus.service
    ```

## Ключи запуска Alertmanager

| Ключ | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `alertmanager.yml` | Имя конфигурационного файла. |
| `--storage.path` | `data/` | Путь, куда сохраняются данные. |
| `--data.retention` | `120h` | Как долго хранить данные. |
| `--web.listen-address` | `:9093` | Адрес и порт, по которому доступны UI и метрики Alertmanager. |
| `--cluster.listen-address` | `"0.0.0.0:9094"` | Адрес для HA кластера. Пустое значение для отключения HA. |
| `--cluster.peer` | `-` | Адреса пиров в HA кластере. |
| `--log.level` | `info` | Уровень логирования: `debug`, `info`, `warn`, `error`. |
| `--log.format` | `logfmt` | Формат логов: `logfmt`, `json`. |

## Настройка конфигурационного файла `alertmanager.yml`

### Блок `global`

Здесь объявляются глобальные параметры по умолчанию.

*   `resolve_timeout`: (default: `5m`) Время, через которое алерт считается решенным, если он не был обновлен.
*   `smtp_from`: email-адрес отправителя по умолчанию.
*   `smtp_smarthost`: SMTP-сервер по умолчанию (формат: `ip:port`).
*   `smtp_require_tls`: (default: `true`) Использовать ли TLS при подключении к SMTP.

### Блок `route`

В этом блоке настраивается древовидная структура маршрутизации оповещений.

*   `receiver`: Имя получателя по умолчанию для корневого маршрута.
*   `group_by`: Набор меток для агрегации алертов. `['...']` отключает группировку.
*   `continue`: (default: `false`) Если `false`, обработка прекращается при первом совпадении. Если `true`, продолжается до последнего совпадения.
*   `match` / `match_re`: Список меток для точного или regex-совпадения, определяющий выбор маршрута.
*   `group_wait`: (default: `30s`) Время ожидания перед отправкой группы алертов.
*   `group_interval`: (default: `5m`) Время задержки для отправки новых уведомлений для уже сработавшей группы.
*   `repeat_interval`: (default: `4h`) Время задержки для повторной отправки уведомления.
*   `routes`: Вложенные маршруты.

**Пример:**
```yaml
route:
  receiver: 'default-receiver'
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  group_by: [cluster, alertname]
  routes:
  - receiver: 'db-team'
    group_wait: 10s
    match_re:
      service: mysql|postgres
  - receiver: 'frontend-team'
    group_by: [product, environment]
    match:
      team: frontend
```

### Блок `receivers`

Именованная конфигурация одного или нескольких получателей (email, Slack, PagerDuty, webhook и др.).

### Блок `inhibit_rules`

Позволяет подавлять одни алерты при наличии других.

*   `target_match` / `target_match_re`: Метки алерта, который будет подавлен.
*   `source_match` / `source_match_re`: Метки алерта, который должен уже существовать для срабатывания правила.
*   `equal`: Набор меток, которые должны совпадать в обоих алертах.

### Блок `templates`

Список путей к файлам с пользовательскими шаблонами уведомлений.

---
**Связанные темы:**
*   [[./alertmanager_overview.md]]
*   [[./alertmanager_ha.md]]
*   [[./alerting_rules.md]]
