# Безопасность реестров образов

**Актуально для:** Docker Engine 29.x, Docker Registry 2.x–3.x, Harbor 2.11+.

Гигиена public-реестров (typo-squatting, rate limits) — в [public_registry_security.md](../Docker_registries/public_registry_security.md); версионирование и immutable tags — в [image_versioning_and_tagging.md](../Docker_registries/image_versioning_and_tagging.md); Harbor — в [Harbor/](../Docker_registries/Harbor/); GC и retention — в [cleanup_gc_strategies.md](../Docker_fs/cleanup_gc_strategies.md). Данный файл — security-разрез: угрозы, контроль доступа, подписи, сканирование, network hardening, аудит.

## Определения

**Registry** — хранилище образов (Docker Hub, Harbor, GitLab Container Registry, distribution). Реестр — компонент supply chain: скомпрометированный registry = скомпрометированные все развёртывания.

**Repository / tag / digest** — образ адресуется `registry/repo:tag`; digest (`@sha256:...`) — криптографический хеш манифеста, неизменяемый.

**Immutable tag** — тег, который нельзя перезаписать (Harbor: immutable tags; Registry: политика). Предотвращает подмену образа под известным именем.

**Content trust / cosign / notation** — подпись образов: Docker Content Trust (DCT, Notary v1 — устарел, вывод из эксплуатации с 30.07.2025, `notary.docker.io` отключается 08.12.2026), Cosign (Sigstore, keyless, OCI 1.1 Referrers) и Notation (Notary Project, PKI). Проверка подписи перед запуском.

**OCI 1.1 Referrers** — стандарт связи артефактов (подписей, SBOM, provenance) с образом через API реестра без использования тегов-пустышек. Harbor 2.11+, GHCR и Docker Hub поддерживают.

**Dependency confusion** — атака: злоумышленник публикует пакет с именем внутреннего в public registry; сборщик тянет public-версию.

**Robot Account** — сервисный аккаунт реестра для CI/CD с минимальными правами и сроком действия, не привязан к личности сотрудника.

**VSA (Verification Summary Attestation)** — агрегированная аттестация, подтверждающая, что образ прошёл проверку подписи, SLSA-уровня и наличия валидного SBOM. Используется Admission Controllers для принятия решения о развёртывании.

**Proxy Cache** — режим работы реестра, при котором локальный реестр кэширует образы из upstream (например, Docker Hub), позволяя обходить rate limits и применять централизованные политики безопасности.

## Предварительные требования

- **Docker Engine 29.x** — `docker login`, `docker push/pull`, `docker inspect`.
- **Cosign v3.x** — подпись и верификация образов (keyless OIDC, OCI 1.1 Referrers по умолчанию).
- **Notation v1.x** — корпоративная подпись через X.509 PKI.
- **Harbor 2.11+** — реестр с поддержкой OCI 1.1 Referrers, RBAC, сканирование.
- **Trivy ≥ 0.70.1** (≥ 0.74.x) — сканирование уязвимостей; критично из-за CVE-2026-33634 (компрометация образов сканера).
- **Kyverno 1.19+** или **OPA Gatekeeper** — admission control для принудительной проверки подписей в Kubernetes.
- **curl, jq, openssl** — проверка лимитов, API, сертификатов.
- **Skopeo** (опционально) — копирование образов между реестрами, инспекция без Docker daemon.

## Базовые концепции

### Модель угроз реестра

| Угроза | Вектор | Последствия | Контроль |
| :--- | :--- | :--- | :--- |
| Зловредный образ | Пуш в shared-repo, typo-squatting | RCE на всех хостах | Сканирование, подписи, RBAC |
| Подмена тега | Перезапись `:latest` | Незаметная замена образа | Immutable tags, пининг по digest |
| Непроверенный pull | Нет сканирования при pull | Уязвимости в production | Admission-контроль, Trivy в CI |
| Утечка образов | Открытый registry, слабый RBAC | Утечка IP/секретов в слоях | Auth, приватность, аудит |
| Supply chain | Dependency confusion, скомпрометированная база | Внедрение на этапе сборки | Приватный registry как единственный источник, provenance |
| Кражу credential-ов | Секреты в CI/CD переменных, логи | Неавторизованный доступ к registry | Vault/Sealed Secrets, robot-аккаунты с expiration |
| DDoS registry | Flood pull-запросами | Отказ сервиса для production | Proxy Cache, rate limiting на ingress |

