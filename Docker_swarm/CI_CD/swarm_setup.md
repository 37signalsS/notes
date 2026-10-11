# CI/CD в Docker Swarm: Подготовка и настройка кластера

**Актуально для:** Docker Engine 29.x+

## Определения

- **[Docker Swarm Mode](../docker_swarm_overview.md):** Встроенный механизм оркестрации Docker, превращающий группу хостов в единый отказоустойчивый кластер.
- **[mTLS (mutual TLS)](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls):** Протокол двусторонней проверки сертификатов. Обеспечивает шифрование трафика и проверку подлинности как CI-раннера (клиента), так и Swarm-менеджера (сервера).
- **[Docker Context](./docker_context_setup.md):** Абстракция в CLI Docker, объединяющая параметры подключения (URL эндпоинта и пути к сертификатам) под коротким именем.
- **[Advertising Address (`--advertise-addr`):](../swarm_advanced_topics.md)** IP-адрес или интерфейс, который узел сообщает остальным участникам кластера для связи. Критичен в мульти-интерфейсных системах.
- **[Listening Address (`--listen-addr`):](../swarm_advanced_topics.md)** Адрес и порт, на которых демон слушает входящий трафик управления Swarm (по умолчанию 0.0.0.0:2377).

## Базовые концепции

### Архитектура безопасного удаленного доступа

Для интеграции Swarm с внешними CI/CD системами (GitLab, GitHub) необходимо организовать защищенный канал управления. Использование порта 2376 с mTLS является промышленным стандартом, так как:

- **Безопасность:** Исключает несанкционированный доступ к API (в отличие от открытого порта 2375).
- **Изоляция:** CI-система взаимодействует с кластером как удаленный клиент, не требуя установки агентов на менеджер-ноды.
- **Централизация:** Один CI-раннер может управлять множеством кластеров через переключение контекстов.

### Сетевые требования

Для корректной работы Swarm и его API необходимо открыть следующие порты в Firewall:

| Порт / Протокол | Назначение | Описание |
|:---|:---|:---|
| **2376 / TCP** | Docker TLS API | Удаленное управление кластером (CI/CD) |
| **2377 / TCP** | Cluster Management | Коммуникации между менеджерами (Raft) |
| **7946 / TCP + UDP** | Node Discovery | Обнаружение узлов и обмен состоянием (Gossip) |
| **4789 / UDP** | Overlay Traffic | Трафик сетей Overlay (VXLAN-инкапсуляция) |

> **Важно:** Синхронизация времени (NTP) критически важна для алгоритма Raft. Разница во времени между менеджерами более чем в несколько секунд может привести к потере кворума. Используйте `chrony` или `systemd-timesyncd`.

### Service Discovery и Routing Mesh

Docker Swarm включает встроенный механизм обнаружения сервисов и балансировки нагрузки:

- **Встроенный DNS (127.0.0.11):** Каждый контейнер в Swarm использует внутренний DNS-резолвер для обнаружения сервисов по имени. Имя сервиса резолвится в Virtual IP (VIP), который балансирует трафик между репликами.
- **Routing Mesh:** Встроенный балансировщик уровня L4, распределяющий входящие запросы между репликами сервиса. Позволяет обратиться к сервису через опубликованный порт на любом узле кластера (не обязательно на том, где запущена реплика).
- **Endpoint Mode:**
  - **VIP (по умолчанию):** Балансировка через единый IP и IPVS.
  - **DNSRR:** Возвращает список IP всех реплик, клиент сам выполняет балансировку (полезно для Stateful-сервисов).

### Overlay Networks

Overlay-сети создают виртуальную L2-сеть между хостами кластера:

- **VXLAN-инкапсуляция:** Добавляет заголовок к пакетам, что уменьшает доступный MTU. Рекомендуемое значение MTU для интерфейса `docker0` — **1450** (вместо стандартных 1500).
- **Шифрование:** При создании сети с флагом `--opt encrypted` весь трафик Overlay шифруется с помощью IPSec (mTLS между узлами).
- **Attachable:** Флаг `--attachable` позволяет standalone-контейнерам (не часть сервиса) подключаться к Overlay-сети для отладки.

### Secrets Management

Docker Swarm предоставляет встроенный механизм безопасного хранения чувствительных данных:

