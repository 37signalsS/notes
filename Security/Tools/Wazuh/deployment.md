# Развертывание и архитектура Wazuh

## Определения

**Развертывание Wazuh** — комплексный процесс инсталляции и настройки узлов платформы безопасности. С 2026 года (версия **Wazuh 5.0+**) процесс ориентирован на создание высокопроизводительной аналитической среды на базе OpenSearch 3.x, обеспечивающей полную видимость событий (Full Visibility).

**Wazuh-Engine** — современное аналитическое ядро (написано на C++), пришедшее на смену классическому `wazuh-analysisd`. Интегрировано напрямую в процесс индексатора для минимизации задержек при обработке миллионов событий в секунду (EPS).

**Wazuh Indexer** — высокомасштабируемое хранилище данных на базе **OpenSearch 3.x**, оптимизированное для поиска по метаданным безопасности и быстрого полнотекстового поиска.

**Wazuh Server (Manager)** — узел управления агентами, отвечающий за регистрацию, инвентаризацию активов, оркестрацию API и хранение конфигураций.

**Wazuh Dashboard** — визуальный интерфейс управления на базе OpenSearch Dashboards, поддерживающий нативную работу с событиями **wazuh-events** и алертами.

**mTLS (mutual TLS)** — механизм взаимной аутентификации между агентом и менеджером, при котором обе стороны представляют и проверяют сертификаты. В Wazuh 5.0 используется по умолчанию для портов 1514/1515.

**Certificate Authority (CA) Wazuh** — корневой центр сертификации, создаваемый ассистентом установки. Подписывает сертификаты менеджера, индексатора, дашборда и агентов.

**Ассистент установки (Installation Assistant)** — скрипт `wazuh-install.sh` и архив `wazuh-install-files.tar`, автоматизирующие генерацию сертификатов, конфигураций и развертывание кластера.

**Диспетчер индексов (Index State Management / ISM)** — механизм OpenSearch 3.x для автоматического управления жизненным циклом индексов: переход между горячим/теплым/холодным/удаленным состояниями по времени или размеру.

**Full Visibility** — модель хранения всех сырых событий (`wazuh-events-*`), а не только сработавших алертов, что критично для ретроспективного анализа (Threat Hunting).

## Основные концепции

### Жизненный цикл развертывания

Понимание этапов установки необходимо для диагностики и автоматизации:

1.  **Pre-flight**: проверка оборудования, ОС, сетевой доступности и открытых портов. На этом этапе выполняется `wazuh-install.sh --check` или ручная верификация зависимостей.
2.  **Генерация артефактов**: на мастер-узле ассистент создает CA, сертификаты узлов и архив `wazuh-install-files.tar`.
3.  **Распространение**: архив копируется на остальные узлы кластера (Indexer, Dashboard, Manager Workers).
4.  **Установка Indexer**: первый устанавливаемый компонент, так как Dashboard и Manager зависят от него.
5.  **Установка Dashboard**: требует доступности Indexer и валидных сертификатов.
6.  **Установка Manager**: может выполняться на отдельном узле или совместно с Dashboard/Indexer в All-in-one режиме.
7.  **Регистрация агентов**: после запуска Manager агенты подключаются по порту 1515, получают сертификаты и начинают передачу событий по 1514.
8.  **Валидация**: проверка статусов сервисов, подключения агентов и появления событий в Dashboard.

### Архитектура взаимодействия компонентов (Wazuh 5.0+)

В версии 5.0 архитектура эволюционировала от «сборщика логов» к **платформе данных безопасности**:

- **Агенты**: используют протокол **Delta-синхронизации** для передачи изменений инвентаря и логов, снижая нагрузку на сеть.
- **Wazuh-Engine SSoT**: фильтрация, обогащение (GeoIP, CTI) и корреляция (Sigma) теперь происходят на уровне движка данных.
- **Full Visibility**: система сохраняет все события (`wazuh-events-*`), а не только сработавшие алерты, что критично для ретроспективного анализа (Threat Hunting).
- **Кластерная синхронизация**: в 5.0 отсутствует разделение на режимы работы; подсистема кластера активна всегда, что обеспечивает мгновенную синхронизацию состояний между всеми узлами менеджера.