### Registry как контрольная точка supply chain

Образ — единственный артефакт между сборкой и production. Если registry не проверяет (сканирование, подпись, RBAC), все остальные контроли (seccomp, capabilities) работают с уже скомпрометированным кодом. Поэтому реестр — точка enforcement: **не просканирован и не подписан — не развёртывается**.

### Архитектура защиты реестра

Защита делится на три слоя:

1. **Сетевой слой:** TLS 1.2+ для всех подключений, изоляция в доверенной сети (или VPN/zero-trust), firewall rules (registry доступен только из CI/CD и production-хостов), ingress controller с rate limiting. Для Docker Registry 2.x/3.x: `REGISTRY_HTTP_TLS_CERTIFICATE`, `REGISTRY_HTTP_TLS_KEY`.
2. **Слой аутентификации и авторизации:** htpasswd/LDAP/OIDC (через Harbor), RBAC (Guest/Developer/Admin), robot-аккаунты для CI/CD с expiration и минимальными правами. Harbor: дефолтные credentials (`admin` / `Harbor12345`) — первое, что меняют при установке.
3. **Слой артефактов:** сканирование при push (Harbor/Trivy), блокировка по политике (Critical CVE без fixed), подписи (Cosign/Notation через OCI 1.1 Referrers), immutable tags для release-тегов, retention policies, audit log с форвардингом в SIEM.

## Практические сценарии

### Сценарий 1: Приватный Docker Registry 2.x/3.x с TLS и RBAC

```bash
mkdir -p /etc/docker-registry/{auth,certs,data}
htpasswd -Bbn deploy-user 'StrongPassword' > /etc/docker-registry/auth/htpasswd

openssl req -x509 -newkey rsa:4096 -sha256 -days 365 \
  -keyout /etc/docker-registry/certs/domain.key \
  -out /etc/docker-registry/certs/domain.crt \
  -subj "/CN=registry.example.com" \
  -addext "subjectAltName=DNS:registry.example.com,DNS:registry"

docker run -d --name registry --restart=always \
  -p 5000:5000 \
  -v /etc/docker-registry/data:/var/lib/registry \
  -v /etc/docker-registry/certs:/certs:ro \
  -v /etc/docker-registry/auth:/auth:ro \
  -e REGISTRY_HTTP_TLS_CERTIFICATE=/certs/domain.crt \
  -e REGISTRY_HTTP_TLS_KEY=/certs/domain.key \
  -e REGISTRY_AUTH=htpasswd \
  -e REGISTRY_AUTH_HTPASSWD_REALM="Registry" \
  -e REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd \
  -e REGISTRY_STORAGE_DELETE_ENABLED=true \
  -e REGISTRY_STORAGE_DELETE_HEADERS_ENABLED=true \
  registry:2

sudo mkdir -p /etc/docker/certs.d/registry.example.com:5000
sudo cp /etc/docker-registry/certs/domain.crt /etc/docker/certs.d/registry.example.com:5000/ca.crt
sudo systemctl restart docker

docker login registry.example.com:5000
docker tag my-app:latest registry.example.com:5000/my-app:v1.2.3
docker push registry.example.com:5000/my-app:v1.2.3
```

**Валидация:**
```bash
curl -sk https://registry.example.com:5000/v2/ -o /dev/null -w "%{http_code}\n"
# → 200

curl -sk https://registry.example.com:5000/v2/_catalog -o /dev/null -w "%{http_code}\n"
# → 401 (auth работает)

docker logout registry.example.com:5000 && docker push registry.example.com:5000/my-app:v1.2.3
# → denied: authorization failed
```

**Настройка клиентов:** insecure-registries только для localhost/air-gapped dev; для production — TLS с валидным CA (иначе `docker: unable to ping registry endpoint`). Docker Engine 29.x: `insecure-registries` в `/etc/docker/daemon.json`.