- **Immutable:** Секреты неизменяемы. Для обновления необходимо создать новый секрет с новым именем и обновить ссылку в Compose-файле.
- **Хранение:** Секреты хранятся в Raft-логе менеджеров в зашифрованном виде. Доступны только для сервисов, которым они явно назначены.
- **Монтирование:** В контейнере секреты монтируются в `/run/secrets/<имя>` как tmpfs (не сохраняются на диск).

### Health Checks

Swarm использует результаты Health Checks для принятия решений о плановой остановке и перезапуске задач:

- **Dockerfile HEALTHCHECK:** Определяет, как проверять работоспособность контейнера.
- **deploy.healthcheck:** Переопределяет или дополняет проверку из Dockerfile на уровне сервиса.
- **Влияние на Rolling Update:** Swarm ожидает успешного прохождения Health Check перед продвижением новой реплики в статус `Running` (параметр `monitor` в `update_config`).

### Рекомендуемые параметры Docker Daemon

Для стабильной работы Swarm в файл `/etc/docker/daemon.json` рекомендуется добавить:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "metrics-addr": "0.0.0.0:9323",
  "experimental": false,
  "live-restore": true,
  "storage-driver": "overlay2"
}
```

- **log-opts:** Ограничивает рост логов Docker (защита от заполнения диска).
- **metrics-addr:** Включает Prometheus-метрики Docker Engine (порт 9323).
- **live-restore:** Позволяет демону продолжать работать при перезагрузке контейнеров (ускоряет восстановление после перезагрузки узла).

### Кворум и надежность

- **Нечетное количество:** Для обеспечения отказоустойчивости используйте 3 или 5 менеджеров.
- **Availability:** Менеджеры также выполняют роль рабочих узлов по умолчанию. В нагруженных кластерах рекомендуется переводить менеджеры в режим `drain` (`docker node update --availability drain <NODE>`), чтобы они занимались только управлением.

### Pre-flight проверка перед развертыванием

Перед настройкой кластера убедитесь в готовности инфраструктуры:

```bash
# 1. Проверка версии Docker (минимум 20.10+, рекомендуется 29.x+)
docker --version
# Ожидаемый вывод: Docker version 29.x+

# 2. Проверка доступности портов (на всех узлах)
for port in 2376 2377 7946 7946/udp 4789/udp; do
  echo "Port $port: $(ss -tlnp | grep :${port%%/*} >/dev/null && echo 'OK' || echo 'BLOCKED')"
done

# 3. Проверка синхронизации времени (критично для Raft)
for node in manager1 manager2 worker1; do
  echo "$node: $(ssh $node date -u +%H:%M:%S)"
done
# Разница не должна превышать 1 секунды

# 4. Проверка дискового пространства (минимум 10GB на узле)
df -h /var/lib/docker | awk 'NR==2{print "Free:", $4}'

# 5. Проверка NetworkManager (может конфликтовать с Docker)
systemctl is-active NetworkManager && echo "WARNING: Disable or configure for Docker"

# 6. Проверка firewall (ufw/iptables)
sudo ufw status | grep -E '2376|2377|7946|4789' || echo "WARNING: Required ports may not be open"

# 7. Проверка наличия daemon.json
test -f /etc/docker/daemon.json && echo "daemon.json exists" || echo "WARNING: daemon.json not found"

