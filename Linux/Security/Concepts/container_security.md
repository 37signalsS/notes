# Безопасность контейнеров: Концепции и механизмы

## Определения

**Container Security** — комплекс мер по защите контейнеров (Docker, Podman, LXC) и оркестраторов (Kubernetes) от угроз на всех этапах жизненного цикла: сборка, хранение, запуск, выполнение. Контейнеры разделяют ядро хоста, что создает уникальные векторы атак по сравнению с виртуальными машинами.

**Ключевые понятия:**
- **Namespace** — изоляция ресурсов (PID, Network, Mount, User)
- **Cgroups** — ограничение ресурсов (CPU, память, I/O)
- **Capabilities** — гранулярные привилегии вместо полного root
- **Seccomp** — фильтрация системных вызовов
- **LSM (SELinux/AppArmor)** — принудительный контроль доступа

## Теоретический блок

### Модель угроз контейнеров

| Угроза | Описание | Механизм защиты |
| :--- | :--- | :--- |
| **Container Escape** | Побег контейнера в пространство хоста | User Namespaces, capabilities, seccomp |
| **Разделение ядра** | Уязвимость ядра влияет на все контейнеры | Обновление ядра,最小化 образов |
| **Неправильная конфигурация** | Избыточные привилегии, открытые порты | Security Context, Network Policies |
| **Вредоносный образ** | Бэкдоры, уязвимости в зависимостях | Сканирование образов, SBOM |
| **Компрометация реестра** | Подмена образов, утечка секретов | Подпись образов, RBAC |

### Уровни защиты контейнеров

| Уровень | Механизмы | Описание |
| :--- | :--- | :--- |
| **Образ** | Minimal base images, scanning, signing | Безопасность на этапе сборки |
| **Контейнер** | Security Context, capabilities, seccomp | Изоляция при запуске |
| **Сеть** | Network Policies, CNI | Сегментация трафика |
| **Оркестратор** | RBAC, Admission Controllers, Pod Security | Контроль доступа к API |
| **Хост** | Hardened OS, LSM, auditd | Защита базовой системы |

### Security Context в Kubernetes

**SecurityContext** — набор настроек безопасности, применяемых на уровне Pod или контейнера.

**Ключевые параметры:**

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `runAsNonRoot` | Запрет запуска от root | `true` для всех контейнеров |
| `runAsUser` | UID запуска | Использовать непривилегированные UID |
| `readOnlyRootFilesystem` | Только чтение для корневой ФС | `true` (кроме случаев записи) |
| `allowPrivilegeEscalation` | Запрет повышения привилегий | `false` |
| `capabilities.drop` | Удаление capabilities | `["ALL"]` + добавить только необходимые |
| `seccompProfile.type` | Профиль seccomp | `RuntimeDefault` или `Localhost` |

### Pod Security Standards (PSS)

| Уровень | Описание | Ключевые ограничения |
| :--- | :--- | :--- |
| **Privileged** | Без ограничений | Запрещен в production |
| **Baseline** | Минимальные ограничения | Запрет privileged, hostNetwork, hostPID |
| **Restricted** | Строгие ограничения | Требует runAsNonRoot, drop ALL, seccomp |

## Практический блок

### Безопасная конфигурация Docker

```dockerfile
# Использование минимального образа
FROM alpine:3.19

# Создание непривилегированного пользователя
RUN addgroup -g 1001 appgroup && \
    adduser -u 1001 -G appgroup -s /bin/sh -D appuser

# Установка приложения
RUN apk --no-cache add nginx && \
    rm -rf /var/cache/apk/*

# Копирование конфигурации
COPY nginx.conf /etc/nginx/nginx.conf
COPY --chown=appuser:appgroup ./app /usr/share/nginx/html

# Переключение на непривилегированного пользователя
USER appuser

# Экспорт порта
EXPOSE 8080

# Запуск
CMD ["nginx", "-g", "daemon off;"]
```

### Безопасный запуск Docker-контейнера

```bash
# Запуск с минимальными привилегиями
docker run \
  --rm \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --security-opt=no-new-privileges:true \
  --security-opt=seccomp:default \
  --read-only \
  --tmpfs /tmp \
  -v /var/log/app:/var/log/app:Z \
  -p 8080:8080 \
  myapp:latest

# Проверка безопасности
docker inspect myapp | grep -E 'CapDrop|CapAdd|SecurityOpt|ReadonlyRootfs'
```