### Управление сертификатами

В Wazuh 5.0 сертификаты управляются через инструмент `wazuh-security` и каталог `/var/wazuh-manager/etc/certs/`:

- **Срок действия**: по умолчанию 10 лет для CA, 5 лет для серверных сертификатов, 1 год для агентских.
- **Ротация**: выполняется через `wazuh-security` или повторный запуск ассистента с флагом `--renew-certificates`.
- **Хранение**: критически важно иметь резервную копию CA (`/var/wazuh-manager/etc/certs/root-ca.pem`). Без него невозможно выпустить новый сертификат для агента или узла.
- **Проверка**: `openssl x509 -in /var/wazuh-manager/etc/certs/admin.pem -noout -dates`.

### High Availability (HA)

Для production-сред Wazuh 5.0 поддерживает кластеризацию:

- **Manager HA**: несколько узлов Manager в кластере с балансировкой агентов через DNS Round-Robin или HAProxy/Keepalived. Агенты автоматически переподключаются к доступному узлу.
- **Indexer HA**: кластер OpenSearch 3.x минимум из 3 узлов (1 primary + 2 replicas) для отказоустойчивости. Рекомендуется 3 узла для малых и средних сред.
- **Dashboard HA**: несколько экземпляров Dashboard за балансировщиком (nginx/HAProxy) с sticky-sessions или без них (статeless).

### Безопасность инфраструктуры Wazuh

Развертывание Wazuh само по себе является критической инфраструктурой и требует hardening:

- **Сеть**: изолируйте управляющий трафик (1514/1515/55000) в отдельный сегмент/VLAN. Запретите доступ из Интернета.
- **Хосты**: минимальная ОС, только необходимые пакеты, включенный firewall (`ufw`/`firewalld`), отключенный SSH парольный вход.
- **Права**: сервисы Wazuh работают от имени пользователя `wazuh`/`wazuh-indexer`. Никогда не запускайте их от root.
- **Шифрование**: mTLS обязателен. Отключите небезопасные протоколы (TLS 1.0/1.1) в конфигурации OpenSearch.
- **Резервное копирование**: регулярно бэкапьте `/var/wazuh-manager/etc/`, `/var/wazuh-manager/integrations/`, `/var/wazuh-indexer/` и CA.

### Хранение данных и retention

С переходом на модель **Full Visibility** (хранение всех событий) объем данных вырос в 4–6 раз по сравнению с алерт-моделью 4.x.

**Рекомендуемые настройки ISM (Index State Management):**
- **Горячий (Hot)**: 7 дней на NVMe/SSD (активные запросы).
- **Теплый (Warm)**: 30 дней на SSD (редкие запросы).
- **Холодный (Cold)**: 90–365 дней на HDD/S3-совместимое хранилище (архив, compliance).
- **Удаление (Delete)**: по истечении retention-периода.

### Требования к оборудованию

С внедрением Wazuh-Engine требования к ресурсам (особенно RAM) возросли для обеспечения стабильности OpenSearch 3.x.

**Пример требований для All-in-one (до 100 агентов, 2026 год):**

| Количество агентов | CPU (cores) | RAM (GB) | Диск (NVMe рекомендуется) |
| :--- | :--- | :--- | :--- |
| 1–25 | 4 | 12 | 100 GB |
| 25–100 | 8 | 24 | 300 GB |
| 100–500 | 16 | 48 | 1 TB+ |

*Примечание: Использование HDD крайне не рекомендуется из-за высокой интенсивности операций ввода-вывода (IOPS) в OpenSearch 3.x. Для >500 агентов используйте раздельную архитектуру с выделенными узлами Indexer.*

### Сетевые порты

| Компонент | Порт | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| **Агент ↔ Менеджер** | 1514 | TCP | Передача событий (mTLS по умолчанию) |
| **Агент ↔ Менеджер** | 1515 | TCP | Регистрация и получение сертификатов |
| **Engine ↔ Indexer** | 9200 | TCP | Внутренняя шина данных (Native) |
| **Dashboard ↔ Indexer** | 9200 | TCP | API-запросы визуализации |
| **Dashboard ↔ Пользователь** | 443 | TCP | HTTPS веб-интерфейс |
| **OTLP Receiver** | 4317/4318 | gRPC/HTTP | Сбор OpenTelemetry сигналов (Wazuh 5.0+) |
| **REST API** | 55000 | TCP | Управление агентами и конфигурацией (HTTPS) |

