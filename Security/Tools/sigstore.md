# Sigstore: Безопасность цепочки поставок ПО

**Актуально для:** Cosign v3.1.3, Fulcio v1.9.0, Rekor v1.5.4, Gitsign v0.17.1

> **Статус:** Sigstore — активно развиваемая open-source экосистема для keyless-подписи программных артефактов. Поддерживается CNCF и не является устаревшей.

## Определения

* **Sigstore** ([sigstore.dev](https://www.sigstore.dev/)) — открытая экосистема и набор стандартов для безопасной подписи, верификации и прозрачности программных артефактов (образов контейнеров, бинарных файлов, SBOM, Helm-чартов, Terraform-модулей). Устраняет необходимость управлять долгоживущими закрытыми ключами, заменяя их краткосрочными сертификатами на основе OIDC-идентичности.
* **Fulcio** — корневой удостоверяющий центр (CA), который выдает краткосрочные (10 минут) сертификаты X.509 в обмен на OIDC-токен. Сертификат привязывается к подтвержденной личности (email, CI-раннер), а не к публичному ключу.
* **Rekor** — неизменяемый журнал прозрачности (transparency log / Immutable Ledger), построенный на дереве Меркла. Записывает все события подписи и метаданные, обеспечивая аудит и обнаружение компрометации сертификатов.
* **Cosign** — основной CLI-инструмент Sigstore для подписи и верификации артефактов. Поддерживает keyless-подпись через Fulcio, запись в Rekor, аттестации (SBOM, SLSA Provenance) и работу с OCI 1.1 Referrers API.
* **Gitsign** — расширение Sigstore для Git, позволяющее подписывать коммиты и теги с использованием OIDC-идентичности вместо традиционных GPG/SSH-ключей. Интегрируется с системами контроля версий как встроенный Git signer.
* **OIDC (OpenID Connect)** — протокол аутентификации, используемый Fulcio для подтверждения личности подписанта. CI/CD-платформы (GitHub Actions, GitLab CI, Gitea) выступают в роли OIDC-провайдеров.
* **Keyless Signing (Подпись без ключей)** — модель, при которой приватный ключ генерируется эфемерно (в памяти CI-раннера), сертификат выпускается на короткий срок (10 минут) через Fulcio, а все события записываются в Rekor. Закрытый ключ уничрождается после подписи.
* **SCT (Signed Certificate Timestamp)** — доказательство включения сертификата в журнал прозрачности сертификатов (Certificate Transparency), встраиваемое Fulcio в выдаваемые сертификаты.
* **SET (Signed Entry Timestamp)** — криптографическое доказательство того, что подпись была зафиксирована в Rekor в определенное время. Доступно в inclusion proof записи Rekor.
* **Bundle** — сертификат + подпись + SET, упакованные в единый артефакт. С версии Cosign v2.6+ формат bundle стал основным (старый формат поддерживается через `--new-bundle-format=false`).
* **Transparency Log** — публичный, доступный только для добавления реестр всех событий подписи. Обеспечивает ретроспективный аудит и обнаружение компрометаций.
* **OCI 1.1 Referrers API** — стандарт OCI Distribution 1.1 для связывания метаданных (подписей, SBOM, аттестаций) с основным артефактом через поле `subject`, а не через дополнительные теги.
* **TUF (The Update Framework)** — фреймворк для защиты целостности системы дистрибуции обновлений. Sigstore использует TUF для распространения доверенного корня (root.json) с публичными ключами Fulcio и Rekor.

## Основные концепции

### Архитектура Sigstore

Sigstore объединяет четыре компонента для создания доверенной среды подписи:

```text
CI/CD Runner / Developer
        │
        │ 1. OIDC Token
        │
        ▼
┌─────────────┐     2. X.509 Certificate      ┌──────────────┐
│   Fulcio    │ ◄──────────────────────────── │ Ephemeral Key │
│  (CA)       │                               │  (in memory)  │
│             │                              └──────────────┘
│ • OIDC      │                                      │
│ • SCT       │                                      │ 3. Signature
└─────┬───────┘                                      ▼
      │                                              │
      │ 4. Cert + Signature + SET                   │
      ▼                                              │
┌─────────────┐                                      │
│   Rekor      │ ◄──────────────────────────────────┘
│ (Log)       │     5. Inclusion Proof (SET)
│             │
│ • Merkle    │
│ • Append-only │
└─────┬───────┘
      │ 6. TUF root.json
      ▼
┌─────────────┐
│   TUF        │
│ (Trust)     │
│             │
│ • root.json  │
│ • Key rotation │
└─────────────┘
```

### Fulcio: удостоверяющий центр для keyless-подписи

Fulcio — это HTTP API сервис (gRPC + REST), который:

1. Принимает запрос на выпуск сертификата с **OIDC access token**.
2. Проверяет токен через **JWKS endpoint** OIDC-провайдера (GitHub, GitLab, Gitea и т.д.).
3. Извлекает **Subject** (email, sub, workflow URL) из токена.
4. Выпускает **X.509 сертификат** на 10 минут, где:
   - `Subject` = OIDC identity
   - `PublicKey` = ephemeral public key от подписанта
   - `Issuer` = OIDC provider URL
   - `SCT` = встроенный Signed Certificate Timestamp от CT Log
5. Сертификат используется только для одной подписи, затем уничтожается.

**Ключевое свойство:** сертификат привязывается к **личности**, а не к ключу. Это означает, что даже если ключ скомпрометирован, злоумышленник не получит доступ к вашей учетной записи OIDC.

### Rekor: журнал прозрачности

Rekor — это **append-only** журнал на основе **дерева Меркла**, который записывает:

- Метаданные сертификата и подписи
- `SignedEntryTimestamp` (SET) — доказательство записи в лог
- Inclusion proof — криптографическое доказательство наличия записи без загрузки всего лога

Запись в Rekor создаётся каждый раз при подписи. При верификации Cosign:

1. Загружает запись из Rekor по индексу (int, UUID, или SHA256)
2. Проверяет Merkle inclusion proof
3. Проверяет SET — подтверждение, что запись существует в логе в определенный момент времени

Это обеспечивает **ретроспективную проверку**: даже если сертификат уже истёк, запись в Rekor остаётся доказательством подписи.

### Cosign: архитектура CLI

Cosign v3.1.3 — это Go-бинарник с модульной архитектурой:

- **Sign path:** генерирует ephemeral ключ → запрашивает OIDC токен → получает сертификат от Fulcio → подписывает артефакт → загружает запись в Rekor → формирует bundle
- **Verify path:** извлекает bundle из реестра → проверяет сертификат (chain to Fulcio root) → проверяет Rekor inclusion proof → сравнивает identity с `--certificate-identity`
- **Attestation path:** создаёт in-toto Statement с predicate (SLSA Provenance, SBOM, VSA) → подписывает как обычный артефакт → хранит через Referrers API

Cosign v3.1.x по умолчанию использует **bundle format** для новых подписей. Старый формат (`.sig` теги) поддерживается для обратной совместимости через `--new-bundle-format=false`.

### Keyless-подпись: механизм работы

1. **Генерация:** CI/CD-раннер или пользователь генерирует эфемерную пару ключей (ECDSA-P256) только в оперативной памяти.
2. **Аутентификация:** Получение OIDC токена от провайдера (GitHub Actions, GitLab CI, Gitea). Токен содержит claim `sub` (subject) и `iss` (issuer).
3. **Сертификация:** Fulcio проверяет OIDC токен через JWKS endpoint провайдера и выдает сертификат X.509 (10 минут), где `Subject` = OIDC identity, `PublicKey` = ephemeral public key.
4. **Публикация в Rekor:** Метаданные (сертификат + подпись) отправляются в Rekor, который создаёт inclusion proof и возвращает SET.
5. **Подписание:** Артефакт подписывается эфемерным закрытым ключом. Bundle (сертификат + подпись + SET) загружается в реестр через OCI 1.1 Referrers API.
6. **Очистка:** Закрытый ключ уничтожается. Сертификат истекает через 10 минут, но подпись остаётся валидной бесконечно благодारя Rekor.

### Gitsign: подпись Git-коммитов

**Gitsign** — это расширение Sigstore для Git, которое позволяет подписывать коммиты с использованием OIDC-идентичности вместо традиционных GPG/SSH-ключей. Это предотвращает атаки на подмену авторства в репозиториях без оверхеда на управление ключами разработчиков.

#### Конфигурация

Gitsign настраивается через `git config` или переменные окружения:

**Переменные окружения:**

| Переменная | По умолчанию | Описание |
| :--- | :--- | :--- |
| `GITSIGN_FULCIO_URL` | `https://fulcio.sigstore.dev` | Адрес Fulcio (для self-hosted: `https://fulcio.internal`) |
| `GITSIGN_REKOR_URL` | `https://rekor.sigstore.dev` | Адрес Rekor |
| `GITSIGN_OIDC_ISSUER` | `https://oauth2.sigstore.dev/auth` | OIDC провайдер |
| `GITSIGN_OIDC_CLIENT_ID` | `sigstore` | Client ID для OIDC |
| `GITSIGN_REKOR_MODE` | `online` | `online` (хранить commit SHAs в Rekor) или `offline` (хранить хеши, для автономной верификации) |
| `GITSIGN_FULCIO_ROOT` | — | Путь к PEM-файлу с корневым сертификатом Fulcio |

**Git-config опции:**

```bash
# Автоматическая конфигурация для GitHub Actions
git config --global gitsignissuer "https://token.actions.githubusercontent.com"
git config --global gitsignfulcio "https://fulcio.sigstore.dev"
git config --global gitsignrekor "https://rekor.sigstore.dev"
```

#### Режимы аутентификации

| Provider | Описание |
| :--- | :--- |
| `interactive` | Интерактивный OAuth flow через браузер |
| `device` | OAuth 2.0 device flow — для headless / remote-SSH workflows |
| `github-actions` | Автоматическое использование OIDC токена раннера |
| `filesystem` | Чтение токена из файла (для air-gapped) |

#### Верификация коммитов

```bash
# Проверить подпись коммита
git verify-commit <commit-sha>
# → gpg: Signature made ... using RSA
#     gpg:                issuer "..."

# Автоматическая проверка всех коммитов в ветке
git log --show-signature --oneline
```

## Предварительные требования

### Инструменты

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Cosign** | v3.1.3 | CLI для подписи/верификации артефактов, аттестаций, blob-подписей |
| **Fulcio** | v1.9.0 | CA для keyless-подписи (self-hosted или публичный) |
| **Rekor** | v1.5.4 | Журнал прозрачности (self-hosted или публичный) |
| **Gitsign** | v0.17.1 | Подпись Git-коммитов через Sigstore |
| **Policy Controller** | v0.9.x | Kubernetes admission webhook для проверки подписей |
| **Kubernetes** | 1.27+ | Целевая платформа для Policy Controller |
| **Helm** | v3 | Установка Policy Controller |
| **OIDC provider** | — | GitHub Actions, GitLab CI (15.7+), Gitea, или корпоративный IdP |

### Self-hosted Sigstore

Для on-prem развертывания требуются:

- **Fulcio** — сервис CA в отдельном namespace (`fulcio-system`)
- **Rekor** — сервис transparency log (`rekor-system`)
- **TUF root** — сервис для распространения root.json (`tuf-system`)
- **CTLog** — журнал сертификатов для SCT (опционально, `ctlog-system`)
- **TLS certificates** — для Fulcio, Rekor, TUF (self-signed или внутренняя CA)
- **OIDC provider** — GitHub, GitLab, Gitea, или корпоративный IdP с поддержкой OIDC

Детали self-hosted развёртывания через `sigstore/scaffolding` описаны в [sigstore_vs_notation.md](../Supply_Chain_Security/sigstore_vs_notation.md#сценарий-1-настройка-sigstore-keyless-для-gitlab-ci).

## Практические сценарии

### Keyless-подпись в GitHub Actions

В современных пайплайнах Cosign автоматически использует **ambient OIDC credentials** (токены раннера GitHub Actions).

```yaml
jobs:
  build-and-sign:
    permissions:
      contents: read
      packages: write
      id-token: write # Обязательно для keyless/Fulcio
    steps:
      - uses: sigstore/cosign-installer@v3
      - name: Sign the container image
        run: cosign sign --yes ghcr.io/${{ github.repository }}:latest
```

### Проверка подписи с контролем идентичности

Просто проверка наличия подписи недостаточна. Важно проверять, **кто** подписал артефакт.

```bash
cosign verify \
  --certificate-identity "https://github.com/my-org/my-repo/.github/workflows/release.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  ghcr.io/my-org/my-app:latest
```

**Для GitLab CI / Gitea:** аналогичная настройка требует `id_tokens` и `--fulcio-url`/`--rekor-url` для self-hosted Sigstore. Подробнее — в [sigstore_vs_notation.md](../Supply_Chain_Security/sigstore_vs_notation.md#сценарий-1-настройка-sigstore-keyless-для-gitlab-ci).

### Подпись и аттестация SBOM

```bash
# Привязка SBOM в формате CycloneDX к образу через аттестацию
cosign attest --yes --predicate sbom.json --type cyclonedx ghcr.io/my-org/my-app:latest
```

**Для генерации SBOM:** используйте Syft (`syft <image> -o cyclonedx-json > sbom.json`). Подробнее о SBOM и SCA — в [dependency_and_sbom_analysis.md](../Supply_Chain_Security/dependency_and_sbom_analysis.md).

### Gitsign: подпись коммитов в CI/CD

```yaml
# .github/workflows/release.yaml
jobs:
  release:
    permissions:
      id-token: write  # OIDC для Gitsign
      contents: write
    steps:
      - uses: actions/checkout@v4
      - name: Install Gitsign
        run: |
          curl -sSL https://github.com/sigstore/gitsign/releases/download/v0.17.1/gitsign-linux-amd64 -o /usr/local/bin/gitsign
          chmod +x /usr/local/bin/gitsign
      - name: Configure Git
        run: |
          git config --global gitsignissuer "https://token.actions.githubusercontent.com"
          git config --global gitsignfulcio "https://fulcio.sigstore.dev"
          git config --global gitsignrekor "https://rekor.sigstore.dev"
          git config --global gpg.format ssh
          git config --global gpg.ssh.program "$(which gitsign)"
          git config --global commit.gpgsign true
```

### Политика допуска в Kubernetes (Policy Controller)

Sigstore Policy Controller — это admission webhook для Kubernetes, который проверяет подписи и аттестации перед созданием пода.

```bash
# 1. Установка Policy Controller
helm repo add sigstore https://sigstore.github.io/helm-charts
helm repo update
kubectl create namespace cosign-system
helm install policy-controller -n cosign-system sigstore/policy-controller

# 2. Включение webhook для namespace
kubectl label namespace my-namespace policy.sigstore.dev/include="true"

# 3. Создание ClusterImagePolicy (keyless)
cat > policy.yaml << 'EOF'
apiVersion: policy.sigstore.dev/v1alpha1
kind: ClusterImagePolicy
metadata:
  name: keyless
spec:
  images:
    - glob: "ghcr.io/my-org/*"
  authorities:
    - keyless:
        url: https://fulcio.sigstore.dev
        identities:
          - issuer: "https://token.actions.githubusercontent.com"
            subject: "https://github.com/my-org/.*"
EOF
kubectl apply -f policy.yaml
```

### Air-gapped подпись (без облака)

В изолированных сетях без доступа к публичному Sigstore используйте self-hosted Fulcio и Rekor:

```bash
# 1. Инициализация trust root через TUF
cosign initialize \
  --root https://tuf.internal/root.json \
  --mirror https://tuf.internal

# 2. Подпись с указанием внутренних адресов
cosign sign --yes \
  --fulcio-url https://fulcio.internal \
  --rekor-url https://rekor.internal \
  harbor.internal/my-app:v1

# 3. Верификация
cosign verify \
  --fulcio-url https://fulcio.internal \
  --rekor-url https://rekor.internal \
  --certificate-identity "https://git.internal/my-org/my-app/-/jobs" \
  --certificate-oidc-issuer "https://git.internal" \
  harbor.internal/my-app:v1
```

**Для полностью офлайн-сред:** используйте key-based подпись (сертификаты от внутренней CA) с Notation. Подробнее — в [artifact_signing.md](../Supply_Chain_Security/artifact_signing.md).

## Операции и команды

### Cosign

| Команда | Описание |
| :--- | :--- |
| `cosign sign --yes <image>` | Keyless-подпись образа (по умолчанию bundle format, OCI 1.1 Referrers) |
| `cosign sign --yes --key <key> <image>` | Key-based подпись с долгоживущим ключом |
| `cosign verify <image>` | Проверка подписи и сертификата |
| `cosign verify --certificate-identity <identity> --certificate-oidc-issuer <issuer> <image>` | Проверка с контролем идентичности |
| `cosign sign-blob --yes <file> --bundle <bundle>` | Подпись бинарного файла (blob) |
| `cosign verify-blob <file> --bundle <bundle>` | Верификация подписи blob |
| `cosign attest --yes --predicate <file> --type <type> <image>` | Создание аттестации (SBOM, SLSA, VSA) |
| `cosign verify-attestation <image> --type <type>` | Верификация аттестаций |
| `cosign generate-key-pair` | Генерация key-based пары ключей |
| `cosign initialize --root <tuf-root>` | Инициализация trust root из TUF |
| `cosign copy <src> <dst>` | Копировать образ с подписями между реестрами |
| `cosign tree <image>` | Просмотр связанной информации (подписи, аттестации) |

### Gitsign

| Команда | Описание |
| :--- | :--- |
| `git config --global gpg.ssh.program "$(which gitsign)"` | Настройка Gitsign как Git signer |
| `git config --global commit.gpgsign true` | Автоматическая подпись коммитов |
| `gitsign verify <commit>` | Верификация подписи коммита |
| `gitsign --version` | Проверка версии |

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Error: no identity token found` | OIDC-токен не передан в CI | Добавьте `permissions: id-token: write` в workflow; для GitLab CI — настройте `id_tokens` с `aud: sigstore` (см. [sigstore_vs_notation.md](../Supply_Chain_Security/sigstore_vs_notation.md)) |
| `cosign verify: certificate identity mismatch` | `--certificate-identity` не совпадает с OIDC claim `sub` | Сначала выполните `cosign verify` без фильтров, чтобы увидеть identity, затем укажите точное значение |
| `no signatures found` | Реестр не поддерживает OCI 1.1 Referrers или подпись хранится как `.sig`-тег | Используйте Harbor v2.15+ или GHCR; для старых реестров добавьте `--legacy-include-operations` при подписи |
| `Rekor: inclusion proof failed` | Rekor недоступен в air-gapped среде | Используйте `--rekor-url https://rekor.internal` или `--tlog-upload=false` для локального использования без Rekor |
| `cosign: bundle format not supported` | Используется устаревший клиент Cosign (< v2.6) для чтения нового bundle формата | Обновите Cosign до v3.1.3; для обратной совместимости используйте `--new-bundle-format=false` |
| `gitsign: token provider not available` | OIDC-токен недоступен в headless-окружении | Используйте `GITSIGN_TOKEN_PROVIDER=device` (OAuth 2.0 device flow) или `GITSIGN_TOKEN_PROVIDER=filesystem` с заранее загруженным токеном |
| `Fulcio: invalid OIDC token` | Токен просрочен или issuer не совпадает | Проверьте, что OIDC issuer URL совпадает с настройкой Fulcio; токен действителен 10 минут |
| `certificate signed by unknown authority` | Self-hosted Fulcio использует self-signed сертификат | Добавьте корневой сертификат Fulcio в trust store через `GITSIGN_FULCIO_ROOT` или `SSL_CERT_FILE` |

## Лучшие практики

1. **Предпочитайте keyless:** Keyless-подпись (через OIDC + Fulcio) устраняет риск кражи долгоживущих ключей. Используйте key-based подпись только для air-gapped сред без OIDC.

2. **Всегда проверяйте identity:** Не достаточно проверить, что подпись существует. Используйте `--certificate-identity` и `--certificate-oidc-issuer` для подтверждения, **кто** подписал артефакт. Это предотвращает атаки типа «злоумышленник получил ключ и подписал под себя».

3. **Фиксируйте версии инструментов:** Никогда не используйте `latest` или `v3` для Cosign/Gitsign в CI/CD. Фиксируйте конкретную версию (`cosign-installer@v3.5.0`, `gitsign@v0.17.1`) и проверяйте SHA256-контрольные суммы с сайта релизов.

4. **OCI 1.1 Referrers:** Используйте Harbor v2.15+ или GHCR для хранения подписей через Referrers API. Не используйте устаревшие `.sig`-теги — они затрудняют GC и создают «мусор» в реестре.

5. **Доверенные сертификаты Fulcio:** При self-hosted развертывании регулярно ротируйте корневой сертификат Fulcio и распространяйте новый через TUF root.json.

6. **TUF для trust root:** Используйте TUF для распространения доверенного root.json. Никогда не распространяйте корневые сертификаты через незащищённые каналы.

7. **Отдельный identity для подписи:** Не используйте личную OIDC-учётную запись для подписи. Создавайте выделенные service accounts с минимальными правами.

8. **VSA-ориентированный admission control:** Требуйте VSA-аттестацию (Verification Summary Attestation), агрегирующую результаты проверки подписи + SLSA + SBOM. Подробнее — в [build_integrity.md](../Supply_Chain_Security/build_integrity.md#верификация-vsa-через-admission-controller).

## Очистка и отзыв

### keyless-подпись

Keyless-сертификаты Fulcio автоматически истекают через 10 минут. Дополнительных действий не требуется:

```bash
# Проверить, что сертификат истёк (но подпись в Rekor остаётся валидной)
cosign verify <image> --output json | jq '.signatures[0].certificate'
```

### Key-based подпись

Для key-based подписи (долгоживущие ключи):

```bash
# 1. Ротация ключа (90-дневный цикл)
cosign generate-key-pair --output-key cosign-new.key

# 2. Переподпись артефакта новым ключом
cosign sign --yes --key cosign-new.key <image>

# 3. Удаление старой подписи из реестра
# Через Harbor API:
curl -u "robot$ci-bot:$ROBOT_SECRET" -X DELETE \
  "https://harbor.internal/api/v2.0/projects/my-app/repositories/my-app/artifacts/sha256:<SIG_DIGEST>"
```

### Отзыв сертификатов Fulcio (self-hosted)

При компрометации корневого сертификата Fulcio:

```bash
# 1. Генерация нового корневого сертификата
openssl ecparam -name prime256v1 -genkey | openssl pkcs8 -topk8 -out fulcio-root-key.pem
openssl req -x509 -new -key fulcio-root-key.pem -out fulcio-root.pem -days 365 \
  -subj "/O=Sigstore Internal/CN=Fulcio Root CA"

# 2. Обновление TUF root.json с новым корневым сертификатом
# (см. документацию sigstore/scaffolding)

# 3. Реиндексация trust root на всех клиентах
cosign initialize --root https://tuf.internal/root.json
```

## Дополнительная информация

### Интеграция с Kubernetes

Для обеспечения безопасности в рантайме подписи проверяются автоматически перед запуском пода:

* **Sigstore Policy Controller:** Нативный admission webhook от проекта Sigstore. Поддерживает keyless, key-based и Keyless+Keyless режимы.
* **Kyverno:** Политики `verifyImages` для проверки подписей Cosign и Notation. Поддерживает VSA-аттестации. Подробнее — в [kyverno security policies](../../Kubernetes/Security/kyverno/Scenarios/security_policies.md).
* **OPA Gatekeeper:** Rego-политики для проверки подписей и аттестаций.

### Сравнение: Sigstore vs Notation

Подробное сравнение моделей подписи, когда использовать каждую, а также сценарии для GitLab CI и Harbor — в [sigstore_vs_notation.md](../Supply_Chain_Security/sigstore_vs_notation.md).

| Характеристика | Sigstore (Cosign) | Notation (Notary v2) |
| :--- | :--- | :--- |
| **Управление ключами** | Keyless (OIDC) | X.509 / HSM / Vault |
| **Прозрачность** | Встроенный Rekor Log (TUF) | Опционально через внешние логи |
| **Сфера применения** | Open Source CI/CD, on-prem с self-hosted | Enterprise PKI, HSM, закрытые контуры |
| **Хранение** | OCI 1.1 Referrers API | OCI 1.1 Referrers API |

### Связанные документы

* [Подпись артефактов](../Supply_Chain_Security/artifact_signing.md) — общая методология подписи, Cosign, Notation, VSA, OCI 1.1 Referrers.
* [Sigstore vs Notation: сравнение и выбор](../Supply_Chain_Security/sigstore_vs_notation.md) — когда использовать каждую систему, self-hosted сценарии.
* [Целостность сборки](../Supply_Chain_Security/build_integrity.md) — SLSA, воспроизводимые сборки, TUF, VSA.
* [Анализ зависимостей и SBOM](../Supply_Chain_Security/dependency_and_sbom_analysis.md) — SCA, VEX, инвентаризация.
* [Обзор безопасности цепочки поставок](../Supply_Chain_Security/overview.md) — SLSA, EU CRA, SLSA Provenance.
* [Подписание и верификация Docker-образов](../../Docker/Docker_security/image_signature_and_verification.md) — практика подписи в Docker CI/CD.
* [Docker SBOM](../../Docker/Docker_security/docker_sbom.md) — генерация аттестаций через BuildKit.
