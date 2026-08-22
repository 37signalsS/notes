# CI/CD в Docker Swarm: Подготовка и настройка кластера

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
| **2377 / TCP** | Cluster Management | Коммуникации между менеджерами |
| **7946 / TCP + UDP** | Node Discovery | Обнаружение узлов и обмен состоянием |
| **4789 / UDP** | Overlay Traffic | Трафик сетей Overlay (VXLAN) |

> **Важно:** Синхронизация времени (NTP) критически важна для алгоритма Raft. Разница во времени между менеджерами более чем в несколько секунд может привести к потере кворума.

### Кворум и надежность

- **Нечетное количество:** Для обеспечения отказоустойчивости используйте 3 или 5 менеджеров.
- **Availability:** Менеджеры также выполняют роль рабочих узлов по умолчанию. В нагруженных кластерах рекомендуется переводить менеджеры в режим `drain` (`docker node update --availability drain <NODE>`), чтобы они занимались только управлением.

### Pre-flight проверка перед развертыванием

Перед настройкой кластера убедитесь в готовности инфраструктуры:

```bash
# 1. Проверка версии Docker (минимум 20.10+)
docker --version
# Ожидаемый вывод: Docker version 27.x+

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

### Сценарий 6: Проверка и диагностика

Полная проверка работоспособности кластера после развертывания:

```bash
# 1. Проверка доступности API по TLS
docker --tlsverify --tlscacert=ca.pem --tlscert=cert.pem --tlskey=key.pem \
  -H 10.0.0.1:2376 info

# 2. Состояние узлов кластера
docker node ls
# Ожидаемый вывод: все узлы в статусе Ready

# 3. Проверка кворума менеджеров
docker node ls --filter role=manager
# Должно быть нечетное число (3 или 5)

# 4. Проверка доступности сервисов
docker service ls
# Все сервисы в статусе Replicated

# 5. Проверка сетей Overlay
docker network ls --filter driver=overlay

# 6. Проверка логов менеджера (в случае проблем)
docker service logs swarm_manager --tail 50

# 7. Тестирование swap-менеджера (failover)
docker node ls --filter role=manager --format "{{.Hostname}} {{.ManagerStatus}}"
# Leader должен быть одним из узлов
```

### Сценарий 7: Multi-Manager HA (High Availability)

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

## Дополнительная информация

### Безопасность и эксплуатация

- **Firewall:** Ограничьте входящий трафик на порт 2376 только с IP-адресов CI-раннеров (например, через `ufw allow from <CI_IP> to any port 2376`).
- **Ротация:** Сертификаты Swarm (внутренние) ротируются автоматически. Сертификаты для CI/CD (внешние) необходимо обновлять вручную (рекомендуется раз в год).
- **Секреты:** Никогда не храните `ca-key.pem` в репозитории. Используйте защищенные хранилища (HashiCorp Vault, GitLab Secrets).

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

### Связанные документы

- **[Настройка Docker Context](./docker_context_setup.md)** — управление подключениями к кластерам.
- **[Общий обзор CI/CD в Swarm](./overview.md)** — архитектура конвейера и сценарии.
- **[Справочник CLI Swarm](../swarm_management_cli.md)** — полезные команды управления узлами и сервисами.
- **[Ansible: Управление кластером](../../Ansible/examples/docker_management.md)** — автоматизация через роли Ansible.
- **[Секреты и конфиги Swarm](../swarm_secrets_configs.md)** — безопасная доставка данных в контейнеры.
- **[swarm_volumes_advanced.md](../swarm_volumes_advanced.md)** — CSI-драйверы и Cluster Volumes.

