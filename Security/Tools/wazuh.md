# Wazuh: Платформа XDR и SIEM для комплексной защиты

## Определения

**Wazuh** ([wazuh/wazuh](https://github.com/wazuh/wazuh)) — это полнофункциональная платформа с открытым исходным кодом для обеспечения безопасности конечных точек (Endpoints) и облачных инфраструктур. Она объединяет возможности **XDR** (Extended Detection and Response) и **SIEM** (Security Information and Event Management), позволяя предотвращать, обнаруживать и реагировать на угрозы в реальном времени.

Wazuh является глубоким форком проекта OSSEC, значительно расширившим возможности масштабирования, визуализации и интеграции с облачными провайдерами.

## Основные концепции

### Архитектура системы

Wazuh состоит из четырех центральных компонентов, которые могут быть развернуты как на одном сервере, так и в виде высокодоступного кластера:

1.  **Wazuh Agent**: Легковесный кроссплатформенный процесс, устанавливаемый на хосты.
2.  **Wazuh Manager (Server)**: Анализирует данные, декодирует логи и генерирует алерты.
3.  **Wazuh Indexer**: Индексирует и хранит события (на базе OpenSearch).
4.  **Wazuh Dashboard**: Веб-интерфейс для визуализации.

**Поддержка источников**:
- **Агенты**: Linux, Windows, macOS, Solaris.
- **Безагентный сбор**: сетевые устройства (Firewalls, Switches) через Syslog, SSH или API.

Подробности развертывания, порты и требования: **[Развертывание и архитектура Wazuh](./Wazuh/deployment.md)**.

### Конвейер обработки данных

Процесс анализа событий в Wazuh проходит через следующие этапы:
-   **Сбор (Collection)**: Агент считывает логи из файлов, журналов событий (Event Channel), команд или сетевых сокетов. Подробнее: [Сбор логов (Logcollector)](./Wazuh/wazuh-log-collection.md).
-   **Предварительное декодирование (Pre-decoding)**: Извлечение базовых метаданных (таймстемп, имя хоста, название программы).
-   **Декодирование (Decoding)**: Разбор тела сообщения на структурированные поля с использованием регулярных выражений. Подробнее: [Кастомные декодеры в Wazuh](./Wazuh/custom-decoders.md).
- **Сопоставление с правилами (Rule Matching)**: Анализ структурированных данных на соответствие условиям.
- **Корреляция событий (Correlation)**: Анализ последовательностей и частоты событий для обнаружения сложных атак. Подробнее: [Правила корреляции в Wazuh](./Wazuh/wazuh-rules.md).
- **Реагирование (Alerting/Response)**: Запись алерта в индекс и выполнение автоматических действий.


## Практические сценарии

### Установка на Debian 12 (Wazuh 4.x)

Среда: **Debian 12** (также применимо к **Ubuntu 22.04+**). В статье описывается развертывание Wazuh **4.14** в непривилегированном **LXC-контейнере** на Proxmox VE. Для работы в LXC добавьте опции в конфиг контейнера: `features: nesting=1` и `lxc.apparmor.profile: unconfined`. Непривилегированный контейнер с отключенным AppArmor безопаснее привилегированного, так как сохраняется изоляция через user namespace.

Схема работы сервера:

```
  [ Клиент (Linux/Windows/Роутер) ]
    | 1. Отправка лога по Syslog или Агентом
    v
  [ Wazuh Manager ]
    | 2. Принимает syslog или данные от агента
    | 3. Анализирует: Декодирует -> Применяет правила -> Генерирует АЛЕРТ
    | 4. Записывает алерт в локальный файл
    v
  [ Filebeat ]
    | 5. Читает новый алерт
    | 6. Формирует пакет и отправляет по защищенному каналу
    v
  [ Wazuh Indexer ]
    | 7. Принимает данные, индексирует их и сохраняет в своем хранилище
    v
  [ Wazuh Dashboard ]
    | 9. Делает запросы к Indexer
    | 10. Получает данные и рисует их на экране
    v
  [ ВЫ (Браузер) ]
    | 11. Смотрите графики и логи в веб-интерфейсе
```

По умолчанию **wazuh-manager** передает в **wazuh-indexer** только события, классифицированные как алерты. Остальные события, не соответствующие ни одному правилу, отбрасываются на этапе анализа и не сохраняются в базе данных.

Сравнение возможностей:

| Возможность | С агентом | Только syslog |
| --- | --- | --- |
| Сбор логов | ✅ Агент читает логи и отправляет их на сервер | ✅ Логи на сервер отправляет syslog |
| Алерты на основе логов | ✅ Да | ✅ Да |
| FIM (мониторинг изменения файлов) | ✅ Да | ❌ Нет |
| Rootkit detection | ✅ Да | ❌ Нет |
| Мониторинг процессов | ✅ Да | ❌ Нет |
| Inventory (список ПО) | ✅ Да | ❌ Нет |
| Vulnerability detector (поиск уязвимостей) | ✅ Да | ❌ Нет |
| Active Response (автоматическое реагирование) | ✅ Да | ❌ Нет |

#### Wazuh Manager

Установка зависимостей, импорт GPG-ключа и добавление репозитория:

```bash
apt install -y curl gnupg apt-transport-https
curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH \
 | gpg --no-default-keyring \
 --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import \
 && chmod 644 /usr/share/keyrings/wazuh.gpg
cat > /etc/apt/sources.list.d/wazuh.list << 'EOF'
deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main
EOF
```

Установка и запуск:

```bash
apt update && apt install -y wazuh-manager
systemctl daemon-reload
systemctl enable --now wazuh-manager
systemctl status wazuh-manager
```

#### Wazuh Indexer

Установка:

```bash
apt install -y wazuh-indexer
```

Основной конфиг — `/etc/wazuh-indexer/opensearch.yml`. Сгенерируйте SSL-сертификаты:

```bash
mkdir -p /tmp/wazuh-certs && cd /tmp/wazuh-certs
cat > config.yml << 'EOF'
nodes:
  indexer:
    - name: indexer
      ip: <YOUR_SERVER_IP>
  server:
    - name: server
      ip: <YOUR_SERVER_IP>
  dashboard:
    - name: dashboard
      ip: <YOUR_SERVER_IP>
EOF
curl -sO https://packages.wazuh.com/4.14/wazuh-certs-tool.sh
chmod 700 wazuh-certs-tool.sh
./wazuh-certs-tool.sh -A
```

Скопируйте SSL-сертификаты:

```bash
mkdir -p /etc/wazuh-indexer/certs
mkdir -p /etc/filebeat/certs
cp /tmp/wazuh-certs/wazuh-certificates/indexer.pem /etc/wazuh-indexer/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/indexer-key.pem /etc/wazuh-indexer/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/root-ca.pem /etc/wazuh-indexer/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/admin.pem /etc/wazuh-indexer/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/admin-key.pem /etc/wazuh-indexer/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/server.pem /etc/filebeat/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/server-key.pem /etc/filebeat/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/root-ca.pem /etc/filebeat/certs/
chown -R wazuh-indexer:wazuh-indexer /etc/wazuh-indexer/certs/
chmod 500 /etc/wazuh-indexer/certs/ && chmod 400 /etc/wazuh-indexer/certs/*
chown -R root:root /etc/filebeat/certs/
chmod 500 /etc/filebeat/certs/ && chmod 400 /etc/filebeat/certs/*
```

Запустите indexer и инициализируйте security-плагин:

```bash
systemctl daemon-reload
systemctl enable --now wazuh-indexer
systemctl status wazuh-indexer
/usr/share/wazuh-indexer/bin/indexer-security-init.sh
```

Смените пароли:

```bash
/usr/share/wazuh-indexer/plugins/opensearch-security/tools/wazuh-passwords-tool.sh --change-all
```

#### Wazuh Dashboard

Установка:

```bash
apt install -y wazuh-dashboard
```

Скопируйте сертификаты:

```bash
mkdir -p /etc/wazuh-dashboard/certs
cp /tmp/wazuh-certs/wazuh-certificates/dashboard.pem /etc/wazuh-dashboard/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/dashboard-key.pem /etc/wazuh-dashboard/certs/ && \
   cp /tmp/wazuh-certs/wazuh-certificates/root-ca.pem /etc/wazuh-dashboard/certs/
chown -R wazuh-dashboard:wazuh-dashboard /etc/wazuh-dashboard/certs/
chmod 500 /etc/wazuh-dashboard/certs/
chmod 400 /etc/wazuh-dashboard/certs/*
```

Настройка `/etc/wazuh-dashboard/opensearch_dashboards.yml`:

```yaml
opensearch.hosts: https://<IP-сервера>:9200
opensearch.username: kibanaserver
opensearch.password: '<пароль_kibanaserver>'
```

Запуск:

```bash
systemctl daemon-reload
systemctl enable --now wazuh-dashboard
systemctl status wazuh-dashboard
```

#### Filebeat

Установка:

```bash
apt install -y filebeat
```

Подключение модуля Wazuh:

```bash
mkdir -p /usr/share/filebeat/module/wazuh
cd /tmp
curl -LO https://packages.wazuh.com/4.x/filebeat/wazuh-filebeat-0.4.tar.gz
tar -xzf wazuh-filebeat-0.4.tar.gz -C /usr/share/filebeat/module/
ls /usr/share/filebeat/module/wazuh/
alerts  archives  @meta  module.yml
```

Шаблон индекса:

```bash
curl -so /etc/filebeat/wazuh-template.json \
  https://raw.githubusercontent.com/wazuh/wazuh/v4.14.0/extensions/elasticsearch/7.x/wazuh-template.json
chown root:root /etc/filebeat/wazuh-template.json
chmod 400 /etc/filebeat/wazuh-template.json
```

Конфигурация `/etc/filebeat/filebeat.yml`:

```yaml
seccomp.enabled: false
filebeat.modules:
  - module: wazuh
    alerts:
      enabled: true
setup.template.json.enabled: true
setup.template.json.path: '/etc/filebeat/wazuh-template.json'
setup.template.json.name: 'wazuh'
setup.template.overwrite: true
setup.ilm.enabled: false
setup.dashboards.enabled: false
output.elasticsearch:
  hosts: ["<IP-сервера>:9200"]
  protocol: https
  username: "admin"
  password: "<ваш_пароль>"
  ssl.certificate_authorities:
    - /etc/filebeat/certs/root-ca.pem
  ssl.certificate: "/etc/filebeat/certs/server.pem"
  ssl.key: "/etc/filebeat/certs/server-key.pem"
logging.level: info
logging.to_files: true
logging.files:
  path: /var/log/filebeat
  name: filebeat
  keepfiles: 7
  permissions: 0640
```

Запуск:

```bash
mkdir -p /var/log/filebeat
filebeat test config
systemctl daemon-reload
systemctl enable --now filebeat
systemctl status filebeat
filebeat setup -e
```

Примечание: команда `filebeat setup -e` может завершиться с ошибкой подключения к Kibana. Это ожидаемо — основная задача загрузки шаблона индекса. Подробнее: **[Сбор логов (Logcollector)](./Wazuh/wazuh-log-collection.md)).

#### Включение сбора логов по Syslog

Добавьте блок в `/var/ossec/etc/ossec.conf`:

```xml
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>udp</protocol>
  <allowed-ips>172.28.0.0/16</allowed-ips>
  <allowed-ips>10.0.0.0/8</allowed-ips>
  <allowed-ips>192.168.0.0/16</allowed-ips>
</remote>
```

Перезапустите wazuh-manager:

```bash
systemctl restart wazuh-manager
```

Проверка портов:

```bash
ss -tulpn | grep -E '514|1514'
```

#### LXC-специфика

Если вы устанавливаете Wazuh в непривилегированный контейнер LXC, добавьте в конфиг контейнера исключение для rootcheck:

```xml
<rootcheck>
  <ignore>/dev/.lxc/proc/sysrq-trigger</ignore>
  <ignore>/dev/.lxc-boot-id</ignore>
</rootcheck>
```

Перезапустите wazuh-manager:

```bash
systemctl restart wazuh-manager
```

### Мониторинг целостности файлов (FIM)

Wazuh отслеживает изменения в критических файлах и реестре Windows в режиме реального времени. Модуль **Syscheck** выявляет изменения контента, прав доступа и владельцев файлов, позволяя восстановить цепочку действий злоумышленника.
Подробнее: [Мониторинг целостности файлов через Wazuh](./Wazuh/wazuh-fim.md).

### Оценка конфигурации безопасности (SCA)

Модуль **SCA (Security Configuration Assessment)** выполняет автоматизированные проверки системы на соответствие стандартам (CIS Benchmarks) и лучшим практикам харденинга.
-   Проверка параметров ядра (`sysctl`).
-   Аудит настроек SSH и прав доступа к системным директориям.
-   Поиск небезопасных настроек в установленном ПО.

Подробнее: [Оценка конфигурации безопасности через Wazuh](./Wazuh/wazuh-sca.md).

### Обнаружение уязвимостей (Vulnerability Detector)

Модуль выполняет автоматический поиск известных дефектов безопасности (CVE) в операционной системе и установленных приложениях.
-   Инвентаризация пакетов через `syscollector`.
-   Сопоставление версий ПО с глобальными базами данных (NVD, RedHat, Canonical).
-   Учет установленных исправлений (hotfixes) для Windows.

Подробнее: [Обнаружение уязвимостей через Wazuh](./Wazuh/wazuh-vulnerability-detector.md).

### Безопасность облачных сред (Cloud Security)

Wazuh обеспечивает нативную интеграцию с основными облачными провайдерами:
-   **AWS**: Сбор и анализ логов CloudTrail, VPC Flow Logs, GuardDuty, аудит корзин S3.
-   **Azure**: Интеграция с Azure Graph, мониторинг событий AD и инфраструктуры.
-   **GCP**: Анализ логов Pub/Sub, мониторинг активности в Google Cloud.

### Мониторинг контейнеров и Kubernetes

-   **Инвентаризация**: Автоматический сбор данных о запущенных контейнерах, их образах и привилегиях.
-   **Runtime Security**: Обнаружение выполнения подозрительных команд внутри контейнеров через интеграцию с Docker API и событиями K8s.
Подробнее: [Мониторинг контейнеров через Wazuh](./Wazuh/container_monitoring.md) и [Мониторинг ядра (eBPF/Auditd)](./Wazuh/kernel_monitoring.md).

## Дополнительная информация

### Активное реагирование (Active Response)

Система позволяет автоматически блокировать атаки на ранних стадиях:
-   **Блокировка на уровне L3**: Блокировка IP-адреса через `iptables`, `nftables` или `firewalld` при обнаружении брутфорса.
-   **Взаимодействие с EDR**: Завершение вредоносных процессов или изоляция сетевого интерфейса хоста.
-   **Интеграция с YARA**: Автоматический запуск сканирования подозрительного файла при его создании/изменении.

### Автоматизация через Ansible (IaC)

Для управления парком из сотен агентов используется подход **Security as Code**. Ansible позволяет динамически управлять конфигурациями групп агентов, CDB-списками и уникальными исключениями.
Подробнее: [Автоматизация Wazuh через Ansible](./Wazuh/ansible-automation-per-agent.md).

### Интеграции в SOC-экосистему

-   **Authentik (SSO)**: Использование SAML для единого входа и управления ролями (RBAC). Подробнее: [Интеграция Authentik и Wazuh](./Wazuh/authentik-sso-integration.md).
-   **Zabbix**: Передача критических алертов в систему мониторинга для оперативного реагирования дежурных смен. Подробнее: [Интеграция Wazuh и Zabbix](./Wazuh/zabbix-integration.md).
-   **Telegram**: Оперативное оповещение администраторов через мессенджер с использованием кастомных Python-скриптов. Подробнее: [Интеграция Wazuh с Telegram](./Wazuh/telegram-integration.md).
-   **VirusTotal**: Автоматическая проверка хешей файлов через API для обогащения контекста алертов.

### Эксплуатация и контроль здоровья

Для обеспечения непрерывности мониторинга необходимо отслеживать состояние самой SIEM:
- Контроль подключения агентов через Dashboard и API.
- Настройка самодиагностики менеджера (Self-healing).
- Мониторинг системных ресурсов и очередей событий.

Подробнее: **[Мониторинг здоровья и самодиагностика Wazuh](./Wazuh/wazuh-health-monitoring.md)**.

### Операции и команды

Список агентов:

```bash
/var/ossec/bin/agent_control -l
```

Статистика алертов:

```bash
curl -k -u admin:<ваш_пароль> "https://<ip_сервера>:9200/wazuh-alerts-*/_count"
```

Последние алерты:

```bash
tail -f /var/ossec/logs/alerts/alerts.log
```

Логи filebeat:

```bash
journalctl -u filebeat -f
```

Логи indexer:

```bash
tail -f /var/log/wazuh-indexer/wazuh-cluster.log
```

Перезапустить все сервисы:

```bash
systemctl restart wazuh-manager wazuh-indexer wazuh-dashboard filebeat
```

Изменить пароль **kibanaserver**:

```bash
/usr/share/wazuh-indexer/plugins/opensearch-security/tools/wazuh-passwords-tool.sh -u kibanaserver -p '<новый_пароль>'
```

**kibanaserver** — служебный пользователь, через которого **Wazuh Dashboard** подключается к Indexer.

### Устранение неполадок

При установке на LXC может потребоваться отключение AppArmor. Если служба **wazuh-dashboard.service** показывает ошибки подключения к **wazuh-indexer** (например, `Authentication finally failed`), проблема в несовпадении паролей. В этом случае задайте пароль вручную:

```bash
/usr/share/wazuh-indexer/plugins/opensearch-security/tools/wazuh-passwords-tool.sh -u kibanaserver -p '<новый_пароль>'
```

Вставьте новый пароль в `/etc/wazuh-dashboard/opensearch_dashboards.yml` и перезапустите службу `wazuh-dashboard.service`. Перепроверьте статус службы и логи.

Проверка индексов:

```bash
curl -k -u admin:<ваш_пароль> https://<YOUR_SERVER_IP>:9200/_cat/indices?v
```

### См. также

- [Аудит и комплаенс (Audit & Compliance)](../audit_and_compliance_overview.md)
- [Харденинг ядра Linux](../../Linux/Security/Mechanisms/Kernel/hardening.md)
- [Falco: Runtime Security Monitoring](./falco.md)
- [Lynis: Аудит безопасности и харденинг Linux](./lynis.md)
