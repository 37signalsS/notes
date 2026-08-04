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

### Сценарий 3: Конфигурация Docker Daemon

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

### Сценарий 4: Проверка и диагностика

```bash
# Проверка, что API доступен по TLS
docker --tlsverify --tlscacert=ca.pem --tlscert=cert.pem --tlskey=key.pem \
  -H 10.0.0.1:2376 info
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

### Связанные документы

- **[Настройка Docker Context](./docker_context_setup.md)** — управление подключениями.
- **[Общий обзор CI/CD в Swarm](./overview.md)** — архитектура конвейера.
- **[Справочник CLI Swarm](../swarm_management_cli.md)** — полезные команды управления.
- **[Ansible: Управление кластером](../../Ansible/examples/docker_management.md)** — автоматизация через роли.
- **[Секреты и конфиги Swarm](../swarm_secrets_configs.md)** — безопасная доставка данных.