# 8. Проверка MTU интерфейса (должен быть 1450 для VXLAN)
ip link show docker0 | grep mtu
# Ожидаемый вывод: mtu 1450 qdisc noqueue state DOWN mode DEFAULT
```

## Практические сценарии

### Сценарий 1: Инициализация кластера

1. **Создание первого менеджера:**
   ```bash
   # --advertise-addr указывает IP, доступный другим узлам
   docker swarm init --advertise-addr 10.0.0.1
   ```

2. **Получение токенов присоединения:**
   ```bash
   # Для рабочих узлов
   docker swarm join-token worker
   # Для дополнительных менеджеров
   docker swarm join-token manager
   ```

3. **Подключение узла:**
   ```bash
   docker swarm join --token <TOKEN> 10.0.0.1:2377
   ```

### Сценарий 2: Создание PKI инфраструктуры (mTLS)

Для генерации сертификатов используется `openssl`. Убедитесь, что `Common Name (CN)` и `Subject Alternative Name (SAN)` настроены корректно.

1. **Корневой CA:**
   ```bash
   openssl genrsa -aes256 -out ca-key.pem 4096
   openssl req -new -x509 -days 3650 -key ca-key.pem -sha256 -out ca.pem
   ```

2. **Сертификат сервера (Manager):**
   ```bash
   openssl genrsa -out server-key.pem 4096
   openssl req -subj "/CN=$(hostname -f)" -sha256 -new -key server-key.pem -out server.csr
   # Укажите ВСЕ IP и DNS имена менеджера в SAN
   echo "subjectAltName = DNS:swarm.example.com,IP:10.0.0.1,IP:127.0.0.1" > extfile.cnf
   openssl x509 -req -days 3650 -sha256 -in server.csr -CA ca.pem -CAkey ca-key.pem \
     -CAcreateserial -out server-cert.pem -extfile extfile.cnf
   ```

3. **Сертификат клиента (CI Runner):**
   ```bash
   openssl genrsa -out key.pem 4096
   openssl req -subj "/CN=ci-client" -new -key key.pem -out client.csr
   echo "extendedKeyUsage = clientAuth" > extfile-client.cnf
   openssl x509 -req -days 3650 -sha256 -in client.csr -CA ca.pem -CAkey ca-key.pem \
     -CAcreateserial -out cert.pem -extfile extfile-client.cnf
   ```

### Сценарий 3: Распределение сертификатов CI-системе

После генерации сертификатов необходимо безопасно передать их CI-платформе:

**Вариант 1: GitLab CI (Protected Variables)**
```bash
# В GitLab: Settings → CI/CD → Variables → Protected + Masked
# Переменные:
#   TLS_CA   → base64 ca.pem
#   TLS_CERT → base64 cert.pem
#   TLS_KEY  → base64 key.pem

