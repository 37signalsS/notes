# Антипаттерны управления секретами

## Определения

**Антипаттерн управления секретами** — это распространённая, но неэффективная или опасная практика обработки конфиденциальных данных (паролей, ключей, токенов). В современной парадигме управления жизненным циклом секретов (SLM — Secret Lifecycle Management) антипаттерном считается любое статическое хранение секрета, который может быть заменён динамической выдачей или федерацией идентичности.

**Радиус поражения (Blast Radius)** — объем ресурсов и данных, к которым злоумышленник получает доступ при компрометации одного секрета. Главная цель борьбы с антипаттернами — минимизация этого радиуса.

**Секрет Зеро (Secret Zero)** — антипаттерн, при котором для получения доступа к хранилищу секретов используется другой статический секрет (например, токен в конфигурационном файле), создавая бесконечную цепочку доверия.

## Предварительные требования

Для устранения антипаттернов необходимы следующие компоненты инфраструктуры:

- **Vault** — инициализированный и расшифрованный кластер (версия 1.16+), доступный по HTTPS с доверенным сертификатом.
- **Аутентификация** — настроенный метод аутентификации, исключающий статические токены (Kubernetes auth, AppRole, JWT/OIDC).
- **Политики ACL** — гранулярные политики Vault ([Авторизация и политики](./authorization.md)) с принципом наименьших привилегий.
- **Движки секретов** — включённые и настроенные движки (KV v2, Database, PKI, SSH, Transit) для динамической выдачи.
- **Аудит** — включённый audit device (файловый или Syslog) для отслеживания всех операций.
- **Сеть** — разрешённые egress-правила между приложениями, Vault и платформой аутентификации (Kubernetes API, CI/CD платформа).

## Основные концепции

Современное управление секретами (2025–2026) перешло от модели «надёжного хранилища» к модели **«приоритета идентичности»**. Ключевая проблема большинства антипаттернов — статичность данных и избыточность прав. Kubernetes-инструменты и плагины Vault (Vault Radar, Vault Secrets Operator, Secrets Sync) позволяют устранить статические секреты как класс: генерировать их динамически и раздавать по федерации идентичности.

### Принципы предотвращения антипаттернов

