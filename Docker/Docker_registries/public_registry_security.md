# Безопасность при работе с публичными реестрами

**Актуально для:** Docker Hub (лимиты и статус DCT на 2026), Docker Engine 29.x, Cosign v3.x, Kyverno 1.12+, Trivy 0.69.x

## Определения

*   **Угрозы публичных реестров**: Использование публичных репозиториев, таких как Docker Hub, создает риски для [безопасности цепочки поставок ПО](../../Security/Supply_Chain_Security/overview.md). Основные угрозы включают:
    *   **Подмена образа (Image spoofing)**: Злоумышленник перезаписывает легитимный изменяемый тег (например, `:latest`).
    *   **Typo-squatting**: Публикация вредоносных образов с именами, похожими на официальные (например, `postgresl` вместо `postgresql`).
    *   **Уязвимые зависимости**: Использование базовых образов с известными уязвимостями **CVE (Common Vulnerabilities and Exposures)**.
    *   **Подмена зависимостей (Dependency Confusion)**: Риск публикации злоумышленником вредоносного образа в публичном реестре под тем же именем, что и внутренний приватный образ, что может привести к ошибочной загрузке вредоносного артефакта.
*   **Квотирование (Rate Limiting)**: Ограничение количества запросов на загрузку образов. Docker Hub различает два вида лимитов:
    *   **Pull limit** — лимит на загрузку образов: 100 pull-запросов за 6 часов для анонимных пользователей (считается на IPv4-адрес или IPv6 /64-подсеть), 200 за 6 часов для аутентифицированных аккаунтов Personal, без лимита для Pro/Team/Business. При превышении возвращается `429` с развёрнутым сообщением: `You have reached your pull rate limit. You may increase the limit by authenticating and upgrading: https://www.docker.com/increase-rate-limits`.
    *   **Abuse limit** — защита от злоупотреблений (~тысячи запросов в минуту), применяется ко всем пользователям одинаково независимо от уровня аккаунта и возвращает простой `429 Too Many Requests`.
*   **Примитивы безопасности**:
    *   **Дайджест (Digest)**: Криптографический идентификатор (SHA-256), гарантирующий неизменность содержимого образа.
    *   **Подпись образа (Image Signature)**: Криптографическое подтверждение издателя и целостности. Детали см. в [подписании и верификации образов](../Docker_security/image_signature_and_verification.md).
    *   **SBOM (Software Bill of Materials)**: Подробный перечень всех компонентов ПО внутри образа. Детали см. в [Docker SBOM](../Docker_security/docker_sbom.md).

> **Статус:** Docker Content Trust (DCT, Notary v1) выведен из эксплуатации. Объявление — 29.07.2025, проект Notary архивирован 30.07.2025, сертификаты подписи Docker Official Images начали истекать 08.08.2025 (pull с `DOCKER_CONTENT_TRUST=1` ломается), сервис `notary.docker.io` отключается 08.12.2026. Современные альтернативы — Sigstore/Cosign и Notation (Notary Project).

## Основные концепции

Для минимизации рисков при работе с публичными реестрами применяется многоуровневая защита.

| Риск | Меры контроля |
| :--- | :--- |
| **Подмена/изменение образа** | Использование дайджеста вместо тега (`pull by digest`), проверка подписей (Cosign). |
| **Typo-squatting** | Использование белых списков (allow-lists) доверенных реестров и пространств имен. |
| **Уязвимости в слоях** | Обязательное [сканирование уязвимостей](../Docker_security/vulnerability_scanning.md) в CI/CD пайплайнах. |
| **Секреты внутри образа** | Сканирование на наличие секретов (Trivy, Gitleaks), использование multi-stage сборок. |
| **Непрозрачность состава** | Генерация и анализ SBOM, аттестации происхождения (provenance). |
| **Превышение лимитов (429)** | Аутентификация в реестре, использование локального прокси-кэша. |
| **Dependency Confusion** | Использование полных FQDN имен образов и блокировка внешних реестров в Admission Control. |

Ключевой стратегией является использование **локального прокси-кэша** (например, [Harbor](./Harbor/overview.md) или Nexus). Он кэширует образы из публичных реестров, позволяя применять централизованные политики безопасности:
*   Запрет на использование изменяемых тегов (например, `:latest`).
*   Автоматическое сканирование на уязвимости и блокировка при наличии критических CVE.
*   Снижение нагрузки на внешние каналы и обход Rate Limits: 200-узловой кластер генерирует один upstream-pull вместо 200.

## Предварительные требования

*   **Docker Engine 29.x** — команды `docker pull`, `docker inspect`, `docker login`.
*   **Cosign v3.x** — верификация подписей и аттестаций (Sigstore).
*   **Trivy 0.69.x** — сканирование уязвимостей и секретов.
*   **Kyverno 1.12+** — Admission Control для принудительной верификации подписей в Kubernetes.
*   **curl и jq** — проверка оставшихся лимитов Docker Hub через заголовки ответа.

## Практические сценарии