### Поддерживаемые ОС (2026)
- Ubuntu 24.04 LTS (рекомендуется)
- RHEL 9, 10
- Debian 12
- Amazon Linux 2023

## Практические сценарии

### 0. Pre-flight проверка

Перед установкой выполните проверку окружения:

```bash
#!/bin/bash
set -euo pipefail

echo "=== Wazuh 5.0 Pre-flight Check ==="

# ОС
if [ -f /etc/os-release ]; then
  . /etc/os-release
  echo "OS: $NAME $VERSION"
fi

# Ресурсы
CORES=$(nproc)
RAM_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1024 / 1024 ))
echo "CPU cores: $CORES"
echo "RAM: ${RAM_GB}GB"

if [ "$CORES" -lt 4 ] || [ "$RAM_GB" -lt 12 ]; then
  echo "ERROR: Минимум 4 cores и 12GB RAM для All-in-one"
  exit 1
fi

# Порты
for port in 1514 1515 443 55000 9200; do
  if ss -tlnp | grep -q ":$port "; then
    echo "WARNING: Порт $port уже занят"
  fi
done

# DNS
echo "DNS resolution test:"
getent hosts packages.wazuh.com || echo "WARNING: DNS не разрешает packages.wazuh.com"

# SELinux
if command -v getenforce &>/dev/null; then
  echo "SELinux: $(getenforce)"
fi

echo "=== Pre-flight OK ==="
```

### 1. Установка «все в одном» (All-in-one)

Идеально для POC (Proof of Concept) и малых офисов.

```bash
curl -sO https://packages.wazuh.com/5.x/installation-assistant/wazuh-install.sh
sudo bash ./wazuh-install.sh -a
```
# → Скрипт установит OpenSearch 3.x, Wazuh-Engine и Dashboard. Сохраните пароль из файла /var/wazuh-manager/etc/wazuh-passwords.txt.

**Постустановочная проверка:**
```bash
sudo systemctl status wazuh-manager wazuh-indexer opensearch-dashboard
sudo /var/wazuh-manager/bin/wazuh-control status
# → Ожидаем: wazuh-manager running, wazuh-indexer running
```

### 2. Распределенная установка (Production)

В 2026 году стандарт де-факто — разделение уровней хранения и управления.

#### Шаг А: Подготовка конфигурации
```bash
curl -sO https://packages.wazuh.com/5.x/installation-assistant/config.yml
```

Отредактируйте `config.yml`, включив поддержку `wazuh-engine` на узлах индексатора:
```yaml
nodes:
  indexer:
    - name: indexer-node-1
      ip: "10.0.0.10"
      engine_enabled: true
  server:
    - name: manager-master
      ip: "10.0.0.20"
  dashboard:
    - name: wazuh-dashboard
      ip: "10.0.0.30"
```

#### Шаг Б: Установка
Выполните развертывание последовательно. В Wazuh 5.0 сертификаты генерируются автоматически в рамках запуска ассистента на мастере.

```bash
# На мастере менеджере:
sudo bash wazuh-install.sh --generate-config-files
# → Перенесите архив wazuh-install-files.tar на остальные узлы.

# На узлах Indexer:
sudo bash wazuh-install.sh --wazuh-indexer indexer-node-1

# На узле Dashboard:
sudo bash wazuh-install.sh --wazuh-dashboard

# На дополнительных узлах Manager:
sudo bash wazuh-install.sh --wazuh-manager
```

### 3. Установка агентов

Существует два основных способа добавления хостов в Wazuh: через веб-интерфейс Dashboard (мастер **Deploy new agent**) и через CLI-инструменты. Мастер автоматически генерирует команду установки с подставленными IP менеджера и именем агента, что упрощает подключение отдельных хостов. Для массового развертывания используйте Ansible (см. [Массовая установка агентов](./wazuh-mass-deployment.md)).

