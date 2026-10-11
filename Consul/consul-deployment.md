# Развертывание в продуктовой среде

**Актуально для:** Consul 2.0.x / 1.22.x / 1.20.x / 1.19.x

## Определения

**Продуктовое развертывание Consul** — это процесс установки и настройки кластера с учетом требований высокой доступности (HA), безопасности и производительности. В отличие от режима разработки, промышленная эксплуатация требует обязательного включения шифрования (Gossip и RPC), настройки ACL, использования отказоустойчивого кворума и интеграции с системными менеджерами служб (systemd).

## Основные компоненты

Для надежной работы кластера необходимо обеспечить:
- **Шифрование Gossip:** Защита UDP-трафика между агентами с помощью общего ключа.
- **Шифрование RPC/HTTPS:** Использование TLS для защиты TCP-взаимодействия и UI.
- **ACL (Access Control Lists):** Разграничение прав доступа по принципу **Default Deny**.
- **Systemd:** Управление жизненным циклом процесса Consul в ОС.

## Практические сценарии

### 1. Подготовка конфигурации (HCL)

Рекомендуется разделять общие настройки и специфичные для роли (Server/Client).

#### Общие настройки безопасности (`consul.hcl`)

Файл содержит параметры, общие для всех узлов кластера.

```hcl
datacenter = "dc1"
data_dir   = "/opt/consul/data"
encrypt    = "YOUR_GOSSIP_ENCRYPTION_KEY" # Сгенерируйте через 'consul keygen'

retry_join = ["10.0.1.10", "10.0.1.11", "10.0.1.12"]

performance {
  raft_multiplier = 1 # Максимальная производительность Raft для Production
}

acl {
  enabled = true
  default_policy = "deny"
  enable_token_persistence = true
}

telemetry {
  prometheus_retention_time = "60s"
  disable_hostname = true
}
```

**Валидация:**
```bash
# Проверка синтаксиса конфигурации
consul validate /etc/consul.d/consul.hcl
# → Configuration valid

# Проверка подключения к кластеру
consul members
# → вывод таблицы с узлами и их статусами
```

#### Конфигурация Сервера (`server.hcl`)

Серверы хранят состояние и участвуют в консенсусе.

```hcl
server           = true
bootstrap_expect = 3 # Количество серверов для начального формирования кворума
ui_config {
  enabled = true
}

client_addr = "0.0.0.0" # Слушать на всех интерфейсах (защитите доступ через ACL/Firewall)

tls {
  defaults {
    ca_file   = "/etc/consul.d/certs/consul-agent-ca.pem"
    cert_file = "/etc/consul.d/certs/server.pem"
    key_file  = "/etc/consul.d/certs/server-key.pem"
    verify_incoming = true
    verify_outgoing = true
  }
  internal_rpc {
    verify_server_hostname = true
  }
}

auto_encrypt {
  allow_tls = true
}
```

**Валидация:**
```bash
# Проверка статуса сервера
consul info
# → server: true, leader: true/false

# Проверка Raft-статуса
consul operator raft list-peers
# → вывод таблицы с id, address, voter status, leader status
```

#### Конфигурация Клиента (`client.hcl`)

Клиенты (агенты) запускаются на узлах с приложениями.

```hcl
server = false

tls {
  defaults {
    ca_file         = "/etc/consul.d/certs/consul-agent-ca.pem"
    verify_outgoing = true
  }
}

auto_encrypt {
  tls = true
}
```

**Валидация:**
```bash
# Проверка статуса клиента
consul info
# → server: false

# Проверка регистрации сервисов
consul services
# → вывод списка сервисов на узле
```

### 2. Настройка службы Systemd

Создайте файл `/etc/systemd/system/consul.service`. Данная конфигурация включает ограничения безопасности и автоматический перезапуск.

```ini
[Unit]
Description="HashiCorp Consul - A service mesh solution"
Documentation=https://www.consul.io/
Requires=network-online.target
After=network-online.target
ConditionFileNotEmpty=/etc/consul.d/consul.hcl

[Service]
Type=notify
User=consul
Group=consul
# Процесс запускается с чтением всех файлов .hcl в директории
ExecStart=/usr/bin/consul agent -config-dir=/etc/consul.d/
ExecReload=/bin/kill --signal HUP $MAINPID
KillMode=process
KillSignal=SIGTERM
Restart=on-failure
LimitNOFILE=65536

# Ограничения безопасности (Hardening)
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true

[Install]
WantedBy=multi-user.target
```