### Сценарий 1: Фиксация образа по дайджесту

Использование дайджеста гарантирует неизменность образа вне зависимости от обновлений тега в реестре.

```bash
# 1. Получение дайджеста для конкретного тега
docker inspect --format='{{index .RepoDigests 0}}' nginx:1.31
# → nginx@sha256:<digest>

# 2. Pull по дайджесту — содержимое зафиксировано криптографически
docker pull nginx@sha256:<digest>

# 3. Использование дайджеста в Dockerfile или K8s манифесте
# FROM nginx@sha256:<digest>
# image: nginx@sha256:<digest>
```

> `<digest>` — placeholder: замените на реальное значение из вывода команды.

### Сценарий 2: Проверка подписи образа через Cosign

Обеспечивает гарантию того, что образ был выпущен доверенным издателем. Cosign v3 поддерживает два режима: key-based (публичный ключ издателя) и keyless (OIDC-identity подписанта, например GitHub Actions).

```bash
# Key-based verification
cosign verify --key cosign.pub ghcr.io/org/app:1.4.3

# Keyless verification (identity and OIDC issuer of the signer)
cosign verify \
  --certificate-identity "https://github.com/org/app/.github/workflows/release.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/org/app:1.4.3

# Verify attached attestation (e.g., SBOM)
cosign verify-attestation --type=spdx --key cosign.pub ghcr.io/org/app:1.4.3
```

### Сценарий 3: Сканирование на уязвимости и секреты (Trivy)

Интеграция сканирования в CI-пайплайн для автоматической блокировки небезопасных сборок.

```bash
# Сканирование образа на CVE с блокировкой по коду возврата
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 nginx:1.31

# Сканирование на наличие секретов (пароли, ключи, токены)
trivy image --scanners secret nginx:1.31
```

### Сценарий 4: Проверка и обход лимитов Docker Hub

Лимиты Docker Hub считаются за 6 часов и привязаны к IPv4-адресу или IPv6 /64-подсети (для анонимных). Для CI/CD систем рекомендуется использовать выделенную сервисную учетную запись.

```bash
# 1. Анонимный токен для проверки лимитов
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq -r .token)

# 2. Текущие лимиты через заголовки ответа
curl -sI -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest
# → ratelimit-limit: 100;w=21600
# → ratelimit-remaining: 20;w=21600
# → docker-ratelimit-source: 192.0.2.1

# 3. Токен аутентифицированного пользователя (Personal — 200 pull/6h)
TOKEN=$(curl -s -u "$DOCKER_USERNAME:$DOCKER_PASSWORD" \
  "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq -r .token)

# 4. Авторизация в Docker Hub для увеличения лимитов
echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
```

Текущие лимиты pull за 6 часов:

| Тип учётной записи | Лимит pull / 6 часов |
| :--- | :--- |
| Анонимный | 100 на IPv4-адрес или IPv6 /64-подсеть |
| Personal (аутентифицированный) | 200 |
| Pro / Team / Business | Без лимита (fair use) |

### Сценарий 5: Принудительная проверка подписей (Kyverno)

Блокировка запуска неподписанных образов в кластере Kubernetes. Правило `verifyImages` выполняется как часть mutation webhook (может подставить дайджест) и validation webhook; `verifyDigest: true` (по умолчанию) требует фиксации образа дайджестом.

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
          - "ghcr.io/my-org/*"
          verifyDigest: true
          attestors:
            - count: 1
              entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      ...
                      -----END PUBLIC KEY-----