#### 3.1 Через веб-интерфейс

В Dashboard перейдите в **Agent management / Summary** → **Deploy new agent**:

1. Укажите адрес **сервера Wazuh** (менеджера), а не целевого хоста.
2. Задайте имя агента (рекомендуется использовать hostname хоста).
3. Скопируйте сгенерированную команду и выполните её на целевом хосте.

##### Linux (Debian/Ubuntu)

```bash
wget https://packages.wazuh.com/5.x/apt/pool/main/w/wazuh-agent/wazuh-agent_5.x.y-1_amd64.deb \
    && sudo WAZUH_MANAGER='<IP-SRV-WAZUH>' \
    WAZUH_AGENT_NAME='srv-debian' \
    dpkg -i ./wazuh-agent_5.x.y-1_amd64.deb

sudo systemctl daemon-reload
sudo systemctl enable wazuh-agent
sudo systemctl start wazuh-agent

# Проверка статуса
systemctl status wazuh-agent
# → active (running)
```

##### Windows

```powershell
# Скачивание и установка MSI
Invoke-WebRequest -Uri https://packages.wazuh.com/5.x/windows/wazuh-agent-5.x.y-1.msi -OutFile $env:tmp\wazuh-agent.msi
msiexec.exe /i $env:tmp\wazuh-agent.msi /q WAZUH_MANAGER="<IP-SRV-WAZUH>" WAZUH_AGENT_NAME="srv-win10"

# Запуск службы
Start-Service -Name Wazuh
```

> **Важно:** `Invoke-WebRequest` может не работать из-за политик выполнения PowerShell. Если скачивание не удалось, загрузите MSI вручную через браузер и выполните:
> ```powershell
> msiexec.exe /i "$env:USERPROFILE\Downloads\wazuh-agent-5.x.y-1.msi" /q WAZUH_MANAGER="<IP-SRV-WAZUH>" WAZUH_AGENT_NAME="srv-win10"
> ```

После установки откройте **Manage Agent** в меню Пуск и убедитесь, что статус — **Running**. Вернитесь в Dashboard и нажмите **Back to agent list**, чтобы увидеть нового агента в списке.

#### 3.2 Через CLI (автоматизация)

##### Windows (PowerShell v5+)

```powershell
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri https://packages.wazuh.com/5.x/windows/wazuh-agent-5.x.y.msi -OutFile $env:tmp\wazuh-agent.msi
msiexec.exe /i $env:tmp\wazuh-agent.msi /q WAZUH_MANAGER='wazuh-manager.local' WAZUH_AGENT_NAME='WS-ADMIN'
Start-Service -Name Wazuh
```

##### Linux (APT-based)

```bash
wget -qO - https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --dearmor -o /usr/share/keyrings/wazuh.gpg
echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/5.x/apt/ stable main" | tee /etc/apt/sources.list.d/wazuh.list
sudo apt update
WAZUH_MANAGER='10.0.0.20' apt install wazuh-agent
systemctl enable --now wazuh-agent
```

##### Linux (RPM-based)

```bash
sudo rpm --import https://packages.wazuh.com/key/GPG-KEY-WAZUH
cat <<EOF | sudo tee /etc/yum.repos.d/wazuh.repo
[wazuh]
gpgcheck=1
gpgkey=https://packages.wazuh.com/key/GPG-KEY-WAZUH
enabled=1
type=rpm-md
baseurl=https://packages.wazuh.com/5.x/yum/
EOF
sudo dnf install wazuh-agent -y
sudo systemctl enable --now wazuh-agent
```

##### macOS

```bash
curl -Lo /tmp/wazuh-agent.pkg "https://packages.wazuh.com/5.x/macos/wazuh-agent-5.x.y.pkg"
sudo installer -pkg /tmp/wazuh-agent.pkg -target /
sudo /Library/Wazuh/bin/wazuh-control start
```

#### 3.3 Syslog-альтернатива (без установки агента)

Для устройств, на которые нельзя установить агент (сетевое оборудование, legacy-серверы, appliances), используйте перенаправление логов по **syslog** (RFC 5424) на менеджер Wazuh. В этом случае источником логов является удалённый хост, а агентом — сам менеджер, который читает forwarded-логи через Logcollector.