### Сценарий 2: Подписи образов (cosign, keyless)

```bash
# Keyless подпись (OIDC через GitHub Actions / GitLab CI)
cosign sign --yes my-registry.example.com:5000/my-app:v1.2.3

# Проверка перед запуском
cosign verify --certificate-identity-regexp '.*' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  my-registry.example.com:5000/my-app:v1.2.3

# Attestation (SBOM как аттестация)
cosign attest --predicate sbom.json --type spdx \
  my-registry.example.com:5000/my-app:v1.2.3
```

**Валидация:**
```bash
# Exit code 0 — образ подписан
cosign verify --key cosign.pub my-registry.example.com:5000/my-app:v1.2.3 && echo "OK"
# → Verification OK

# Проверка Referrers API (Harbor 2.11+)
curl -u "robot$production+ci-bot:$ROBOT_SECRET" \
  "https://harbor.example.com/v2/production/manifests/sha256:abcd.../referrers"
# → 200 OK со списком подписей/аттестаций
```

Docker Content Trust (DCT/Notary v1) **устарел**: сервис `notary.docker.io` отключается 08.12.2026, сертификаты DOI официальных образов истекают с 08.08.2025. Используйте Cosign или Notation.

### Сценарий 3: Сканирование в registry (Harbor / Clair)

Harbor интегрирует Trivy/Clair: сканирование при push, блокировка развёртывания по политике.

```bash
# Сканирование образа (локально, до пуша)
trivy image --severity CRITICAL,HIGH --ignore-unfixed my-app:v1.2.3

# Harbor: политика "block on critical" — проект → Vulnerability Policy
# Push образа с CRITICAL без fixed-версии отклоняется
```

### Сценарий 4: Контроль доступа и аудит

**RBAC (Harbor):** проекты с ролями Developer (push/pull), Guest (pull), Admin; робот-аккаунты для CI с минимальными правами и expiration.

**Аудит:** Harbor Audit Log — кто, когда, какой образ пушил/пуллил; форвардинг в SIEM через webhook или syslog. В distribution — access logs на уровне HTTP-сервера.

**Принцип единого источника:** production-хосты тянут образы **только** из приватного registry; public-реестры — только для базовых образов на этапе сборки (проверенных по digest).

### Сценарий 5: Пининг по digest и immutable tags

```bash
# Пининг по digest (неизменяемая ссылка)
docker pull nginx@sha256:abc123def456...

# Harbor: immutable tag — политика проекта
# Project → Configuration → Immutable Tags: **
# → повторный push в существующий тег отклоняется
```

### Сценарий 6: Сетевая изоляция и mTLS между сервисами и registry

В enterprise-среде registry доступен только из CI/CD подсетей и production-хостов. Для zero-trust окружений — mTLS между клиентами и registry.

```bash
# Harbor: сертификаты клиента (mutual TLS)
# Project → Configuration → Certificate: upload client cert for pull

# containerd hosts.toml:
[host."registry.example.com:5000"]
  capabilities = ["pull", "resolve"]
  tls = true
  tls_client_cert = "/etc/certs/client.crt"
  tls_client_key = "/etc/certs/client.key"
```

### Сценарий 7: Мониторинг и алерты registry

```bash
# Harbor: Prometheus метрики
curl -s http://harbor.example.com:9090/metrics | grep -E "harbor_(up|health|project_quota)"
# → harbor_up{job="harbor"} 1
# → harbor_project_quota_usage_byte{project="production"} 5.4e+09

# Docker Registry 2.x/3.x: включение метрик в config.yml
# metric:
#   prometheus:
#     enabled: true
#     path: /metrics
```

Алерты: `harbor_up == 0`, `harbor_health != 1`, disk usage на volume registry > 80%, `harbor_project_quota_usage_byte / harbor_project_quota_byte > 0.85`.

### Сценарий 8: Ротация credential-ов и секретов

```bash
# Robot-аккаунт: срок действия 30 дней, автоматическая ротация через API
harbor project robot create --project myproject --name ci-bot --duration 30d --pull-permission
# → Secret показывается один раз; для ротации — Refresh Secret

# В Kubernetes: ImagePullSecret с robot-аккаунтом
kubectl create secret docker-registry regcred \
  --docker-server=registry.example.com \
  --docker-username='robot$myproject+ci-bot' \
  --docker-password='SECRET_TOKEN'
```