**Валидация:**
```bash
# Перезагрузка systemd и включение службы
systemctl daemon-reload
# → Reloaded

systemctl enable --now consul
# → Created symlink, started consul

# Проверка статуса
systemctl status consul
# → active (running) с указанием PID и memory usage

# Проверка логов
journalctl -u consul -f
# → вывод логов в реальном времени
```

### 3. Порядок развертывания

1.  **Генерация ключей:**
    - `consul keygen` — для Gossip шифрования.
    - `consul tls ca create` — для TLS (если не используется внешний CA).
2.  **Настройка ОС:** Создайте пользователя `consul` и директории `/opt/consul/data`, `/etc/consul.d/`. Установите права: `chown -R consul:consul /opt/consul/`.
3.  **Запуск серверов:** Запустите сначала серверы один за другим. Проверьте формирование кворума: `consul operator raft list-peers`.
4.  **ACL Bootstrap:** Выполните `consul acl bootstrap` на одном из серверов для получения первого Management Token.
5.  **Запуск клиентов:** Разверните конфиг клиента и CA на остальные узлы и запустите службу.

**Валидация:**
```bash
# Проверка кворума
consul operator raft list-peers
# → вывод таблицы, все серверы со статусом voter

# Проверка лидера
consul operator raft list-peers | grep leader
# → вывод строки с active leader

# Проверка ACL
consul acl token read -self
# → вывод информации о текущем токене
```

### 4. Проверка резервного копирования

```bash
# Создание тестового снапшота
consul snapshot save test-backup.snap
# → Snapshot saved successfully

# Проверка валидности снапшота
consul snapshot inspect test-backup.snap
# → вывод размера, индекса, версии Raft

# Удаление тестового файла
rm test-backup.snap
```

## Оптимизация ОС для высоких нагрузок (High-Load Tuning)

При работе в высоконагруженных средах стандартные параметры ядра Linux могут приводить к потере UDP-пакетов Gossip-протокола и отказу в новых соединениях. Рекомендуется настроить параметры `sysctl`.

### 1. Настройка сетевых буферов (UDP/TCP)

Consul активно использует UDP для Gossip. Маленькие буферы приводят к «дребезгу» (flapping) статусов узлов.

```bash
# /etc/sysctl.d/10-consul.conf

# Увеличение максимальных размеров буферов приема и отправки (16MB)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 16777216
net.core.wmem_default = 16777216

# Увеличение очереди сетевой карты
net.core.netdev_max_backlog = 65536

# Увеличение лимита одновременно открытых сокетов
net.core.somaxconn = 65535
```

**Валидация:**
```bash
# Применение изменений
sysctl --system
# → Применение изменений из /etc/sysctl.d/10-consul.conf

# Проверка текущих значений
sysctl net.core.rmem_max net.core.wmem_max
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216
```

### 2. Лимиты открытых файлов и Conntrack

Большое количество сервисов и соединений Service Mesh требует расширения таблиц отслеживания соединений.

```bash
# Увеличение системного лимита открытых файлов
fs.file-max = 2097152

# Расширение таблицы conntrack (если используется Firewall/NAT)
net.netfilter.nf_conntrack_max = 1048576
# Снижение таймаутов для быстрой очистки таблицы
net.netfilter.nf_conntrack_tcp_timeout_established = 3600

# Расширение диапазона эфемерных портов
net.ipv4.ip_local_port_range = 1024 65535
```

**Валидация:**
```bash
# Проверка лимита открытых файлов
cat /proc/sys/fs/file-max
# → 2097152

# Проверка conntrack
cat /proc/sys/net/netfilter/nf_conntrack_max
# → 1048576

# Проверка текущего использования conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
# → текущее количество отслеживаемых соединений
```

### 3. Лимиты процесса (Ulimit)

Для самого процесса Consul в `systemd`-юните обязательно должен быть установлен лимит `LimitNOFILE` (уже включен в пример выше). Для ручного запуска используйте `ulimit -n 65536`.

```bash
# Проверка текущего лимита
ulimit -n
# → 65536 (если настроен через systemd)

# Проверка лимита для запущенного процесса
cat /proc/$(pgrep consul)/limits | grep "open files"
# → вывод текущих лимитов открытых файлов
```

## Тюнинг больших кластеров (Scaling Tuning)

При росте кластера свыше 1000 узлов рекомендуется внести изменения в конфигурацию Consul для снижения нагрузки на Control Plane.