##### Настройка rsyslog на Linux-хосте

```bash
# Установка rsyslog
sudo apt install rsyslog

# Добавление конфигурации отправки логов на Wazuh Manager
echo "*.* @<IP-SRV-WAZUH>:514" | sudo tee /etc/rsyslog.d/wazuh.conf

# Перезапуск службы
sudo systemctl restart rsyslog
```

На менеджере Wazuh настройте Logcollector для чтения принятых syslog-сообщений:

```xml
<!-- /var/wazuh-manager/etc/ossec.conf -->
<ossec_config>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/remote-syslog.log</location>
  </localfile>
</ossec_config>
```

> **Примечание:** По умолчанию rsyslog отправляет на UDP 514. Для TCP используйте `@@<IP>:514`. Убедитесь, что firewall на менеджере разрешает приём на порту 514.

##### Настройка syslog на MikroTik

В **Winbox** перейдите в **System / Logging**:

1. **Actions** → добавьте новое действие:
   - **Name:** `wazuh`
   - **Target:** `remote`
   - **Remote Address:** `<IP-SRV-WAZUH>`
   - **Remote Port:** `514`

2. **Rules** → создайте правила отправки логов (например, `info`, `warning`, `critical`) на действие `wazuh`.

После этого логи начнут передаваться на менеджер. Однако без кастомных декодеров и правил в Dashboard попадут только сырые syslog-сообщения. Примеры декодеров и правил для MikroTik приведены в разделе [Декодеры в Wazuh: структура, типы и кастомная настройка](./custom-decoders.md).

### 4. Валидация развертывания

После установки всех компонентов выполните проверку:

```bash
# 1. Статус сервисов Manager
sudo systemctl status wazuh-manager
# → active (running)

# 2. Статус Indexer
curl -k -u admin:admin https://localhost:9200/_cluster/health?pretty
# → "status": "green" или "yellow" (для single-node yellow нормален)

# 3. Статус агентов
sudo /var/wazuh-manager/bin/agent_control -l
# → список агентов с статусом 'Active'

# 4. Проверка сертификатов
openssl s_client -connect wazuh-manager:1514 -showcerts </dev/null 2>/dev/null | openssl x509 -noout -subject -dates

# 5. Проверка Engine
sudo /var/wazuh-manager/bin/wazuh-engine-check -t
# → OK

# 6. Доступность Dashboard
curl -k https://localhost/status
# → {"status":"ok"}
```

### 5. Управление сертификатами

#### Просмотр информации о сертификатах

```bash
# Manager сертификат
openssl x509 -in /var/wazuh-manager/etc/certs/admin.pem -noout -text

# Root CA
openssl x509 -in /var/wazuh-manager/etc/certs/root-ca.pem -noout -subject -issuer -dates
```

#### Ротация сертификатов агента

При утере или компрометации сертификата агента:

```bash
# На менеджере: удалить старый ключ
sudo /var/wazuh-manager/bin/wazuh-control restart

# На агенте: удалить старые сертификаты и перерегистрироваться
sudo /var/ossec/bin/agent-auth -m wazuh-manager-ip
sudo systemctl restart wazuh-agent
```

#### Ротация CA (extreme scenario)

Если CA скомпрометирован, требуется перевыпуск всей цепочки:

```bash
# 1. Остановите все сервисы Wazuh
sudo systemctl stop wazuh-manager wazuh-indexer opensearch-dashboard

# 2. Удалите старые сертификаты (сохраните backup!)
sudo mv /var/wazuh-manager/etc/certs /root/certs-backup-$(date +%Y%m%d)

# 3. Перезапустите ассистент с флагом regenerate
sudo bash wazuh-install.sh --generate-config-files

# 4. Распространите новый архив на все узлы
# 5. Переустановите агентов с новым enrollment ключом
```

### 6. Резервное копирование и восстановление

#### Что бэкапить