```

### Сценарий 6: Mirror и прокси-кэш

Для снятия нагрузки с Docker Hub и обхода лимитов используются зеркала и прокси-кэши:

```json
// /etc/docker/daemon.json — Docker Engine registry mirror
{
  "registry-mirrors": ["https://mirror.gcr.io"]
}
```

> `mirror.gcr.io` кэширует только официальные образы Docker (`library/*`); сторонние образы не проксируются. Для полного покрытия разверните Harbor в режиме Proxy Cache: создайте Registries Endpoint для `https://registry-1.docker.io` и pull-ите образы через локальный проект кэша — см. [Harbor usage](./Harbor/usage.md), сценарий 6. Перед отдачей из кэша Harbor проверяет upstream HEAD-запросом, что не расходует квоту rate limiter.

## Валидация

```bash
# Digest pinning: DIGEST в выводе должен совпадать с зафиксированным
docker images --digests nginx
# → REPOSITORY   TAG    DIGEST                            IMAGE ID
#   nginx        1.31   sha256:<digest>                   sha256:...

# Signature verification: exit code 0 — образ подписан доверенным ключом
cosign verify --key cosign.pub ghcr.io/org/app:1.4.3 && echo "verified"

# Vulnerability gate: exit code 1 — найдены HIGH/CRITICAL CVE
trivy image --severity HIGH,CRITICAL --exit-code 1 nginx:1.31; echo "exit=$?"

# Kyverno: политика в режиме принудительного применения
kubectl get clusterpolicy check-image-signature -o jsonpath='{.spec.validationFailureAction}'
# → Enforce
```

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `429` с развёрнутым сообщением и ссылкой на `docker.com/increase-rate-limits` | Превышен pull limit Docker Hub (100/6h анонимно, 200/6h Personal) | Аутентификация (`docker login`), прокси-кэш Harbor, mirror |
| Простой `429 Too Many Requests` | Abuse limit Docker Hub (~тысячи запросов/мин, действует для всех аккаунтов) | Снизить частоту запросов; проверить CI-флот на shared NAT |
| Pull Docker Official Images падает с ошибкой trust/сертификата | Установлено `DOCKER_CONTENT_TRUST=1`: DCT retired, сертификаты DOI истекают с 08.08.2025 | Снять переменную: `unset DOCKER_CONTENT_TRUST`; перейти на Cosign/Notation |
| `cosign verify`: подписи не найдены | Образ не подписан или подписи хранятся в отдельном репозитории | Проверить наличие подписей; в Kyverno указать `repository` для fetch подписей |
| Kyverno: под запускается несмотря на политику | `background: true` — политика не применяется к существующим объектам; webhook недоступен | `background: false`; проверить `kubectl get validatingwebhookconfiguration` |
| Содержимое тега `:latest` изменилось после пересборки | Mutable tag | Фиксировать образ дайджестом (сценарий 1) |

## Граничные случаи

*   **Shared IP / NAT**: лимит анонимных pull считается на IPv4-адрес или IPv6 /64-подсеть — CI-флеты и корпоративные сети делят одну квоту; аутентификация или прокси-кэш обязательны.
*   **Объявленные, но не применённые лимиты**: 1 апреля 2025 Docker объявила почасовые лимиты (10/ч анонимно, 100/ч для free-аккаунтов) и плату за pull; 8 апреля подтвердила, что лимиты не применялись, а плата отменена. Актуальная модель — 6-часовые окна.
*   **DCT/Notary v1 retirement**: `notary.docker.io` отключается 08.12.2026 (brownout-окна в июле–августе 2026). Azure ACR выводит DCT 31.03.2028. Миграция — на Sigstore/Cosign или Notation.
*   **Multi-arch образы**: `RepoDigests` содержит дайджест manifest list; для фиксации конкретной платформы используйте `docker buildx imagetools inspect --raw` и дайджест платформенного манифеста.
*   **Immutable Tags**: в приватном реестре включайте иммутабельность тегов (Harbor: проект → immutable tags), чтобы предотвратить случайную или намеренную перезапись тегов версий.
*   **Dependency Confusion**: при использовании внутренних реестров всегда указывайте полный FQDN образа (`registry.example.com/org/app`) и блокируйте внешние реестры в Admission Control.

## Лучшие практики

*   **Admission Control**: Используйте механизмы Kubernetes (**ImagePolicyWebhook**, Kyverno, OPA Gatekeeper) для ограничения источников образов (разрешать только внутренний Harbor).
*   **Анализ цепочки поставок**: Генерируйте SBOM для каждого собственного образа и требуйте его наличия для сторонних образов. Это позволяет быстро идентифицировать наличие уязвимой библиотеки (например, log4j) во всей инфраструктуре.
*   **Очистка (Garbage Collection)**: Регулярно удаляйте неиспользуемые и старые образы из локального кэша и реестра для минимизации поверхности атаки.
*   **Allow-lists**: Ведите белые списки доверенных реестров и пространств имен (например, `docker.io/library/*`, `ghcr.io/org/*`) вместо блокировки по чёрному списку.
*   **Service accounts**: Для CI/CD используйте выделенные учётные записи Docker Hub с минимальными правами; не используйте личные аккаунты в автоматизации.

## См. также

*   **[Подписание и верификация образов](../Docker_security/image_signature_and_verification.md)** — глубокое погружение в Cosign и Notation.
*   **[Сканирование уязвимостей](../Docker_security/vulnerability_scanning.md)** — выбор инструментов и настройка Trivy.
*   **[Docker SBOM](../Docker_security/docker_sbom.md)** — генерация и анализ SBOM.
*   **[Безопасность цепочки поставок ПО](../../Security/Supply_Chain_Security/overview.md)** — концептуальный обзор SLSA и SBOM.
*   **[Обзор Harbor](./Harbor/overview.md)** — настройка безопасного прокси-кэша.
*   **[Harbor: использование](./Harbor/usage.md)** — сценарий 6: Proxy Cache для Docker Hub.
*   **[Диагностика ошибок загрузки образов](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/diagnostics.md)** — разбор `429 Too Many Requests` в Kubernetes.
*   **Документация Docker Hub**: [pull usage and limits](https://docs.docker.com/docker-hub/usage/pulls/).
*   **Docker**: [Retiring Docker Content Trust](https://www.docker.com/blog/retiring-docker-content-trust) (объявление о выводе DCT из эксплуатации).
*   **Kyverno**: [Verify Images Rules](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/overview).