### 1. Снижение нагрузки на CPU (Антиэнтропия)

Увеличение интервалов проверки состояния позволяет снизить количество транзакций записи в Raft.

```hcl
# server.hcl
# Увеличение интервала обновления статуса проверок (по умолчанию 5m)
check_update_interval = "10m"

# Отключение сохранения вывода (output) успешных проверок в каталоге
# Это значительно снижает объем данных, пересылаемых через Raft
discard_check_output = true
```

**Валидация:**
```bash
# Проверка применения конфигурации
consul reload
# → Configuration reload triggered

# Мониторинг метрик Raft
curl -s http://localhost:8500/v1/metrics | grep consul_raft
# → вывод метрик Raft для анализа нагрузки
```

### 2. Оптимизация Raft и Дискового IO

Увеличение порога создания снимков предотвращает слишком частую запись тяжелых файлов на диск.

```hcl
# server.hcl
performance {
  # Количество записей в логе перед созданием снимка (по умолчанию 16384)
  snapshot_threshold = 32768
  
  # Количество записей, сохраняемых после снимка для фолловеров (catch-up)
  raft_trailing_logs = 20000
}
```

**Валидация:**
```bash
# Проверка текущих значений Raft
consul operator raft list-peers
# → Health tracking: LastContact < 200ms, trailing logs в пределах нормы

# Мониторинг частоты снапшотов
curl -s http://localhost:8500/v1/metrics | grep 'consul.raft.rpc.installSnapshot'
# → частота установки снапшотов должна снизиться
```

### 3. Настройка Gossip (для кластеров > 5000 узлов)

Увеличение интервалов Gossip снижает нагрузку на сеть и CPU за счет более медленного обнаружения сбоев. По умолчанию `gossip_interval` для LAN составляет 200ms, `probe_interval` — 1s.

```hcl
# server.hcl & client.hcl
gossip_lan {
  gossip_interval = "500ms" # Увеличено с дефолта 200ms для больших кластеров
  probe_interval  = "2s"    # Увеличено с дефолта 1s
}
```

**Валидация:**
```bash
# Проверка статуса узлов
consul members
# → все узлы со статусом alive

# Мониторинг обнаружения сбоев
consul monitor -level=debug
# → отслеживание событий Serf/Memberlist
```

**Очистка после изменений:** Если производительность ухудшилась, верните значения к дефолту (`gossip_interval = "200ms"`, `probe_interval = "1s"`) и перезагрузите конфигурацию.

## Управление ключами Gossip

### 1. Генерация ключа

Для инициализации нового кластера необходимо сгенерировать 32-байтовый ключ в формате Base64:

```bash
consul keygen
# → x9X5P+... (Пример вывода, 32 символа Base64)
```

Полученный ключ необходимо вставить в параметр `encrypt` в файле `consul.hcl` на всех узлах.

**Валидация:**
```bash
# Проверка длины ключа (должен быть 32 байта)
echo -n "YOUR_KEY" | base64 -d | wc -c
# → 32

# Проверка работы шифрования
consul members
# → узлы видят друг друга, статус alive
```

### 2. Ротация ключа (Zero-downtime)

Если ключ скомпрометирован или требуется плановое обновление, используйте механизм **Keyring** для замены без остановки кластера.

1.  **Добавление нового ключа:** Выполните на любом сервере. Новый ключ будет распространен по кластеру через Gossip.
    ```bash
    consul keyring -install <NEW_KEY>
    # → Key installed successfully
    ```
2.  **Смена активного ключа:** Сделайте новый ключ основным для шифрования исходящих сообщений.
    ```bash
    consul keyring -use <NEW_KEY>
    # → Key activated successfully
    ```
3.  **Обновление конфигурации:** Обновите параметр `encrypt` в файлах `consul.hcl` на всех узлах, чтобы при перезагрузке они использовали нового ключа.
4.  **Удаление старого ключа:** После того как все узлы перешли на нового ключа, удалите старый из памяти кластера.
    ```bash
    consul keyring -remove <OLD_KEY>
    # → Key removed successfully
    ```

**Очистка после ротации:** Убедитесь, что старый ключ удален:
```bash
consul keyring -list
# → в выводе должен присутствовать только новый ключ
```

## Стратегии обновления (Zero-downtime Upgrade)

Обновление Consul без простоя требует строгого соблюдения последовательности действий для сохранения Raft-кворума и доступности данных.