| Компонент | Путь | Важность |
| :--- | :--- | :--- |
| CA и сертификаты | `/var/wazuh-manager/etc/certs/` | Critical |
| Конфигурации | `/var/wazuh-manager/etc/` | High |
| Кастомные правила | `/var/wazuh-manager/etc/rules/` | High |
| Интеграции | `/var/wazuh-manager/integrations/` | Medium |
| Indexer config | `/etc/wazuh-indexer/` | High |
| Dashboard config | `/usr/share/wazuh-dashboard/data/wazuh/` | Medium |

#### Скрипт бэкапа

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/wazuh-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Manager
tar czf "$BACKUP_DIR/wazuh-manager-etc.tar.gz" -C /var wazuh-manager/etc
tar czf "$BACKUP_DIR/wazuh-manager-integrations.tar.gz" -C /var wazuh-manager integrations

# Indexer
tar czf "$BACKUP_DIR/wazuh-indexer-etc.tar.gz" -C /etc wazuh-indexer

# Dashboard
tar czf "$BACKUP_DIR/wazuh-dashboard-config.tar.gz" -C /usr/share wazuh-dashboard/data

# OpenSearch snapshots (через API)
curl -k -u admin:admin -X PUT "https://localhost:9200/_snapshot/wazuh_backups/snapshot_$(date +%Y%m%d)" \
  -H "Content-Type: application/json" \
  -d '{"indices": "*", "ignore_unavailable": true}'

echo "Backup saved to $BACKUP_DIR"
```

#### Восстановление

```bash
# 1. Остановите сервисы
sudo systemctl stop wazuh-manager wazuh-indexer opensearch-dashboard

# 2. Восстановите файлы
tar xzf wazuh-manager-etc.tar.gz -C /var
tar xzf wazuh-indexer-etc.tar.gz -C /etc

# 3. Восстановите данные Indexer из snapshot
curl -k -u admin:admin -X POST "https://localhost:9200/_snapshot/wazuh_backups/snapshot_20260101/_restore"

# 4. Запустите сервисы
sudo systemctl start wazuh-indexer wazuh-manager opensearch-dashboard
```

### 7. Масштабирование (Scale-up и Scale-out)

#### Вертикальное масштабирование (Scale-up)

Для увеличения capacity существующего узла:
1. Увеличьте RAM и CPU согласно таблице требований.
2. Для Indexer: добавьте страницы памяти (`vm.max_map_count=262144` в `/etc/sysctl.conf`).
3. Перезапустите сервисы и проверьте `_cluster/health`.

#### Горизонтальное масштабирование (Scale-out)

При добавлении узлов в кластер:

**Indexer:**
```bash
# На новом узле: установите пакеты
sudo bash wazuh-install.sh --wazuh-indexer new-indexer-node

# На существующем узле: добавьте в кластер
curl -k -u admin:admin -X PUT "https://localhost:9200/_cluster/settings" \
  -H "Content-Type: application/json" \
  -d '{"persistent": {"cluster.routing.allocation.enable": "all"}}'
```

**Manager:**
```bash
# На новом узле Manager
sudo bash wazuh-install.sh --wazuh-manager
# Агенты автоматически распределяются по доступным Manager через DNS RR
```

### 8. High Availability (HA)

#### HAProxy для Manager

```bash
# /etc/haproxy/haproxy.cfg
frontend wazuh-manager-frontend
    bind *:1514
    bind *:1515
    bind *:55000
    default_backend wazuh-manager-backend

backend wazuh-manager-backend
    balance roundrobin
    option tcp-check
    server manager1 10.0.0.20:1514 check
    server manager2 10.0.0.21:1514 check
    server manager3 10.0.0.22:1514 check
```

На агентах указывается виртуальный IP HAProxy в `ossec.conf`:
```xml
<ossec_config>
  <client>
    <server>
      <address>10.0.0.100</address>  # VIP HAProxy
      <port>1514</port>
      <enrollment>
        <enabled>yes</enabled>
      </enrollment>
    </server>
  </client>