### Security Context в Kubernetes

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-pod
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1001
    runAsGroup: 1001
    fsGroup: 1001
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: myapp:latest
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop:
        - ALL
        add:
        - NET_BIND_SERVICE
    volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: app-log
      mountPath: /var/log/app
  volumes:
  - name: tmp
    emptyDir: {}
  - name: app-log
    emptyDir: {}
```

### Network Policies для изоляции

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-web-to-api
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: web
    ports:
    - protocol: TCP
      port: 8080
```

### Сканирование уязвимостей образов

```bash
# Trivy - сканирование образов
trivy image myapp:latest
trivy image --severity HIGH,CRITICAL myapp:latest

# Сканирование файловой системы
trivy fs --security-checks vuln,secret .

# Grype - альтернативный сканер
grype myapp:latest

# Сканирование SBOM
syft myapp:latest -o spdx-json > sbom.json
grype sbom:sbom.json
```

### Подпись и верификация образов

```bash
# Установка cosign
go install github.com/sigstore/cosign/v2/cmd/cosign@latest

# Генерация ключей
cosign generate-key-pair

# Подпись образа
cosign sign --key cosign.key registry.example.com/myapp:v1.0.0

# Верификация подписи
cosign verify --key cosign.pub registry.example.com/myapp:v1.0.0

# Keyless подпись (OIDC)
cosign sign registry.example.com/myapp:v1.0.0
cosign verify \
  --certificate-identity-regexp ".*@mycompany\.com" \
  --certificate-oidc-issuer-regexp "https://token.actions.githubusercontent.com" \
  registry.example.com/myapp:v1.0.0
```

## Дополнительная информация

### Инструменты контейнерной безопасности

| Инструмент | Назначение | Тип |
| :--- | :--- | :--- |
| **Trivy** | Сканирование уязвимостей образов | Open Source |
| **Grype** | Сканирование уязвимостей | Open Source |
| **Cosign** | Подпись и верификация образов | Open Source |
| **Falco** | Runtime security мониторинг | Open Source |
| **Tetragon** | Runtime enforcement через eBPF | Open Source |
| **Kyverno** | Policy-as-code для Kubernetes | Open Source |
| **OPA Gatekeeper** | Policy-as-code для Kubernetes | Open Source |

### CIS Benchmarks

- **CIS Docker Benchmark** — рекомендации по безопасной конфигурации Docker
- **CIS Kubernetes Benchmark** — рекомендации для Kubernetes
- **CIS Docker Enterprise Benchmark** — для Docker Enterprise

### Лучшие практики

1. **Минимальные образы**: используйте distroless, alpine,scratch
2. **Непривилегированный запуск**: всегда `runAsNonRoot: true`
3. **Drop ALL capabilities**: добавляйте только необходимые
4. **ReadOnlyRootFilesystem**: защита от модификации
5. **Seccomp RuntimeDefault**: фильтрация системных вызовов
6. **Network Policies**: сегментация трафика
7. **Сканирование образов**: интеграция в CI/CD
8. **Подпись образов**: верификация перед деплоем

### Связанные темы

- **[User Namespaces](../../Linux/Core/namespaces.md)** — изоляция UID/GID
- **[Linux Capabilities](../Mechanisms/Capabilities.md)** — гранулярные привилегии
- **[SELinux](../Mechanisms/SELinux.md)**, **[AppArmor](../Mechanisms/AppArmor.md)** — принудительный контроль доступа
- **[Seccomp](../Mechanisms/Seccomp.md)** — фильтрация системных вызовов
- **[Landlock](../Mechanisms/Landlock.md)** — self-sandboxing
- **[Безопасность модулей ядра](../Mechanisms/kernel_module_security.md)** — подпись и контроль загрузки модулей
- **[Auditd](../../Linux/SystemAdministration/Logging/auditd.md)** — аудит контейнерных событий
- **[Сканирование образов](../../Docker/Docker_security/vulnerability_scanning.md)** — Trivy, Grype
- **[Харденинг контейнеров](../../Docker/Docker_security/container_hardening.md)** — практические рекомендации
- **[Docker daemon hardening](../../Docker/Docker_security/host_daemon_hardening.md)** — защита хоста
- **[Управление секретами](../../Vault/guides/vault_docker_integration.md)** — Vault + Docker