### 1. Ручное последовательное обновление (Rolling Update)

Подходит для Community Edition. Основное правило: **обновлять по одному узлу за раз**.

#### Порядок действий:
1.  **Снапшот:** Создайте резервную копию состояния: `consul snapshot save backup.snap`.
    ```bash
    # → Snapshot saved successfully
    ```
2.  **Обновление Фолловеров:**
    - Остановите один сервер-последователь (Follower).
    - Замените бинарный файл/образ и запустите службу.
    - Дождитесь, пока узел перейдет в статус `healthy` и синхронизирует логи.
    - Повторите для всех фолловеров.
3.  **Обновление Лидера:**
    - После обновления всех фолловеров, остановите текущего Лидера.
    - Кластер проведет выборы, новым лидером станет один из уже обновленных узлов.
    - Обновите старый узел-лидер и верните его в кластер.
4.  **Обновление Клиентов:** Клиенты обновляются группами (batch). Это не влияет на кворум, но позволяет избежать резких скачков перерегистрации сервисов.

**Валидация после обновления:**
```bash
# Проверка версии на всех узлах
consul version
# → Consul v2.0.3 (или целевая версия)

# Проверка кворума
consul operator raft list-peers
# → все узлы healthy, один leader

# Проверка стабилизации
watch -n 5 'consul operator raft list-peers'
# → стабильное состояние без flapping в течение 1-2 минут
```

### 2. Автоматизация через Autopilot (Enterprise)

Autopilot в Enterprise-версии позволяет автоматизировать замену серверов при обновлении.

- **Механизм:** Новые серверы с более высокой версией присоединяются к кластеру как `non-voters`. Autopilot следит за их здоровьем и, когда их становится достаточно для формирования кворума, автоматически повышает их до `voters`, инициирует перевыборы лидера и исключает старые узлы из кворума.
- **Преимущество:** Полностью исключает риск потери кворума из-за человеческой ошибки при ручной замене узлов.

### 3. Обновление в Kubernetes (Helm)

Используется стратегия `updatePartition` для управления `StatefulSet` серверов.

1.  **Подготовка:** Установите `server.updatePartition` равным количеству реплик (например, 3).
2.  **Обновление образа:** Укажите новую версию в `values.yaml` и выполните `helm upgrade`. Поды не перезапустятся.
3.  **Поэтапный перезапуск:** Уменьшайте `updatePartition` на 1 и выполняйте `helm upgrade`. Это перезапустит один под. Дождитесь его готовности и стабильности кластера перед следующим шагом.
4.  **Завершение:** Когда `updatePartition` станет 0, все серверы будут обновлены.

**Валидация:**
```bash
# Проверка статуса подов
kubectl get pods -l app=consul,component=server
# → все поды в статусе Running, Ready 1/1

# Проверка версии Consul в кластере
kubectl exec -it consul-server-0 -- consul version
# → Consul v2.0.3

# Проверка кворума через Kubernetes
kubectl exec -it consul-server-0 -- consul operator raft list-peers
# → все серверы healthy
```

## Устранение неполадок (Troubleshooting)

### Consul не запускается (Systemd)

- **Ошибка прав:** Проверьте, что пользователь `consul` имеет доступ к `data_dir` и файлам в `config-dir`.
    ```bash
    # Проверка прав
    ls -la /opt/consul/data
    # → владелец consul:consul

    # Проверка прав на конфиги
    ls -la /etc/consul.d/
    # → файлы читаемы пользователем consul
    ```
- **Ошибка конфигурации:** Проверьте синтаксис: `consul validate /etc/consul.d/`.
    ```bash
    # → Configuration valid / Configuration invalid: <ошибка>
    ```
- **Порты заняты:** Убедитесь, что порты 8300-8302, 8500-8600 не заняты другими процессами.
    ```bash
    # Проверка портов
    ss -tulpn | grep -E '8300|8301|8302|8500|8600'
    # → вывод процессов, слушающих на портах Consul
    ```

### Проблемы с Gossip (UDP)

Симптомы: Узлы не видят друг друга или помечаются как `failed`.
- **Firewall:** Убедитесь, что порты `8301` (LAN) и `8302` (WAN) открыты для **UDP**.
    ```bash
    # Проверка firewall
    iptables -L -n | grep -E '8301|8302'
    # → правила должны разрешать UDP трафик
    ```