### Сценарий 9: Admission Control в Kubernetes (Kyverno)

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-image-signature
spec:
  validationFailureAction: Enforce
  background: false
  webhookTimeoutSeconds: 30
  failurePolicy: Fail
  rules:
    - name: check-signature
      match:
        any:
        - resources:
            kinds:
              - Pod
      verifyImages:
        - imageReferences:
          - "registry.example.com/*"
          verifyDigest: true
          attestations:
          - predicateType: cosign.sigstore.dev/attestation/v1
            condition:
              all:
              - key: "{{ scan_result }}"
                operator: NotIn
                value: ["HIGH", "CRITICAL"]
          attestors:
            - count: 1
              entries:
              - keys:
                  publicKeys: |-
                    -----BEGIN PUBLIC KEY-----
                    ...
                    -----END PUBLIC KEY-----
```

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `unable to ping registry endpoint` | TLS-сертификат не доверен клиенту | Скопировать CA в `/etc/docker/certs.d/<host>/ca.crt`; или `--insecure-registry` только для dev |
| Push отклонён | RBAC: нет прав на repository | Проверить роль в Harbor; робот-аккаунт для CI |
| Тег перезаписан | Нет immutable-tag политики | Включить immutable tags; пинить по digest |
| `manifest unknown` | Тег удалён retention или GC ещё не отработал | Проверить retention policy; запустить GC; использовать digest |
| `TOOMANYREQUESTS` | Rate limit upstream (Docker Hub) | Прокси-кэш Harbor; аутентификация; scheduler запросов |
| Cosign: подпись не найдена | Реестр не поддерживает OCI 1.1 Referrers | Обновить Harbor до 2.11+; для старых — `--legacy-include-operations` |
| Kyverno не блокирует | `background: true` или `match.kinds` неверен | `background: false`; проверить `kubectl describe clusterpolicy` |
| Секрет robot-аккаунта утерян | Токен не хранится в Harbor | Refresh Secret: старый перестаёт работать; ротация через API |
| `harbor_up == 0` | Компонент упал | `curl -sk https://harbor.example.com/api/v2.0/health`; логи pod-а |

## Граничные случаи

* **Shared IP / NAT:** rate limit анонимных pull считается на IPv4-адрес или IPv6 /64-подсеть — CI-флеты и корпоративные сети делят одну квоту; аутентификация или прокси-кэш обязательны.
* **Docker Content Trust retirement:** `notary.docker.io` отключается 08.12.2026; DCT ломается на официальных образах с 08.08.2025. Удалите `DOCKER_CONTENT_TRUST=1` из окружения; мигрируйте на Cosign/Notation.
* **Multi-arch подписи:** подпись привязывается к каждому child-образу манифест-листа отдельно; `cosign verify` проверяет только выбранный клиентом манифест (обычно amd64).
* **Air-gapped / офлайн-реестры:** публичный Sigstore недоступен; используйте self-hosted Fulcio/Rekor или ключ-based подпись (Cosign `--key`).
* **Self-signed TLS и Cosign:** Cosign может отказаться подписывать образ в реестре с self-signed сертификатом; добавьте CA в `SSL_CERT_FILE` или system trust store.
* **PQC (ML-DSA):** Cosign v3.x поддерживает `--sign-algorithm mldsa`, но не все Admission Controllers и реестры recognise PQC-подписи — проверяйте совместимость перед production.
* **Кросс-реестр promotion:** при promotion staging→prod подпись не переносится автоматически; переподписывайте в prod-реестре или используйте `cosign copy`.
* **Registry GC и 2-часовое окно:** Harbor GC не удаляет артефакты, загруженные за последние 2 часов; остановка GC не восстанавливает удалённое.
* **Robot-аккаунт без интерфейса:** не может войти в веб-Harbor, только API/CLI; при утере секрета — Refresh Secret.
* **Смена `secretKey` в Harbor необратима:** `keyval`-таблица не перешифровывается автоматически; старые сессии/токены инвалидируются. Планируйте ротацию как плановое мероприятие, а не runtime-операцию.