1.  **Исключение Secret Zero:** Использование [федерации идентичности (WIF)](./zero_trust.md#фундаментальные-принципы-zero-trust) вместо статических токенов аутентификации.
2.  **Динамическая генерация (Just-in-Time):** Секреты должны создаваться в момент запроса и иметь минимальный срок жизни (TTL < 1 часа).
3.  **Непрерывное обнаружение (Continuous Discovery):** Использование инструментов класса **Vault Radar** для поиска секретов в Git, внутренних wikis, мессенджерах и объектных хранилищах. Радар находит активные (валидные) секреты и умеет импортировать их в Vault для дальнейшей ротации.
4.  **Изоляция сред выполнения:** Защита от утечек секретов через логи, переменные окружения и метаданные контейнеров.

## Практические сценарии

### 1. Распространение секретов (Secret Sprawl)

Секреты попадают в системы контроля версий, вики-страницы, мессенджеры и логи.

**Риск:** Бессрочная утечка данных. Даже удаление коммита в Git оставляет данные в истории и кэшах всех, кто клонировал репозиторий. Секреты, обнаруженные в коде, статистически живут в среднем **неделю**, и этого времени достаточно для автоматизированной компрометации аккаунтов.

**Решение:**

```bash
# 1. Сканирование репозитория pre-commit (Gitleaks)
gitleaks protect --staged --redact
# → 1 leaks detected. Commit blocked.

# 2. Сканирование всей истории репозитория
gitleaks detect --source /path/to/repo --redact -v
# → Finding: DB_PASSWORD in config.py:12 (high)
```

**Действия после обнаружения:**
1. Немедленно отозвать скомпрометированный секрет (ротация пароля, отзыв токена).
2. Удалить секрет из истории Git (BFG Repo-Cleaner или `git filter-repo`).
3. Принудительно обновить все клоны репозитория.
4. Записать инцидент в журнал аудита Vault.

**Vault Radar:** Автоматическое сканирование всей инфраструктуры (Git, внутренние wikis, мессенджеры, объектные хранилища, логи) с приоритизацией по критичности. Находит активные секреты и импортирует их в Vault для ротации.

### 2. Использование Secret Zero

Приложение хранит статический токен Vault в файле или переменной окружения, чтобы пройти аутентификацию.

**Риск:** Компрометация одного токена дает доступ ко всем секретам приложения. Создаётся бесконечная цепочка доверия — для получения доступа к Vault нужен токен, для получения токена нужен другой секрет, и так далее.

**Решение:**

```bash
# Вариант A: Kubernetes Auth (ServiceAccount JWT)
vault write auth/kubernetes/config \
    kubernetes_host="https://kubernetes.default.svc" \
    token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"

# Создание роли, связанной с ServiceAccount
vault write auth/kubernetes/role/myapp-role \
    bound_service_account_names="myapp-sa" \
    bound_service_account_namespaces="production" \
    policies="myapp-policy" \
    ttl=1h

# Вариант B: AppRole (для гибридных сред)
vault write auth/approle/role/myapp-role \
    token_ttl=1h \
    token_max_ttl=24h \
    policies="myapp-policy"

# Получение Role-ID и Secret-ID
vault read auth/approle/role/myapp-role/role-id
vault write -f auth/approle/role/myapp-role/secret-id
```

**Kubernetes Integration (Vault Agent Sidecar):**

```yaml
# Внедрение Vault Agent в под без статических токенов
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  serviceAccountName: myapp-sa
  containers:
    - name: app
      image: myapp:latest
      env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: vault-token
              key: DB_PASSWORD
    - name: vault-agent
      image: vault:latest
      command: ["vault", "agent", "-config=/etc/vault/agent-config.hcl"]
```

### 3. Секреты в слоях образов и переменных окружения

Хранение паролей в `Dockerfile` или использование `ENV` в Kubernetes.

**Риск:** Секреты видны через `docker history`, `kubectl describe pod` или `/proc/1/environ`. Во время сборки секреты попадают в слои образа; в рантайме — в конфигурацию пода и окружение процессов. Эти данные кэшируются в регистре и логах оркестратора.

**Решение:**

```bash
# BuildKit Secrets — секрет не остаётся в слоях образа
docker build --secret id=db_password,env=DB_PASSWORD -t myapp:latest .
# → Секрет доступен только во время RUN, не сохраняется в образ

# Проверка: секрета нет в истории образа
docker history myapp:latest
# → Слои не содержат секретных данных
```

```yaml
# Kubernetes: Vault Agent Sidecar с эфемерным томом
apiVersion: v1
kind: Pod
metadata:
  name: myapp
spec:
  containers:
    - name: app
      image: myapp:latest
      volumeMounts:
        - name: vault-secrets
          mountPath: /secrets
          readOnly: true
    - name: vault-agent
      image: vault:latest
      volumeMounts:
        - name: vault-secrets
          mountPath: /secrets
      volumes:
        - name: vault-secrets
          emptyDir:
            medium: Memory  # tmpfs — секреты только в памяти
```

### 4. Статическая синхронизация секретов

Автоматическое копирование статических паролей из Vault в внешние системы управления секретами.

**Риск:** Создание дубликатов долгоживущих секретов, что усложняет аудит и ротацию. При изменении секрета в Vault нужно синхронизировать все копии, что практически невозможно при большом числе систем.

**Решение:** Прямое использование динамических движков Vault. Если система не поддерживает нативную интеграцию — использовать механизм [Secrets Sync](./overview.md#ключевые-преимущества) только для целевых систем, поддерживающих интеграцию.

```bash
# Создание динамического секрета базы данных (вместо статического пароля)
vault write database/config/myapp \
    plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@db.example.com:5432/myapp" \
    allowed_roles="myapp-role" \
    username="vault_admin" \
    password="static_admin_password"

# Создание роли с TTL 1 час
vault write database/roles/myapp-role \
    db_name=myapp \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';" \
    default_ttl=1h \
    max_ttl=24h

# Приложение получает динамические credentials
vault read database/creds/myapp-role
# → lease_id, lease_duration, username, password (уникальные для этого запроса)
```

### 5. Логирование чувствительных данных

Вывод паролей, токенов, заголовков `Authorization` и полей конфигурации в `stdout`/`stderr` (включая отладочный режим).

**Риск:** Секреты попадают в системы сбора логов (ELK, Loki, Graylog, Promtail), становятся доступны широкому кругу лиц и часто записываются в долгосрочные архивы без ограничений доступа. Данные в логах при этом могут дублироваться в неограниченном количестве без истечения срока действия.

**Решение:**

```bash
# 1. Маскирование секретов в логах приложения (пример для Python)
import logging
import re

class SecretFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'password=[^&\s]+', 'password=[REDACTED]', str(record.msg))
        return True

logger.addFilter(SecretFilter())

# 2. Санитайзеры в логической pipeline (Vector/Fluent Bit)
# vector.toml
[transforms.redact_secrets]
type = "regex"
pattern = '(?i)(password|token|secret|key)\s*[=:]\s*["\']?([^"\'\\s]+)'
replace = '${1}=[REDACTED]'
```

**Vault Audit Device — обязательный канал:**

```bash
# Включение файлового аудита (отдельный канал, не дублируемый в прикладные логи)
vault audit enable file file_path=/var/log/vault/audit.log

# Проверка работы
tail -f /var/log/vault/audit.log | head
# → {"type":"request","path":"secret/myapp/db","data":null,...}
```

### 6. Передача секретов через небезопасные каналы

Передача API-ключей, паролей и токенов через мессенджеры, электронную почту, общие файловые ресурсы или личные устройства.

**Риск:** Отсутствие контроля доступа, невозможность ротации без уведомления всех получателей, отсутствие аудита. Секреты в мессенджерах хранятся на серверах третьих лиц без шифрования end-to-end.

**Решение:**

```bash
# Корректный способ передачи: Vault Secret Sharing (Response Wrapping)
# Отправитель создаёт одноразовый токен доступа
vault read -wrap-ttl=1h secret/myapp/db
# → wrapped_token: s.XXXXX

# Получатель использует wrapped_token для получения секрета
vault unwrap s.XXXXX
# → {"password":"dynamic_password","username":"app_user"}

# Преимущества:
# - Секрет не передаётся в открытом виде
# - TTL 1 час — токен автоматически истекает
# - Отправитель может отозвать wrapped_token до истечения TTL
# - Вся активность логируется audit-устройством
```

### 7. Избыточные права доступа (IAM/RBAC)

Широкие политики (например, `path "secret/*" { capabilities = ["read", "list", "create", "update", "delete"] }`) или унаследованные учётные записи с правами администратора.

**Риск:** Даже короткоживущий секрет или скомпрометированная учётная даёт злоумышленнику весь радиус действия политики. Избыточные права напрямую расширяют радиус поражения при компрометации одного секрета.

**Решение:**

```bash
# Проверка текущих прав токена
vault token capabilities secret/myapp/config
# → read, list

# Аудит всех политик на предмет wildcards
vault list sys/policy
vault read sys/policy/myapp-policy
# → Проверить path и capabilities

# Пример гранулярной политики (myapp-policy.hcl)
path "secret/data/myapp/*" {
  capabilities = ["read"]
  allowed_parameters = {"version" = "1"}
}

path "secret/metadata/myapp/*" {
  capabilities = ["read", "list"]
}

# Применение политики
vault policy write myapp-policy myapp-policy.hcl

# Проверка: политика не даёт прав на другие пути
vault token capabilities secret/other-app/config
# → deny
```

## Дополнительная информация

### Сравнение рисков и стратегий защиты (2026)

| Антипаттерн | Уровень риска | Современное решение | Инструментарий |
| :--- | :--- | :--- | :--- |
| **Секреты в Git** | Критический | Vault Radar + Pre-commit | Gitleaks, Vault Radar |
| **Secret Zero** | Высокий | Workload Identity Federation | OIDC, Kubernetes Auth |
| **ENV переменные** | Средний | Монтирование в tmpfs / VSO | Vault Secrets Operator, CSI Driver |
| **Слои образа** | Высокий | BuildKit Secrets, multi-stage | BuildKit |
| **Статическая синхронизация** | Низкий | Динамические секреты (JIT) | Database Engine |
| **Логирование секретов** | Средний | Маскирование, санитайзеры | Vector, Fluent Bit |
| **Избыточные права** | Высокий | Гранулярные ACL-политики | Vault Policy, Sentinel |
| **Небезопасная передача** | Средний | Response Wrapping | Vault Wrapping Tokens |

### Типичные ошибки и их устранение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Токен не продлевается** | У секрета `renewable=false` (статические секреты KV v1) | Использовать динамические секреты (Database, PKI, SSH) или настроить renew на уровне AppRole/Kubernetes auth |
| **Vault Agent не получает секреты** | Неверный ServiceAccount или политика | Проверить `bound_service_account_names` и `vault token capabilities` |
| **Секреты видны в `docker inspect`** | Используется `ENV` вместо BuildKit secrets или mounted volume | Перенести секреты в BuildKit `--secret` или mounted volume |
| **Ротация не работает** | Статические секреты не имеют TTL | Перейти на динамические движки Vault (Database, SSH, PKI) |
| **Pre-commit пропускает секреты** | Устаревшие правила Gitleaks | Обновить правила: `gitleaks update` |
| **Audit log заполняется** | Чрезмерное логирование `request` вместо `response` | Использовать `audit log_request_response` осторожно или включить только `log_request` |

### Лучшие практики

1. **Отказ от Secret Zero:** Используйте федерацию идентичности (OIDC, Kubernetes, AppRole) вместо статических токенов аутентификации.
2. **Минимальные TTL:** Настраивайте максимально возможные ограничения по времени жизни секретов. Для баз данных рекомендуется TTL < 1 часа.
3. **Автоматическая ротация:** Настройте автоматическое продление (`renew`) и перевыпуск токенов через Vault Agent. Ручная ротация — источник человеческой ошибки.
4. **KV v2:** Используйте KV v2 для всех новых хранилищ — он поддерживает версионирование и каскадное удаление.
5. **Response Wrapping:** Используйте `-wrap-ttl` для передачи секретов между сервисами — исключает необходимость общего статического секрета.
6. **Аудит:** Включите audit device с самого начала развёртывания Vault. Без аудита невозможно отследить источник утечки.
7. **Namespaces (Enterprise):** Используйте Namespaces для изоляции сред (dev/staging/prod) — политики не пересекаются между namespace.
8. **Shamir:** Храните ключи Shamir у разных администраторов (минимум 3 из 5). Никогда не храните все ключи на одном носителе.

### Границы применимости и ограничения

- **Dynamic Secrets не универсальны:** Некоторые legacy-системы не поддерживают динамическое изменение паролей (например, статические API-ключи в SaaS). Для таких систем используйте Vault Radar для обнаружения и автоматической ротации.
- **Требует сетевой доступности:** Приложения должны иметь возможность соединяться с Vault. В air-gapped средах разворачивайте Vault внутри периметра и используйте Vault Agent для кэширования.
- **TTL vs. graceful reload:** Приложение должно корректно обрабатывать смену пароля (graceful reload) при истечении TTL. Без этого возможны короткие простои.
- **Secret Zero неизбежен на старте:** При первоначальном развёртывании Secret Zero временно необходим. Цель — минимизировать время его жизни и заменить на федерацию идентичности как можно быстрее.

### Связанные документы

*   **[Подход Zero Trust](./zero_trust.md)** — архитектурные основы федерации идентичности.
*   **[Обзор Vault](./overview.md)** — возможности SLM и динамические движки.
*   **[Авторизация в Vault](./authorization.md)** — политики доступа и принцип наименьших привилегий.
*   **[Интеграция Vault с Kubernetes](./guides/vault_kubernetes_integration.md)** — примеры VSO, CSI Driver и Injector.
*   **[SSH Secrets Engine](./guides/ssh_secrets_engine.md)** — динамические SSH-ключи и сертификаты.
*   **[Database Secrets Engine](./guides/database_secrets_engine.md)** — динамические учетные данные баз данных.
*   **[PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md)** — Intermediate CA, ACME, CRL/OCSP.
*   **[Производительность и репликация](./performance_and_replication.md)** — Performance Standby, DR Replication.
*   **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — Prometheus, Grafana, SLO/SLI.
*   **[Анализ audit логов](./audit_log_analysis.md)** — SIEM, forensic, compliance.
*   **[Ротация секретов](./secret_rotation.md)** — стратегии ротации.
*   **[Namespaces](./namespaces.md)** — изоляция сред (Enterprise).
*   **[SLM, Vault Radar, Secrets Sync](./slm_radar_secrets_sync.md)** — Security Lifecycle Management.
*   **[Производительность и тюнинг](./performance_tuning.md)** — оптимизация для high-load.
*   **[Vault API Reference](./vault_api_reference.md)** — REST API и endpoints.
*   **[Cubbyhole и Response Wrapping](./cubbyhole_response_wrapping.md)** — безопасная доставка секретов.
*   **[Control Groups](./control_groups.md)** — multi-approval для критических операций.
*   **[Стратегии бэкапов и восстановления](./backup_restore_strategies.md)** — RPO/RTO, disaster recovery.