- **MTU:** В некоторых средах большой размер Gossip-пакетов может блокироваться. Снизьте MTU или проверьте настройки сети.
    ```bash
    # Проверка MTU
    ip link show | grep mtu
    # → MTU 1500 (или ниже для туннелей)

    # Тест фрагментации
    ping -M do -s 1472 <узел>
    # → тест на поддержку больших пакетов
    ```

### Проблемы с TLS

Симптомы: Ошибки `TLS handshake failure` или `certificate verify failed`.
- **Сертификаты:** Проверьте срок действия и соответствие имени.
    ```bash
    # Проверка сертификата
    openssl x509 -in /etc/consul.d/certs/server.pem -text -noout
    # → вывод информации о сертификате, включая срок действия

    # Проверка соответствия имени
    openssl s_client -connect localhost:8501 -servername consul.service.consul
    # → проверка TLS-соединения
    ```
- **Цепочка сертификатов:** Убедитесь, что промежуточные сертификаты включены в `cert_file` или предоставлены через `ca_file`.

### Проблемы с ACL

Симптомы: Ошибки `Permission denied` при выполнении операций.
- **Проверка токена:** Убедитесь, что используется правильный токен с необходимыми правами.
    ```bash
    # Проверка текущего токена
    consul acl token read -self
    # → вывод PolicyID, Roles, Policies

    # Проверка прав токена
    consul acl token info <TOKEN>
    # → вывод разрешений токена
    ```

## Лучшие практики

- **HA:** 3 или 5 серверов; больше замедляет Raft.
- **Диск:** Используйте NVMe/SSD с задержкой `fsync` < 10ms. Raft блокируется на `fsync` при записи в WAL.
- **Сеть:** Низкая задержка между серверами (< 10ms для LAN). Для гео-распределенных кластеров настройте `raft_multiplier` для увеличения тайм-аутов.
- **Автопилот:** Оставьте включенным (`CleanupDeadServers = true`). В тестовых окружениях можно отключить.
- **Time Sync:** NTP/Chrony на всех серверах; Raft зависит от согласованных часов.
- **Бэкапы:** Регулярные снапшоты через `consul snapshot save` или snapshot agent. Храните снапшоты вне кластера.
- **Learners:** Используйте Learner при добавлении/замене серверов для безопасной синхронизации.
- **Наблюдаемость:** Мониторьте `consul_raft_leader_lastContact`, `MaxTrailingLogs`, `consul_raft_commitTime`, `consul_raft_peers`.

## Граничные случаи

- **WAL LogStore:** По умолчанию с Consul 1.15.0. BoltDB доступен для обратной совместимости, но не рекомендуется.
- **Quorum Loss:** При потере кворума кластер переходит в read-only для `stale` чтений. Для восстановления требуется ручное создание `peers.json`.
- **Leader Flapping:** Частые перевыборы лидера вызываются дисковыми задержками (`await > 10ms`) или contention на CPU. Используйте выделенные инстансы и приоритизацию процесса.
- **Гео-распределение:** Увеличение `raft_multiplier` компенсирует сетевые задержки, но увеличивает время обнаружения сбоев.
- **Enterprise Redundancy Zones:** Требуют лицензии Enterprise. Автоматическое повышение non-voter происходит только внутри одной AZ.
- **Большие кластеры (>5000 узлов):** Требуется тюнинг Gossip интервалов и антиэнтропии. Рассмотрите разделение на несколько дата-центров или использование Sameness Groups.

## Дополнительная информация

- **[Архитектура Consul](./consul_architecture.md)** — описание ролей и портов.
- **[Система ACL](./consul_acl.md)** — детальная настройка прав доступа.
- **[Обзор Consul](./consul_overview.md)** — общее описание платформы и лучшие практики.
- **[Ротация CA и auto_encrypt](./consul_architecture.md#ротация-сертификатов-agent-tls-step-by-step)** — процедуры обслуживания TLS.
- **[Резервное копирование и восстановление (DR)](./consul-disaster-recovery.md)** — автоматизация бэкапов и сценарии восстановления.
- **[Consul Network Segments](./consul_network_segments.md)** — разбиение gossip-пула для больших кластеров.
- **[Consul Backup Verification](./consul_backup_verification.md)** — методика проверки бэкапов.
- **[Consul Upgrade и Migration](./consul_upgrade_migration.md)** — глубокая методика обновления и миграции данных.
- **[Raft-консенсус](./consul_consensus.md)** — глубокое погружение в репликацию и кворум.