# В .gitlab-ci.yml:
before_script:
  - echo "$TLS_CA" | base64 -d > /tmp/ca.pem
  - echo "$TLS_CERT" | base64 -d > /tmp/cert.pem
  - echo "$TLS_KEY" | base64 -d > /tmp/key.pem
  - chmod 600 /tmp/*.pem
```

**Вариант 2: GitHub Actions (Secrets)**
```yaml
# В GitHub: Settings → Secrets → Actions
# Secret'ы: TLS_CA, TLS_CERT, TLS_KEY (base64)

# В workflow:
- name: Setup TLS
  run: |
    echo "${{ secrets.TLS_CA }}" | base64 -d > /tmp/ca.pem
    echo "${{ secrets.TLS_CERT }}" | base64 -d > /tmp/cert.pem
    echo "${{ secrets.TLS_KEY }}" | base64 -d > /tmp/key.pem
    chmod 600 /tmp/*.pem
```

**Вариант 3: HashiCorp Vault**
```bash
# Запись сертификатов в Vault
vault kv put secret/swarm/tls \
  ca=@ca.pem cert=@cert.pem key=@key.pem

# Чтение в CI (после аутентификации)
vault kv get -field=ca secret/swarm/tls > /tmp/ca.pem
vault kv get -field=cert secret/swarm/tls > /tmp/cert.pem
vault kv get -field=key secret/swarm/tls > /tmp/key.pem
```

### Сценарий 4: Конфигурация Docker Daemon

Рекомендуется использовать Systemd override для управления параметрами запуска.

1. Создайте директорию: `sudo mkdir -p /etc/systemd/system/docker.service.d`
2. Создайте файл `override.conf`:
   ```ini
   [Service]
   # Сброс ExecStart обязателен
   ExecStart=
   ExecStart=/usr/bin/dockerd -H fd:// -H tcp://0.0.0.0:2376 --tlsverify \
     --tlscacert=/etc/docker/certs/ca.pem \
     --tlscert=/etc/docker/certs/server-cert.pem \
     --tlskey=/etc/docker/certs/server-key.pem
   # Лимиты для стабильности при высокой нагрузке
   LimitNOFILE=infinity
   LimitNPROC=infinity
   ```
3. Примените настройки:
   ```bash
   sudo systemctl daemon-reload && sudo systemctl restart docker
   ```

### Сценарий 5: Создание Overlay Networks

Overlay-сети обеспечивают связь между контейнерами на разных узлах кластера:

```bash
# Создание зашифрованной Overlay-сети
docker network create \
  --opt encrypted \
  --subnet 172.240.0.0/24 \
  --gateway 172.240.0.254 \
  --attachable \
  --driver overlay \
  mynetwork

# Проверка сети
docker network ls --filter driver=overlay
# → NETWORK ID     NAME      DRIVER  SCOPE
# → abc123         mynetwork overlay swarm
```

**Ключевые параметры:**
- `--opt encrypted`: Включает IPSec-шифрование трафика между узлами (требует дополнительных ресурсов CPU).
- `--attachable`: Позволяет standalone-контейнерам подключаться к сети (полезно для отладки).
- `--subnet`: Явное указание подсети избегает конфликтов с существующими сетями.

### Сценарий 6: Управление Secrets

Secrets позволяют безопасно передавать чувствительные данные (пароли, ключи) в контейнеры:

```bash
# Создание секрета из файла
echo "SuperSecretPassword123" | docker secret create db_password -

# Список секретов
docker secret ls
# → ID                         NAME        DRIVER  CREATED         UPDATED
# → abc123def456               db_password at      2 hours ago     2 hours ago

# Использование в Compose
cat > docker-compose.yml << EOF
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

secrets:
  db_password:
    external: true
EOF

# Деплой
docker stack deploy -c docker-compose.yml myapp
```

### Сценарий 7: Настройка Health Checks

Health Checks критически важны для надежных Rolling Updates:

```dockerfile
# В Dockerfile
FROM nginx:1.27-alpine
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:80/healthz || exit 1
```

```yaml
# В Compose (переопределяет Dockerfile)
services:
  web:
    image: nginx:1.27
    deploy:
      healthcheck:
        test: ["CMD", "curl", "-f", "http://localhost/healthz"]
        interval: 30s
        timeout: 5s
        start_period: 10s
        retries: 3
```

### Сценарий 8: Rolling Update и Rollback

Swarm поддерживает поэтапное обновление с автоматическим откатом:

```yaml
services:
  api:
    image: myregistry/api:v2.1.0
    deploy:
      replicas: 5
      update_config:
        parallelism: 2
        delay: 15s
        order: start-first
        failure_action: rollback
        monitor: 30s
        max_failure_ratio: 0.2
      rollback_config:
        parallelism: 0
        order: stop-first
```

**Параметры:**
- `parallelism`: Количество реплик, обновляемых одновременно.
- `delay`: Пауза между обновлением групп.
- `order`: `start-first` (сначала поднять новый) или `stop-first` (сначала остановить старый).
- `failure_action`: `pause`, `continue` или `rollback` (автоматический откат).
- `monitor`: Время наблюдения за новой репликой после старта.

### Сценарий 9: Placement Constraints и Resource Limits

Ограничения placement и лимиты ресурсов предотвращают "задушение" узлов:

```yaml
services:
  worker:
    image: worker:latest
    deploy:
      replicas: 3
      placement:
        constraints:
          - node.role == worker
          - node.labels.zone == dmz
        preferences:
          - spread: node.labels.datacenter
      resources:
        reservations:
          cpus: '0.25'
          memory: 256M
        limits:
          cpus: '0.50'
          memory: 512M
```

```bash
# Добавление метки на узел
docker node update --label-add zone=dmz worker-1
docker node update --label-add datacenter=dc1 worker-1
```

### Сценарий 10: Drain Node для Maintenance

Плановый вывод узла из обслуживания без потери задач:

```bash
# Перевод узла в режим drain
docker node update --availability drain worker-1

# Проверка: все задачи должны быть перенесены
docker service ps myapp --no-trunc
# → Все задачи на worker-1 должны иметь статус Shutdown/Complete

# После обслуживания вернуть узел
docker node update --availability active worker-1
```

### Сценарий 11: Проверка Service Discovery

Проверка работоспособности встроенного DNS:

```bash
# Развертывание тестового сервиса
docker service create --name test-web --replicas 2 nginx:1.27-alpine

# DNS-резолв внутри кластера (на любом узле)
docker run --rm --network mynetwork alpine nslookup test-web
# → Name:      test-web
# → Address 1: 172.240.0.2 mynetwork
# → Address 2: 172.240.0.3 mynetwork

# Проверка Routing Mesh (обращение через порт на любом узле)
curl http://manager1:80
# → Должен вернуть ответ Nginx
```

### Сценарий 12: Multi-Manager HA (High Availability)

Расширение кластера до отказоустойчивой конфигурации:

```bash
# На втором менеджере (после получения токена):
docker swarm join --token <MANAGER_TOKEN> 10.0.0.1:2377

# На третьем менеджере:
docker swarm join --token <MANAGER_TOKEN> 10.0.0.1:2377

# Проверка кворума
docker node ls --filter role=manager
# Должно отображаться 3 узла

# Перевод менеджеров в режим drain (рекомендуется для HA)
for node in $(docker node ls --filter role=manager --format "{{.Hostname}}"); do
  docker node update --availability drain $node
done

# Проверка, что кластер работает (менеджеры только управляют)
docker service create --name test-alpine --replicas 3 alpine:latest sleep 3600
docker service ls
docker service ps test-alpine
# Задачи должны распределяться по worker-узлам
docker service rm test-alpine
```

## Best Practices

### Безопасность

1. **Никогда не открывайте порт 2375:** Используйте только 2376 с mTLS для удаленного доступа.
2. **Ограничьте firewall:** Порт 2376 разрешайте только с IP-адресов CI-раннеров (`ufw allow from <CI_IP> to any port 2376`).
3. **Ротация сертификатов:** Внутренние сертификаты Swarm ротируются автоматически (каждые 90 дней). Внешние сертификаты CI/CD обновляйте вручную минимум раз в год.
4. **Хранилище секретов:** Никогда не храните `ca-key.pem` или пароли в репозитории. Используйте HashiCorp Vault, GitLab Secrets или GitHub Secrets.
5. **Автоблокировка Swarm:** Включите `docker swarm update --autolock=true` для защиты данных Raft при перезагрузке менеджеров.

### Надежность

6. **Нечетное количество менеджеров:** Используйте 3 (tolerates 1 failure) или 5 (tolerates 2 failures) менеджеров. Никогда не используйте четное количество.
7. **Drain менеджеров в HA:** В production-кластерах переводите менеджеры в режим `drain`, чтобы они занимались только управлением.
8. **NTP-синхронизация:** Обязательно настройте `chrony` или `systemd-timesyncd` на всех узлах. Clock drift ломает Raft и TLS.
9. **MTU 1450 для Overlay:** Установите MTU интерфейса `docker0` в 1450 (VXLAN добавляет 50 байт заголовка).
10. **Health Checks в каждом сервисе:** Настройте `HEALTHCHECK` в Dockerfile или `deploy.healthcheck` в Compose. Без проверок здоровья Rolling Update работает вслепую.

### Производительность

11. **Resource Limits:** Всегда указывайте `resources.limits` и `resources.reservations` для каждого сервиса. Без лимитов один "съедающий" сервис может задушить весь узел.
12. **Log rotation:** Настройте `log-opts` в daemon.json (`max-size: 10m`, `max-file: 3`) для предотвращения заполнения диска.
13. **Иммутабельность образов:** Никогда не используйте тег `:latest` в production. Используйте конкретные версии или SHA256-хеши.
14. **--with-registry-auth:** Всегда используйте флаг `--with-registry-auth` в CI/CD при деплое стека с приватным registry. Без него воркеры не смогут скачать образы.
15. **Атомарность обновлений:** Используйте `order: start-first` для zero-downtime обновлений (новые реплики запускаются до остановки старых).

### Эксплуатация

16. **Мониторинг:** Разверните Prometheus + Grafana + cAdvisor для мониторинга состояния кластера, узлов и сервисов.
17. **Бэкапы:** Регулярно бэкапите Raft-лог менеджеров (`/var/lib/docker/swarm/raft/`) и данные секретов.
18. **Idempotent операции:** Все скрипты деплоя и CI/CD должны быть идемпотентными. Повторный запуск не должен ломать кластер.
19. **Валидация перед деплоем:** В CI/CD добавляйте стадию валидации Compose-файлов (`docker stack deploy --dry-run` или `docker-compose config`).
20. **Документация:** Ведите актуальный инвентарь узлов (IP, роль, метки) и токенов присоединения.

### CI/CD

21. **Ветвление:** Используйте ветку `main` для production, `develop` для staging. Деплой в production только после прохождения всех проверок.
22. **Security Scanning:** Интегрируйте Trivy или Grype в пайплайн для сканирования образов на уязвимости.
23. **Secret Detection:** Используйте Gitleaks или detect-secrets в пайплайне для предотвращения утечки ключей.
24. **Post-deploy verification:** После каждого деплоя запускайте health checks (`curl /healthz`) на всех репликах.
25. **Автоматический откат:** Настройте `failure_action: rollback` в `update_config` и добавьте gate-шаг в CI/CD с проверкой метрик Prometheus.

## Дополнительная информация

### Устранение неисправностей

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `certificate signed by unknown authority` | Несоответствие CA | Проверьте, что `ca.pem` на клиенте совпадает с тем, которым подписан `server-cert.pem`. |
| `x509: certificate is valid for <IP1>, not <IP2>` | SAN mismatch | Перевыпустите серверный сертификат, добавив `<IP2>` в `extfile.cnf`. |
| `context deadline exceeded` | Проблемы MTU | Если контейнеры в Overlay сети не видят друг друга, проверьте MTU (должен быть 1450 для VXLAN). |
| `No manager nodes are currently reachable` | Потеря кворума | Проверьте NTP на всех менеджерах. Если кворум потерян безвозвратно, используйте `docker swarm init --force-new-cluster`. |
| `rpc error: code = Unknown desc = raft: server is healthy` | Кворум уже существует | Кластер уже инициализирован. Используйте `docker swarm join-token` для получения токена. |
| `permission denied while trying to connect to the Docker daemon socket` | Права доступа | Добавьте пользователя в группу `docker`: `sudo usermod -aG docker $USER`. |
| `Error response from daemon: swarm mode already active` | Повторная инициализация | Swarm уже активен. Используйте `docker info` для проверки. |
| `failed to initialize raft node` | Проблемы с сетью | Проверьте доступность портов 2377, 7946, 4789 между менеджерами. |
| `pool overlaps with other one on this address space` | Конфликт подсетей | Выберите другую подсеть для overlay-сети: `docker network create --subnet=10.10.0.0/16`. |
| `service not found in DNS` | DNS-проблема | Проверьте, что контейнер находится в overlay-сети и имя сервиса указано без домена. |
| `task failed with no ports published` | Конфликт портов | Убедитесь, что published port не занят на узле: `ss -tlnp | grep :80`. |
| `image not found` | Отсутствие registry auth | Используйте `--with-registry-auth` при деплое или добавьте `pull_secret` в Compose. |
| `swarm mode not active` | Swarm не инициализирован | Выполните `docker swarm init` на менеджерском узле. |
| `node is already in drain mode` | Повторный drain | Узел уже выведен. Используйте `docker node update --availability active` для возврата. |
| `secret not found` | Секрет не создан | Создайте секрет на менеджере: `echo "password" \| docker secret create mysecret -`. |
| `health check failed` | Проблемы с приложением | Проверьте, что эндпоинт `/healthz` доступен изнутри контейнера: `docker exec <task> curl localhost/healthz`. |

### Связанные документы

- **[Настройка Docker Context](./docker_context_setup.md)** — управление подключениями к кластерам.
- **[Общий обзор CI/CD в Swarm](./overview.md)** — архитектура конвейера и сценарии.
- **[Основные концепции Docker Swarm](../swarm_core_concepts.md)** — теория Raft, кворум и жизненный цикл задач.
- **[Справочник CLI Swarm](../swarm_management_cli.md)** — полный справочник команд управления узлами и сервисами.
- **[Сетевое взаимодействие в Swarm](../swarm_networking.md)** — Routing Mesh и Overlay.
- **[Секреты и конфиги Swarm](../swarm_secrets_configs.md)** — безопасная доставка данных в контейнеры.
- **[Развертывание стеков](../swarm_stack_deployment.md)** — детальное использование `docker stack`.
- **[Rolling Update стратегии](../../CI-CD/Deployment_Strategies/rolling_update.md)** — поэтапное обновление и откат.
- **[Обнаружение сервисов](../../Concepts/service-discovery-overview.md)** — Service Discovery и DNS в распределенных системах.
- **[Chaos Engineering для не-Kubernetes сред](../../Chaos_Engineering/chaos_non_kubernetes.md)** — хаос-тестирование для Docker Swarm.
- **[Ansible: Управление кластером](../../Ansible/examples/docker_management.md)** — автоматизация через роли Ansible.
- **[Продвинутые темы Swarm](../swarm_advanced_topics.md)** — глубокие детали Raft, mTLS и восстановления кворума.