## Лучшие практики

1. **Приватный registry — единственный источник** для production; public — только базовые образы, проверенные по digest.
2. **TLS 1.2+ everywhere** — никаких insecure-registries в production; corporate CA или Let's Encrypt.
3. **Сканирование при push** (Harbor/Trivy) с блокировкой CRITICAL без fixed-версии.
4. **Подписи и attestations** (Cosign keyless или Notation) + проверка перед развёртыванием через Kyverno/OPA.
5. **Immutable tags** для release-тегов; пининг по digest в манифестах деплоя.
6. **RBAC и робот-аккаунты** для CI с expiration и minimal permissions; аудит пуш/pull в SIEM.
7. **Retention и GC** — политика хранения, автоматическая очистка untagged; GC по расписанию вне пиков.
8. **Network isolation:** registry доступен только из доверенных подсетей (CI/CD, K8s nodes); rate limiting на ingress; firewall rules.
9. **Secrets management:** credential-ы registry не в переменных CI/CD, а в Vault/Sealed Secrets/K8s Secrets с encryption at rest.
10. **Мониторинг и алерты:** `harbor_up`, disk usage, quota usage, rate limit остатки; интеграция с Prometheus/Grafana.
11. **Гигиена public-реестров:** typo-squatting, dependency confusion, rate limits — см. [public_registry_security.md](../Docker_registries/public_registry_security.md).
12. **Supply chain transparency:** SBOM и provenance прикрепляются к образу как аттестации; требуйте их наличия для сторонних образов.
13. **Кросс-реестр promotion:** при перемещении образа между контурами переподписывайте или переносите аттестации через `cosign copy`.
14. **Registry hardening:** для Docker Registry 2.x/3.x включите `delete.enabled`, `storage.maintenance.readonly.enabled` при GC, отключите неиспользуемые API. См. [docker_registries.md](../docker_registries.md).
15. **Верификация версий сканеров и подписей:** фиксируйте версии Cosign/Trivy (≥ 0.70.1) с SHA256-контрольными суммами. Обновляйте при выходе CVE (CVE-2026-33634).

## Дополнительная информация

**Связанные документы:**

- [Public registry security](../Docker_registries/public_registry_security.md) — SSoT: typo-squatting, dependency confusion, rate limits, DCT retirement.
- [Версионирование и теги](../Docker_registries/image_versioning_and_tagging.md) — SSoT: immutable tags, семантика.
- [Подписание и верификация образов](../Docker_security/image_signature_and_verification.md) — SSoT: Cosign, Notation, Kyverno, VSA.
- [Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md) — SSoT: Trivy, Grype, Copacetic.
- [Docker SBOM](../Docker_security/docker_sbom.md) — SSoT: генерация SBOM, VEX.
- [Harbor: overview](../Docker_registries/Harbor/overview.md), [installation](../Docker_registries/Harbor/installation.md), [usage](../Docker_registries/Harbor/usage.md), [hardening](../Docker_registries/Harbor/hardening.md), [certificates](../Docker_registries/Harbor/certificates.md), [offline Trivy update](../Docker_registries/Harbor/offline_trivy_update.md).
- [GC и retention](../Docker_fs/cleanup_gc_strategies.md) — SSoT: очистка registry и Docker Engine.
- [Supply Chain Security](../../Security/Supply_Chain_Security/) — SLSA, provenance.

**Внешние ресурсы:**

- [Docker Registry (distribution)](https://distribution.github.io/distribution/) — reference registry (v2.8.3 последняя 2.x; v3.1.x текущая на 2026).
- [Harbor](https://goharbor.io/) — enterprise registry.
- [Cosign](https://docs.sigstore.dev/cosign/overview/) — подписи образов.
- [Notation](https://notaryproject.dev/) — OCI artifact signatures.
- [Kyverno](https://kyverno.io/) — admission control.

**Инструменты:** `registry:2`/`registry:3`, Harbor, `trivy` (≥ 0.70.1), `cosign` (v3.x), `notation` (v1.x), `skopeo`, `kyverno`, `vault`.