</ossec_config>
```

#### OpenSearch Indexer HA

Минимальная конфигурация — 3 узла для кворума. На каждом узле `/etc/wazuh-indexer/opensearch.yml`:
```yaml
cluster.initial_master_nodes: ["indexer-1", "indexer-2", "indexer-3"]
discovery.seed_hosts: ["indexer-1", "indexer-2", "indexer-3"]
cluster.name: wazuh-indexer-cluster
node.name: ${HOSTNAME}
network.host: 0.0.0.0
```

### 9. Обновление (Upgrade)

#### Планирование

1. Прочитайте [Release Notes](https://documentation.wazuh.com/current/release-notes/) для breaking changes.
2. Сделайте полный бэкап (см. сценарий 6).
3. Протестируйте upgrade на staging-среде.

#### Процедура (5.x → 5.y)

```bash
# 1. Остановите сервисы
sudo systemctl stop wazuh-manager wazuh-indexer opensearch-dashboard

# 2. Обновите репозиторий
curl -sO https://packages.wazuh.com/5.x/installation-assistant/wazuh-install.sh

# 3. Выполните upgrade
sudo bash wazuh-install.sh --upgrade

# 4. Проверьте статусы
sudo systemctl status wazuh-manager wazuh-indexer opensearch-dashboard
curl -k -u admin:admin https://localhost:9200/_cluster/health
```

#### Миграция 4.x → 5.0

Миграция на 5.0 является «разрушительной» для старых индексов из-за смены схем данных (ECS 2026):
1.  **Обновите агентов до 4.14.x** (минимальная версия для понимания протокола 5.0).
2.  **Разверните новый кластер 5.0** параллельно старому.
3.  **Подключите старые данные** через Legacy Connector в Dashboard для чтения архивных алертов.
4.  **Переключите агентов** на новый менеджер через смену IP/DNS в `ossec.conf`.

### 10. Air-gapped / Offline развертывание

Для сред без доступа в Интернет:

1. На машине с доступом скачайте все пакеты:
```bash
mkdir -p /tmp/wazuh-offline && cd /tmp/wazuh-offline
apt download wazuh-manager wazuh-indexer opensearch-dashboard
# Для RPM: yum install --downloadonly --downloaddir=. wazuh-manager ...
```

2. Перенесите пакеты на изолированный хост через removable media.

3. Создайте локальный репозиторий:
```bash
# Deb-based
sudo dpkg -i *.deb
# RPM-based
sudo rpm -Uvh *.rpm
```

4. Запустите установку в offline-режиме:
```bash
sudo bash wazuh-install.sh -a --offline
```

5. Для агентов: используйте offline-репозиторий или предварительно скачанные `.msi`/`.pkg`/`.deb` пакеты.

### 11. Автоматизация через Ansible

Пример плейбука для развертывания All-in-one:

```yaml
---
- name: Deploy Wazuh All-in-one
  hosts: wazuh_manager
  become: yes
  vars:
    wazuh_version: "5.0.0"
  tasks:
    - name: Install prerequisites
      apt:
        name: [curl, apt-transport-https, gnupg]
        state: present

    - name: Download Wazuh install script
      get_url:
        url: https://packages.wazuh.com/5.x/installation-assistant/wazuh-install.sh
        dest: /tmp/wazuh-install.sh
        mode: '0755'

    - name: Run Wazuh All-in-one installation
      command: bash /tmp/wazuh-install.sh -a
      args:
        creates: /var/wazuh-manager/etc/wazuh-passwords.txt

    - name: Ensure Wazuh services are running
      systemd:
        name: "{{ item }}"
        state: started
        enabled: yes
      loop:
        - wazuh-manager
        - wazuh-indexer
        - opensearch-dashboard

    - name: Retrieve admin password
      slurp:
        src: /var/wazuh-manager/etc/wazuh-passwords.txt
      register: wazuh_passwords
```

### 12. Безопасное усиление (Hardening) инфраструктуры

#### Менеджер

```bash
# Ограничьте доступ к API только доверенными подсетями
sudo iptables -A INPUT -p tcp --dport 55000 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 55000 -j DROP

# Отключите неиспользуемые wodle
sudo sed -i 's/<disabled>no<\/disabled>/<disabled>yes<\/disabled>/g' /var/wazuh-manager/etc/ossec.conf
# Включите только необходимые wodle

# Включите аудит процессов Manager
sudo apt install auditd audispd-plugins -y
```

#### Indexer

```yaml
# /etc/wazuh-indexer/opensearch-security/config.yml
http:
  ssl:
    enabled: true
    client_authentication: required
transport:
  ssl:
    enabled: true
    client_authentication: required
```

#### Dashboard

```yaml
# /etc/wazuh-indexer/opensearch-dashboards/opensearch_dashboards.yml
server.host: "127.0.0.1"  # или внутренний IP, не 0.0.0.0 в production
opensearch.security.allow_unsafe_dashboard_init_mode: false
```

## Траблшутинг развертывания

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Port 1514/1515 already in use** | Другой сервис (например, Syslog) занял порт | Остановите конфликтующий сервис или измените порты в `ossec.conf` агента |
| **Indexer cluster health red** | Недостаточно узлов для кворума или диск полон | Проверьте `/_cluster/health`, убедитесь что 2 из 3 узлов доступны, освободите место |
| **Agent stuck in "Pending"** | Порт 1515 закрыт firewall или менеджер недоступен | Проверьте `iptables`/`firewalld`, DNS-резолвинг на агенте, доступность 1515 TCP |
| **Certificate verify failed** | Агент получил неверный сертификат или CA не совпадает | Удалите `/var/ossec/etc/client.keys` на агенте и перезапустите enrollment |
| **Dashboard SSL handshake error** | Несовпадение сертификатов между Dashboard и Indexer | Проверьте `opensearch_dashboards.yml` на корректность путей к сертификатам |
| **Engine not starting** | Недостаточно RAM или неверная конфигурация | Проверьте `journalctl -u wazuh-manager -f`, убедитесь что `vm.max_map_count` настроен |
| **Slow indexing / high CPU** | Недостаточно ресурсов Indexer или неправильные ISM настройки | Увеличьте RAM, проверьте `thread_pool.write.queue_size`, оптимизируйте mappings |
| **Migration index mapping errors** | Старые индексы 4.x несовместимы с 5.0 | Используйте Legacy Connector или реиндексируйте через reindex API |

## Дополнительная информация

### Стратегия миграции (4.x → 5.0)

Миграция на 5.0 является «разрушительной» для старых индексов из-за смены схем данных (ECS 2026):
1.  **Обновите агентов до 4.14.x** (минимальная версия для понимания протокола 5.0).
2.  **Разверните новый кластер 5.0** параллельно старому.
3.  **Подключите старые данные** через Legacy Connector в Dashboard для чтения архивных алертов.
4.  **Переключите агентов** на новый менеджер через смену IP/DNS в `ossec.conf`.

### Планирование дискового пространства

С переходом на модель **Full Visibility** (хранение всех событий) объем данных вырос в 4–6 раз по сравнению с алерт-моделью 4.x. Рекомендуется использовать механизмы **OpenSearch Cold Storage** для архивирования данных старше 30 дней.

### Best Practices

- **Семейство паролей**: храните пароли из `wazuh-passwords.txt` в vault (Ansible Vault, HashiCorp Vault). Никогда не коммитьте их в Git.
- **Сертификаты**: регулярно тестируйте срок действия. Настройте мониторинг через `openssl` cron или Wazuh SCA.
- **Мониторинг инфраструктуры**: настройте Wazuh на само-мониторинг (см. [Мониторинг здоровья](./wazuh-health-monitoring.md)).
- **Тестирование изменений**: любые изменения в `ossec.conf` или политиках сначала тестируйте на 1% агентов (canary).
- **Сеть**: используйте VLAN/segregation для трафика Wazuh. Не открывайте порты 1514/1515/55000 в Интернет.
- **Резервное копирование**: автоматизируйте бэкапы CA и конфигураций. Тестируйте восстановление раз в квартал.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Сбор логов (Logcollector)](./wazuh-log-collection.md) — настройка источников данных 5.0.
- [Декодеры в Wazuh: структура, типы и кастомная настройка](./custom-decoders.md) — нормализация нестандартных логов (MikroTik, Cisco).
- [Agentless-мониторинг в Wazuh: SSH, сетевые устройства](./wazuh-agentless.md) — альтернативный сбор логов без агента.
- [Мониторинг здоровья и самодиагностика Wazuh](./wazuh-health-monitoring.md) — контроль OTLP-метрик.
